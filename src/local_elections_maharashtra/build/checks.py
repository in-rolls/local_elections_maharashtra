"""Checks on the release, each written down with its result.

- Row accounting, recounted from the committed source files: for every file, sarpanch rows
  read = rows released + rows used only as evidence (winner reports) + rows dropped.
- Provenance: every released row is reopened in its source file at its row number; the file
  must hash to source_sha256 and the printed cells must equal the released *_raw values.
- Keys, column names (the rules of central docs/naming.md) and allowed values.
- Comparisons with other records: Ward-Seat vs counting reservation, SEC winner reports vs
  the winner rules, and women's share of seats within each reserved category.

Writes data/checks/{row_accounting.csv, checks.json, summary.json} and, if absent,
data/checks/hand_check.csv (30 seeded rows for a person to compare with the source).
Exits non-zero if an internal check fails.
"""

import hashlib
import io
import json
import sys

import pandas as pd

from local_elections_maharashtra.paths import CHECKS, EXTRACTS, FETCH_LOG, RELEASE, ROOT, SEARCH_LOG
from local_elections_maharashtra.readers import read_table, sarpanch_mask, tidy

FORBIDDEN_WORDS = {"gender", "sex", "female", "women", "category", "quota"}
RETIRED = {"caste_reservation", "caste_reservation_local", "caste_scheme", "woman_reserved", "women_reserved",
           "female_reserved", "gender_stated", "reservation", "reservation_raw", "winner_gender", "winner_female",
           "candidate_gender", "candidate_female", "candidate_category"}


def naming_violations(columns, booleans=()):
    names, out = set(columns), []
    for name in columns:
        words = set(name.lower().split("_"))
        if words & FORBIDDEN_WORDS:
            out.append(f"{name}: uses {', '.join(sorted(words & FORBIDDEN_WORDS))}")
        if "reservation" in words:
            out.append(f"{name}: uses reservation")
        if name in RETIRED:
            out.append(f"{name}: retired name")
        if name.endswith(("_latin", "_probability")) and name not in booleans and f"{name}_method" not in names:
            out.append(f"{name}: no _method column")
    return out


def main() -> int:
    cand = pd.read_parquet(RELEASE / "sarpanch_candidates.parquet")
    res = pd.read_parquet(RELEASE / "sarpanch_results.parquet")
    dropped = pd.read_csv(CHECKS / "dropped_rows.csv")
    fetch = pd.read_csv(FETCH_LOG, dtype=str, keep_default_na=False)
    extracts = pd.read_csv(EXTRACTS, dtype=str, keep_default_na=False)
    checks = []

    def record(name, kind, ok, result):
        checks.append(dict(check=name, appeals_to=kind, status="pass" if ok is True else ("fail" if ok is False else ok),
                           result=result))

    # ---- recount every committed source file
    tables, read = {}, {}
    for row in fetch[fetch["duplicate_of"] == ""].itertuples():
        data = (ROOT / row.path).read_bytes()
        table = read_table(data)[0]
        tables[row.path] = (hashlib.sha256(data).hexdigest(), table)
        read[row.path] = int(sarpanch_mask(table)[0].sum())
    for row in extracts.itertuples():
        data = (ROOT / row.path).read_bytes()
        table = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        tables[row.path] = (hashlib.sha256(data).hexdigest(), table)
        read[row.path] = len(table)
    evidence = {r.path: int(r.rows_kept) for r in extracts.itertuples() if r.kind == "winner_report"}
    released = pd.concat([cand["source_path"], res.loc[res["in_ward_seat_report"], "source_path"]]).value_counts()
    acc = pd.DataFrame({"read": pd.Series(read), "released": released, "evidence_only": pd.Series(evidence),
                        "dropped": dropped["source_path"].value_counts()}).fillna(0).astype(int)
    acc.index.name = "source_path"
    acc["balanced"] = acc["read"] == acc["released"] + acc["evidence_only"] + acc["dropped"]
    acc.to_csv(CHECKS / "row_accounting.csv")
    record("row_accounting", "internal", bool(acc["balanced"].all()),
           f"{int(acc['balanced'].sum())} of {len(acc)} committed source files balance: sarpanch rows recounted from "
           "each file = released + evidence-only (winner reports) + dropped.")

    # ---- provenance: reopen every row
    bad_sha = bad_val = bad_orig = 0
    for t, pairs in ((cand, [("candidate_name_raw", "Name of Contesting Candidate"), ("votes", "Total Votes Secured"),
                             ("candidate_rank", "Rank"), ("gram_panchayat_raw", "LocalBody Name")]),
                     (res[res["in_ward_seat_report"]], [("reserved_raw", "Reservation"),
                                                        ("gram_panchayat_raw", "LocalBody Name")])):
        for path, g in t.groupby("source_path"):
            digest, table = tables[path]
            bad_sha += int((g["source_sha256"] != digest).sum())
            rows = table.iloc[g["source_row_number"].astype(int) - 1]
            for col, src in pairs:
                bad_val += int((rows[src].astype(str).values != g[col].astype(str).values).sum())
            if "original_row_number" in table:
                bad_orig += int((rows["original_row_number"].astype(int).values != g["original_row_number"].astype(int).values).sum())
    w = res[res["result_source_path"].notna()]
    bad_win = 0
    for path, g in w.groupby("result_source_path"):
        rows = tables[path][1].iloc[g["result_source_row_number"].astype(int) - 1]
        bad_win += int((rows["Name of Contesting Candidate"].map(tidy).values != g["winner"].values).sum())
    n_rows = len(cand) + int(res["in_ward_seat_report"].sum())
    record("provenance", "internal", bad_sha + bad_val + bad_orig + bad_win == 0,
           f"{n_rows:,} rows and {len(w):,} winner rows reopened at source_path and row: {bad_sha} hash, {bad_val} value, "
           f"{bad_orig} original-row and {bad_win} winner mismatches.")

    # ---- keys, names, values
    key_ok = (not cand.duplicated(["source_path", "source_row_number"]).any() and not res["seat_event_id"].duplicated().any()
              and res["source_path"].notna().all() and set(res["contest_id"].dropna()) <= set(cand["contest_id"]))
    record("keys", "internal", key_ok, "candidate rows unique on source_path + source_row_number; seat_event_id unique; "
           "every seat has a source_path; every contest_id on a seat exists among the candidates.")
    violations = []
    for t in (cand, res):
        violations += naming_violations(t.columns, [c for c in t.columns if str(t[c].dtype) == "boolean"])
    record("column_names", "internal", not violations, "central docs/naming.md rules: "
           + (f"{len(violations)} violations: {'; '.join(violations)}" if violations else "0 violations in both tables."))
    allowed = {"reserved_caste": {"SC", "ST", "BC", "NONE"}, "winner_basis": {"published", "sole_candidate"},
               "election_type": {"General Election", "By Election"}, "tier": {"gp_head"}, "script": {"latin"}}
    bad_values = {c: sorted(set(res[c].dropna()) - v) for c, v in allowed.items() if set(res[c].dropna()) - v}
    record("allowed_values", "internal", not bad_values, f"values outside the master's enums: {bad_values or 'none'}.")

    # ---- comparisons with other records
    conflict = res["reserved_source_conflict"].dropna()
    record("reservation_ward_seat_vs_counting", "internal", "info",
           f"Seats where both the Ward-Seat report and the counting file print a reservation code: {len(conflict):,}; "
           f"they differ on {int(conflict.sum()):,}.")
    agrees = res["winner_report_agrees"].dropna()
    record("winner_vs_sec_winner_report", "external", "info",
           f"SEC winner reports (608 and 1165 programmes) name the same winner as rules W1 and W3 for "
           f"{int(agrees.sum()):,} of {len(agrees):,} seats they cover.")
    share = res.groupby("reserved_caste")["reserved_woman"].mean()
    record("women_share_by_category", "external", "info",
           "Share of seats reserved for women within each category: "
           + ", ".join(f"{k} {v:.1%}" for k, v in share.items()) + ".")
    json.dump(checks, open(CHECKS / "checks.json", "w"), indent=1)

    # ---- hand check sample (never overwrite one that has been filled in)
    hand = CHECKS / "hand_check.csv"
    if not hand.exists():
        sample = cand[cand["year"] >= 2018].sample(30, random_state=20261111)
        sample[["source_path", "source_row_number", "original_filename", "original_row_number", "gram_panchayat_raw",
                "candidate_name_raw", "votes", "candidate_rank", "reserved_raw"]].assign(verdict="", checked_by="", checked_on="") \
            .to_csv(hand, index=False)

    summarize(cand, res, acc, extracts, checks)
    failed = [c["check"] for c in checks if c["status"] == "fail"]
    for c in checks:
        print(f"{c['status']:>4}  {c['check']}: {c['result']}")
    return 1 if failed else 0


def summarize(cand, res, acc, extracts, checks):
    def b(x):
        return x.fillna(False).astype(bool)

    def counts(x):
        return {str(k): int(v) for k, v in x.value_counts(dropna=False).items()}

    changes = pd.read_csv(CHECKS / "changes.csv")
    dropped = pd.read_csv(CHECKS / "dropped_rows.csv")
    withheld = pd.read_csv(CHECKS / "withheld_by_programme.csv")
    review = pd.read_csv(CHECKS / "alias_review.csv")
    examined = pd.read_csv(SEARCH_LOG / "files_examined.csv")
    not_used = pd.read_csv(SEARCH_LOG / "sources_not_used.csv")
    fetch = pd.read_csv(FETCH_LOG, dtype=str, keep_default_na=False)
    raw = fetch[fetch["duplicate_of"] == ""]
    raw_kind = raw["path"].str.split("/").str[3]
    s = {
        "files_examined": counts(examined["deposit"]),
        "raw_unchanged": {k: {"files": int(len(g)), "mb": round(g["bytes"].astype(int).sum() / 1e6, 1)}
                          for k, g in raw.groupby(raw_kind)},
        "extracts": {k: {"files": int(len(g)), "rows_kept": int(g["rows_kept"].astype(int).sum()),
                         "rows_withheld": int(g["rows_withheld"].astype(int).sum())} for k, g in extracts.groupby("kind")},
        "not_used": not_used.to_dict("records"),
        "withheld_in_sarpanch_programmes": {
            "rows": int(withheld["rows"].sum()), "programmes": int(withheld["programme"].nunique()),
            "first_phase_2017_rows": int(withheld.loc[withheld["programme"].str.contains("First Phase", case=False), "rows"].sum())},
        "candidates": {"rows": len(cand), "contests": int(cand["contest_id"].nunique()),
                       "rows_2017": int((cand["year"] == 2017).sum()), "nota_rows": int(b(cand["nota_tally"]).sum()),
                       "people_2018_on": int(((cand["year"] >= 2018) & ~b(cand["nota_tally"])).sum()),
                       "people_2018_on_blank_gender": int(((cand["year"] >= 2018) & ~b(cand["nota_tally"])
                                                           & cand["candidate_woman_raw"].isna()).sum()),
                       "gender_raw": counts(cand["candidate_woman_raw"])},
        "results": {"rows": len(res), "in_ward_seat": int(res["in_ward_seat_report"].sum()),
                    "counting_only": int((~res["in_ward_seat_report"]).sum()),
                    "result_in_source": counts(res["result_in_source"]), "winner_named": int(res["winner"].notna().sum()),
                    "winner_basis": counts(res["winner_basis"]), "programmes": int(res["election_programme"].nunique()),
                    "by_election_seats": int((res["election_type"] == "By Election").sum()),
                    "districts": int(res["district"].nunique()), "no_date": int(res["programme_date"].isna().sum()),
                    "no_year": int(res["year"].isna().sum()),
                    "undated_key_collisions": int(res[res["election_duration"].isna()].duplicated(
                        ["year", "district", "block", "gram_panchayat"], keep=False).sum()),
                    "flags": {k: int(b(res[k]).sum()) for k in ["shared_place_name", "runner_up_tie", "unopposed_from_candidates",
                                                                 "no_votes_recorded", "nota_ranked_first", "winner_tie",
                                                                 "candidate_row_repeated"]},
                    "by_year": {str(y): {"seats": int(len(g)), "with_counting": int((g["result_in_source"] == True).sum()),  # noqa: E712
                                         "no_counting": int((g["result_in_source"] == False).sum()),  # noqa: E712
                                         "unattachable": int(g["result_in_source"].isna().sum()),
                                         "winner_named": int(g["winner"].notna().sum())}
                                for y, g in res.groupby(res["year"].astype("string").fillna("none"))}},
        "winner_rules": {r.replace("R3-", ""): int(n) for r, n in
                         changes[changes["rule_id"].str.startswith("R3-")].groupby("rule_id")["rows_affected"].sum().items()},
        "dropped_by_reason": counts(dropped["reason"]), "alias_review_pairs": len(review),
        "changes_rules": len(changes), "accounting": {"files": len(acc), "balanced": int(acc["balanced"].sum())},
        "checks": {c["check"]: c["status"] for c in checks},
        "release_mb": {p.name: round(p.stat().st_size / 1e6, 1) for p in sorted(RELEASE.glob("*.parquet"))},
        "columns": {"results": res.shape[1], "candidates": cand.shape[1]},
    }
    json.dump(s, open(CHECKS / "summary.json", "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
