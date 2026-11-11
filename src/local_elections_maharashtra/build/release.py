"""Build the release tables from the committed sources (offline; no network, no originals).

Reads the raw files listed in data/raw/fetch_log.csv and the extracts listed in
data/extracted/sarpanch_extracts.csv (each checked against its recorded sha256), keeps one copy
of every contest, reads each cell into the pooled schema, decides winners by the published
rules W1 to W6, and writes

    data/release/sarpanch_candidates.parquet   one row per counting row
    data/release/sarpanch_results.parquet      one row per sarpanch seat event

with the ledgers in data/checks/: changes.csv (every rule with its count), dropped_rows.csv,
download_conflicts.csv, alias_review.csv and the recode vocabularies.
"""

import difflib
import hashlib
import io
from collections import Counter
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.paths import CHECKS, EXTRACTS, FETCH_LOG, RELEASE, ROOT
from local_elections_maharashtra.readers import (
    CANDIDATE_CASTE,
    CANDIDATE_WOMAN,
    LABEL,
    RESERVATION,
    aliases,
    gp_key,
    kind_of,
    nk,
    read_table,
    sarpanch_mask,
    tidy,
)

APPROVED = "depositor (plan approved 2026-11-11)"
FOLD_REASON = ("central canon.py folds Maharashtra (scheme sc_st_obc) this way; the (W) suffix is read "
               "as a seat reserved for a woman")

CANDIDATE_COLUMNS = [
    "state", "year", "programme_date", "election_programme", "election_programme_raw", "election_type",
    "election_duration", "division", "division_raw", "district", "district_raw", "block", "block_raw",
    "gram_panchayat", "gram_panchayat_raw", "tier", "tier_local", "ward_no_raw", "contest_id",
    "reserved_raw", "reserved_caste_local", "reserved_caste", "reserved_woman", "reserved_label",
    "candidate_name", "candidate_name_raw", "candidate_name_placeholder", "nota_tally",
    "candidate_row_repeated", "candidate_woman_raw", "candidate_woman", "candidate_caste_raw",
    "candidate_caste", "votes", "candidate_rank", "elected", "no_votes_recorded", "symbol_raw", "script",
    "source_path", "source_row_number", "source_sha256", "original_filename", "original_sha256",
    "original_row_number",
]
RESULT_COLUMNS = [
    "state", "year", "programme_date", "election_programme", "election_programme_raw", "election_type",
    "election_duration", "district", "district_raw", "block", "block_raw", "gram_panchayat",
    "gram_panchayat_raw", "tier", "tier_local", "ward_no_raw", "seat_event_id", "contest_id",
    "reserved_raw", "reserved_caste_local", "reserved_caste", "reserved_woman", "reserved_label",
    "reserved_caste_scheme", "reserved_raw_counting", "reserved_source_conflict", "electors_man",
    "electors_woman", "electors_other", "in_ward_seat_report", "result_in_source", "shared_place_name",
    "seat_candidates", "source_rows_in_contest", "winner", "winner_basis", "winner_woman_from_candidates",
    "votes", "runner_up", "runner_up_votes", "runner_up_tie", "margin", "nota_votes",
    "unopposed_from_candidates", "no_votes_recorded", "nota_ranked_first", "winner_tie",
    "candidate_row_repeated", "winner_report_agrees", "script", "source_path", "source_row_number",
    "source_sha256", "original_filename", "original_sha256", "original_row_number",
    "result_source_path", "result_source_row_number",
]
INTEGERS = ["seat_candidates", "source_rows_in_contest", "nota_votes", "votes", "runner_up_votes", "margin",
            "source_row_number", "original_row_number", "result_source_row_number", "year", "electors_man",
            "electors_woman", "electors_other", "candidate_rank"]
INT8 = ["reserved_woman", "candidate_woman", "winner_woman_from_candidates"]
BOOLEANS = ["in_ward_seat_report", "result_in_source", "shared_place_name", "runner_up_tie",
            "unopposed_from_candidates", "no_votes_recorded", "nota_ranked_first", "winner_tie",
            "candidate_row_repeated", "winner_report_agrees", "reserved_source_conflict",
            "candidate_name_placeholder", "nota_tally", "elected"]
WINNER_RULES = {
    "W1": "votes recorded; the rank-1 row is a candidate: winner as published",
    "W2": "votes recorded; NOTA has the most votes: winner null",
    "W3": "no votes on any row; one distinct candidate: that candidate (sole_candidate)",
    "W4": "no votes on any row; two or more distinct candidates: null unless an SEC winner report names one",
    "W5": "2017: names not in the source: winner null",
    "W6": "two or more candidates printed at rank 1: null unless an SEC winner report names one",
}


class Ledger:
    def __init__(self):
        self.changes, self.dropped = [], []

    def log(self, rule, table, column, raw, released, n, reason, decided_by=APPROVED):
        self.changes.append(dict(rule_id=rule, table=table, column=column, raw_value=raw, released_value=released,
                                 rows_affected=int(n), reason=reason, evidence="data/checks/" + table + " rows",
                                 decided_by=decided_by, decided_on="2026-11-11"))

    def drop(self, rows, reason, kept_as=""):
        for sp, sr, of, orow in zip(rows["source_path"], rows["source_row_number"], rows["original_filename"],
                                    rows["original_row_number"], strict=True):
            self.dropped.append((sp, int(sr), of, int(orow), reason, kept_as))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sources():
    """Sarpanch rows of every committed source, with provenance columns attached."""
    parts = {"counting": [], "ward_seat": [], "winner_report": []}
    fetch = pd.read_csv(FETCH_LOG, dtype=str, keep_default_na=False)
    for row in fetch[fetch["duplicate_of"] == ""].itertuples():
        data = (ROOT / row.path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == row.sha256, f"{row.path}: sha256 differs from fetch_log.csv"
        table, fmt, _ = read_table(data)
        keep, _, _ = sarpanch_mask(table)
        assert keep.all(), f"{row.path}: a raw file must hold only sarpanch rows"
        table["original_row_number"] = table.index + 1
        table["source_row_number"] = table["original_row_number"]
        table = table.assign(source_path=row.path, source_sha256=digest, original_filename=Path(row.path).name,
                             original_sha256=digest, _prio=int(row.priority), _format=fmt)
        parts[kind_of(table.columns)].append(table)
    extracts = pd.read_csv(EXTRACTS, dtype=str, keep_default_na=False)
    for row in extracts.itertuples():
        data = (ROOT / row.path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == row.sha256, f"{row.path}: sha256 differs from sarpanch_extracts.csv"
        table = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
        assert len(table) == int(row.rows_kept), f"{row.path}: row count differs from sarpanch_extracts.csv"
        table["original_row_number"] = table["original_row_number"].astype(int)
        table["source_row_number"] = range(1, len(table) + 1)
        table = table.assign(source_path=row.path, source_sha256=digest, original_filename=row.original_filename,
                             original_sha256=row.original_sha256, _prio=int(row.priority), _format=row.original_format)
        parts[row.kind].append(table)
    return (pd.concat(parts[k], ignore_index=True) for k in ("counting", "ward_seat", "winner_report")), extracts


def build():
    ledger = Ledger()
    (counting, frame, reports), extracts = load_sources()
    district_alias, taluka_alias = aliases()
    for kind in ("counting", "ward_seat"):
        ledger.log("R4", f"source rows ({kind})", "row selection", "rows other than Ward No 999 in a sarpanch programme",
                   "withheld (not deposited)", extracts.loc[extracts["kind"] == kind, "rows_withheld"].astype(int).sum(),
                   "sarpanch-only deposit; counts by file in sarpanch_extracts.csv, by programme in withheld_by_programme.csv",
                   decided_by="depositor, 2026-11-09")

    def seat_key(t):
        programme = t["Election Program Name"].map(nk).str.replace("copy", "", regex=False)
        return (programme + "|" + t["District"].map(nk).replace(district_alias) + "|"
                + t["Taluka"].map(nk).replace(taluka_alias) + "|" + t["LocalBody Name"].map(gp_key))

    def raw_key(t):
        return (t["Election Program Name"].map(nk).str.replace("copy", "", regex=False) + "|" + t["District"].map(nk)
                + "|" + t["Taluka"].map(nk) + "|" + t["LocalBody Name"].map(nk))

    counting["_res_cell"] = counting["Ward Reservation"].fillna("")
    def without_blank_places(t):
        blank = t[["District", "Taluka", "LocalBody Name"]].apply(lambda c: c.str.strip() == "").all(axis=1)
        ledger.drop(t[blank], "no district, taluka or GP name in the source row")
        return t[~blank].copy()

    counting, frame = without_blank_places(counting), without_blank_places(frame)
    for t in (counting, frame, reports):
        t["_seat"], t["_rawseat"] = seat_key(t), raw_key(t)

    # one copy of each contest: the download with the most rows, then the lower priority
    def pick(t, sig_cols):
        t = t.copy()
        t["_sig"] = t[sig_cols].apply(lambda r: "|".join(nk(x) for x in r), axis=1)
        n = t.groupby(["_seat", "source_path"]).agg(_n=("_sig", "size"), _prio=("_prio", "min")).reset_index()
        n = n.sort_values(["_seat", "_n", "_prio", "source_path"], ascending=[True, False, True, True])
        best = n.drop_duplicates("_seat").set_index("_seat")["source_path"]
        keep = t["source_path"] == t["_seat"].map(best)
        canon = t[keep].groupby("_seat")["_sig"].agg(Counter)
        conflicts = []
        for (seat, path), g in t[~keep].groupby(["_seat", "source_path"]):
            mine, theirs = Counter(g["_sig"]), canon[seat]
            if mine == theirs:
                reason = "same contest in another download (identical rows)"
            elif all(theirs[k] >= v for k, v in mine.items()):
                reason = "same contest in a fuller download (these rows are a subset)"
            else:
                reason = "same contest in another download with different rows"
                conflicts.append(dict(seat_key_internal=seat, kept_path=best[seat], dropped_path=path,
                                      kept_rows=sum(theirs.values()), dropped_rows=len(g)))
            ledger.drop(g, reason, best[seat])
        return t[keep].copy(), conflicts

    counting, conflicts_c = pick(counting, ["Name of Contesting Candidate", "Total Votes Secured", "Rank"])
    frame, conflicts_w = pick(frame, ["Reservation"])
    for reason, n in Counter(d[4] for d in ledger.dropped).items():
        ledger.log("R5", "source rows", "row selection", reason, "dropped; listed in dropped_rows.csv", n,
                   "one copy of each contest is released; the kept copy is named in kept_as")

    def text_columns(t, table, pairs):
        out = pd.DataFrame(index=t.index)
        for col, src in pairs:
            out[col + "_raw"] = t[src]
            out[col] = t[src].map(tidy)
            ledger.log("R6", table, col, "edge, repeated or embedded whitespace (tabs, newlines)",
                       f"single spaces, trimmed; printed value in {col}_raw", (out[col] != out[col + "_raw"]).sum(),
                       "whitespace only; letters are never changed")
        return out

    programme_spelling = {}
    for raw in frame["Election Program Name"]:
        programme_spelling.setdefault(nk(raw).replace("copy", ""), tidy(raw))

    def programme_fields(t, table):
        raw = t["Election Program Name"]
        canon = raw.map(lambda s: nk(s).replace("copy", "")).map(programme_spelling).fillna(raw.map(tidy))
        ledger.log("R6", table, "election_programme", "programme printed with a different spelling or spacing in another file",
                   "the Ward-Seat report's spelling; this row's own in election_programme_raw",
                   (canon != raw.map(tidy)).sum(), "one name per programme so seat and candidate rows agree")
        dates = canon.str.findall(r"(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(20\d{2})")
        dt = dates.map(lambda m: pd.Timestamp(int(m[-1][2]), int(m[-1][1]), int(m[-1][0])) if m else pd.NaT)
        year = canon.str.extract(r"(20\d{2})(?!.*20\d{2})")[0].astype("Int64")
        out = pd.DataFrame({
            "election_programme": canon, "election_programme_raw": raw,
            "election_type": canon.str.contains("bye", case=False).map({True: "By Election", False: "General Election"}),
            "election_duration": canon.str.extract(r"(\d{1,2}\s*-\s*\d{1,2}\s*-\s*20\d{2})")[0],
            "programme_date": dt.dt.date, "year": dt.dt.year.astype("Int64").fillna(year)}, index=t.index)
        ledger.log("R9", table, "programme_date, year, election_type, election_duration", "programme name",
                   "read from the programme name", len(t),
                   "the source has no separate date or type column; election_type is By Election where the name contains 'bye'")
        ledger.log("R9", table, "programme_date", "programme name without a dd-mm-yyyy date", "null",
                   out["programme_date"].isna().sum(), "no full date in the programme name")
        ledger.log("R9", table, "year", "programme name without a year", "null", out["year"].isna().sum(),
                   "no year in the programme name")
        return out

    vocab = []

    def reservation(cell, table):
        printed = cell.map(tidy)
        caste = printed.map(lambda v: RESERVATION.get(v, (None, None))[0])
        woman = printed.map(lambda v: RESERVATION.get(v, (None, None))[1]).astype("Int8")
        for value, n in printed.value_counts().items():
            c, w = RESERVATION.get(value, (None, None))
            ledger.log("R8", table, "reserved_caste, reserved_woman", value or "(blank)", f"{c}, {w}" if c else "null, null", n,
                       FOLD_REASON if c else "blank or not a reservation code: unknown, never unreserved")
            vocab.append(dict(table=table, reserved_raw=value, reserved_caste=c, reserved_woman=w, rows=int(n)))
        ledger.log("R8", table, "reserved_caste_local", "reserved_raw", "reserved_raw without the (W) suffix",
                   caste.notna().sum(), "caste part only, as naming.md defines _local")
        return pd.DataFrame({
            "reserved_raw": cell.where(printed != "", None),
            "reserved_caste_local": printed.str.replace("(W)", "", regex=False).where(caste.notna(), None),
            "reserved_caste": caste, "reserved_woman": woman,
            "reserved_label": [LABEL.get((c, w)) if c is not None else None for c, w in zip(caste, woman, strict=True)],
        }, index=cell.index)

    # ---------------------------------------------------------------- candidates
    table = "sarpanch_candidates"
    c_src = counting
    prog = programme_fields(c_src, table)
    y2017 = prog["year"] == 2017
    name = c_src["Name of Contesting Candidate"].map(tidy)
    is_nota = name.str.upper() == "NOTA"
    cand = pd.DataFrame({"state": "Maharashtra"}, index=c_src.index).join(prog)
    cand = cand.join(text_columns(c_src, table, [("division", "Division"), ("district", "District"),
                                                  ("block", "Taluka"), ("gram_panchayat", "LocalBody Name")]))
    cand["tier"], cand["tier_local"], cand["ward_no_raw"] = "gp_head", "sarpanch", c_src["Ward No."]
    cand = cand.join(reservation(c_src["_res_cell"], table))
    cand["candidate_name_raw"] = c_src["Name of Contesting Candidate"]
    cand["candidate_name"] = name.where(~is_nota, None)
    ledger.log("R6", table, "candidate_name", "edge or repeated whitespace", "trimmed; printed value in candidate_name_raw",
               ((name != c_src["Name of Contesting Candidate"]) & ~is_nota).sum(), "whitespace only")
    cand["candidate_name_placeholder"] = y2017 & is_nota
    cand["nota_tally"] = pd.Series(pd.NA, index=c_src.index, dtype="boolean")
    cand.loc[~y2017, "nota_tally"] = is_nota[~y2017]
    ledger.log("R1", table, "candidate_name", "NOTA (every 2017 row)", "null; candidate_name_placeholder = true",
               (y2017 & is_nota).sum(), "every 2017 row prints NOTA in the candidate-name column; names are not in the source",
               decided_by="depositor, 2026-11-09")
    ledger.log("R1", table, "nota_tally", "(2017)", "null", y2017.sum(),
               "the 2017 file does not mark which row, if any, is the NOTA count", decided_by="depositor, 2026-11-09")
    ledger.log("R2", table, "candidate_name, nota_tally", "NOTA (2018 on)", "candidate_name null; nota_tally = true",
               (~y2017 & is_nota).sum(), "the None-of-the-above count, not a person")
    gender = c_src["Candidate Gender"].map(tidy)
    cand["candidate_woman_raw"] = c_src["Candidate Gender"].where(gender != "", None)
    cand["candidate_woman"] = gender.map(CANDIDATE_WOMAN).astype("Int8")
    woman_vocab = gender.value_counts().rename_axis("candidate_woman_raw").reset_index(name="rows")
    woman_vocab["candidate_woman"] = woman_vocab["candidate_woman_raw"].map(CANDIDATE_WOMAN)
    for value, n in gender.value_counts().items():
        if value:
            ledger.log("R8", table, "candidate_woman", value, str(CANDIDATE_WOMAN.get(value, "null")), n,
                       "Int8: 1 woman, 0 man; any other value null")
    ledger.log("R11", table, "candidate_woman, candidate_caste", "(blank) on 2017 rows", "null", (y2017 & (gender == "")).sum(),
               "not printed; never inferred from names")
    ledger.log("R11", table, "candidate_woman, candidate_caste", "(blank) on NOTA rows", "null",
               (~y2017 & is_nota & (gender == "")).sum(), "the NOTA row has no person")
    caste = c_src["Candidate Cast"].map(tidy)
    cand["candidate_caste_raw"] = c_src["Candidate Cast"].where(caste != "", None)
    cand["candidate_caste"] = caste.map(CANDIDATE_CASTE)
    caste_vocab = caste.value_counts().rename_axis("candidate_caste_raw").reset_index(name="rows")
    caste_vocab["candidate_caste"] = caste_vocab["candidate_caste_raw"].map(CANDIDATE_CASTE)
    for value, n in caste.value_counts().items():
        if value:
            ledger.log("R8", table, "candidate_caste", value, str(CANDIDATE_CASTE.get(value, "null")), n,
                       "the candidate's own category, not the seat's; " + FOLD_REASON.split(";")[0])
    cand["votes"] = pd.to_numeric(c_src["Total Votes Secured"].str.strip(), errors="coerce").astype("Int64")
    cand["candidate_rank"] = pd.to_numeric(c_src["Rank"].str.strip(), errors="coerce").astype("Int64")
    assert cand["votes"].notna().all() and cand["candidate_rank"].notna().all(), "votes or rank not a whole number"
    ledger.log("R7", table, "votes, candidate_rank", "text", "integer", len(cand), "lossless: every cell is a whole number (checked)")
    spreadsheet_rows = sum(int(t["_format"].isin(["xlsx", "xls_biff"]).sum()) for t in (c_src, frame, reports))
    ledger.log("R7", "all tables", "every cell of .xls/.xlsx sources", "spreadsheet number", "whole numbers written without .0",
               spreadsheet_rows, "read as the spreadsheet displays it")
    cand["symbol_raw"] = c_src["SymbolName"].where(c_src["SymbolName"].str.strip() != "", None)
    cand["script"] = "latin"
    provenance = ["source_path", "source_row_number", "source_sha256", "original_filename", "original_sha256", "original_row_number"]
    for col in provenance:
        cand[col] = c_src[col]
    cand["_seat"], cand["_rawseat"] = c_src["_seat"], c_src["_rawseat"]
    first = cand.sort_values(["source_path", "source_row_number"]).drop_duplicates("_seat").set_index("_seat")
    cand["contest_id"] = cand["_seat"].map(
        lambda s: hashlib.sha1(f"{first.at[s, 'source_path']}#{first.at[s, 'source_row_number']}".encode()).hexdigest()[:12])
    name_key = cand["candidate_name"].map(lambda v: nk(v) if isinstance(v, str) else None)
    cand["candidate_row_repeated"] = ~y2017 & ~is_nota & cand.assign(_p=name_key).duplicated(
        ["_seat", "_p", "votes", "candidate_rank"], keep=False)
    ledger.log("R3", table, "candidate_row_repeated", "same name, votes and rank printed twice in one contest",
               "flag true on each copy", cand["candidate_row_repeated"].sum(), "kept as printed; counted once in seat_candidates")

    # ---------------------------------------------------------------- winners per contest
    reports["_name"] = reports["Name of Contesting Candidate"].map(tidy)
    report_rows = reports.groupby("_seat")
    cand["elected"] = pd.Series(pd.NA, index=cand.index, dtype="boolean")
    cand["no_votes_recorded"] = False
    contests = {}
    for seat, g in cand.groupby("_seat", sort=False):
        is2017 = bool((g["year"] == 2017).all())
        nota = g["nota_tally"].fillna(False).astype(bool)
        people = g if is2017 else g[~nota]
        distinct = people["candidate_name"].dropna().map(nk).nunique()
        total = int(g["votes"].sum())
        report = report_rows.get_group(seat) if seat in report_rows.groups else None
        r = dict(seat_candidates=pd.NA if is2017 else distinct, source_rows_in_contest=len(g),
                 nota_votes=pd.NA if is2017 or not nota.any() else int(g.loc[nota, "votes"].sum()),
                 no_votes_recorded=total == 0, nota_ranked_first=False, winner_tie=False,
                 candidate_row_repeated=bool(g["candidate_row_repeated"].any()),
                 winner_row=None, winner_basis=None, rule=None, report_row=None, winner_report_agrees=pd.NA)

        def from_report(pool, report=report):
            if report is None:
                return None
            hit = report[report["_name"].map(nk).isin(pool["candidate_name"].dropna().map(nk))]
            names = hit["_name"].map(nk).unique()
            if len(names) == 1:
                match = pool["candidate_name"].map(lambda v: nk(v) if isinstance(v, str) else "") == names[0]
                return pool.index[match][0], hit.iloc[0]
            return None

        if is2017:
            r["rule"] = "W5"
        elif total > 0:
            rank1 = g[g["candidate_rank"] == 1]
            rank1_people = rank1[~rank1["nota_tally"].fillna(False).astype(bool)]
            if len(rank1) >= 1 and len(rank1_people) == 0:
                r.update(rule="W2", nota_ranked_first=True)
            elif rank1_people["candidate_name"].map(nk).nunique() == 1:
                r.update(rule="W1", winner_row=rank1_people.index[0], winner_basis="published")
            else:
                r["winner_tie"] = bool(rank1_people["votes"].nunique() == 1)
                hit = from_report(rank1_people)
                r.update(rule="W6", **(dict(winner_row=hit[0], winner_basis="published", report_row=hit[1]) if hit else {}))
        elif distinct == 1:
            r.update(rule="W3", winner_row=people.index[0], winner_basis="sole_candidate")
        else:
            hit = from_report(people) if distinct >= 2 else None
            r.update(rule="W4", **(dict(winner_row=hit[0], winner_basis="published", report_row=hit[1]) if hit else {}))
        if r["winner_row"] is not None:
            cand.loc[g.index, "elected"] = False
            cand.loc[g.index[nota.values], "elected"] = pd.NA
            cand.loc[r["winner_row"], "elected"] = True
            if r["report_row"] is None and report is not None:
                r["winner_report_agrees"] = nk(cand.at[r["winner_row"], "candidate_name"]) in set(report["_name"].map(nk))
        if total == 0:
            cand.loc[g.index, "no_votes_recorded"] = True
        contests[seat] = r
    contests = pd.DataFrame.from_dict(contests, orient="index")
    for rule, n in contests["rule"].value_counts().sort_index().items():
        ledger.log("R3-" + rule, "sarpanch_results", "winner", "(contest)", WINNER_RULES[rule], n, "winner rule " + rule)
    ledger.log("R3", "sarpanch_results", "winner, winner_basis, result_source_path", "(contest)",
               "taken from the SEC winner report (608 and 1165 programmes)", contests["report_row"].notna().sum(),
               "the counting rows alone do not decide the winner (W4, W6)")

    # ---------------------------------------------------------------- results: Ward-Seat frame + contests
    table = "sarpanch_results"
    res = pd.DataFrame({"state": "Maharashtra"}, index=frame.index).join(programme_fields(frame, table))
    res = res.join(text_columns(frame, table, [("district", "District"), ("block", "Taluka"), ("gram_panchayat", "LocalBody Name")]))
    res["tier"], res["tier_local"], res["ward_no_raw"] = "gp_head", "sarpanch", frame["Ward No"]
    res = res.join(reservation(frame["Reservation"], table))
    for col, src in [("electors_man", "Male Voters"), ("electors_woman", "Female Voters"), ("electors_other", "Other Voters")]:
        res[col] = pd.to_numeric(frame[src].str.strip(), errors="coerce").astype("Int64")
    res["in_ward_seat_report"] = True
    for col in provenance:
        res[col] = frame[col]
    res["_seat"], res["_rawseat"] = frame["_seat"], frame["_rawseat"]
    res["shared_place_name"] = res["_seat"].duplicated(keep=False)
    first_c = cand.sort_values(["source_path", "source_row_number"]).drop_duplicates("_seat").set_index("_seat")
    extra = first_c.loc[~first_c.index.isin(res["_seat"])].reset_index()
    extra = extra[["state", "election_programme", "election_programme_raw", "election_type", "election_duration",
                   "programme_date", "year", "district", "district_raw", "block", "block_raw", "gram_panchayat",
                   "gram_panchayat_raw", "tier", "tier_local", "ward_no_raw", "reserved_raw", "reserved_caste_local",
                   "reserved_caste", "reserved_woman", "reserved_label", *provenance, "_seat", "_rawseat"]].copy()
    extra["in_ward_seat_report"], extra["shared_place_name"] = False, False
    res = pd.concat([res, extra], ignore_index=True)
    res["reserved_caste_scheme"] = "sc_st_obc"
    res["seat_event_id"] = [hashlib.sha1(f"{p}#{n}".encode()).hexdigest()[:12]
                            for p, n in zip(res["source_path"], res["source_row_number"], strict=True)]
    has = res["_seat"].isin(contests.index) & ~res["shared_place_name"]
    res["result_in_source"] = has.astype("boolean")
    res.loc[res["shared_place_name"], "result_in_source"] = pd.NA
    res["contest_id"] = res["_seat"].map(cand.drop_duplicates("_seat").set_index("_seat")["contest_id"]).where(has)
    for col in ["seat_candidates", "source_rows_in_contest", "nota_votes", "no_votes_recorded", "nota_ranked_first",
                "winner_tie", "candidate_row_repeated", "winner_basis", "winner_report_agrees"]:
        res[col] = res["_seat"].map(contests[col]).where(has)
    ledger.log("R10", table, "(join)", "district, taluka or GP printed differently in the Ward-Seat and counting files",
               "joined through data/manual/aliases.csv; printed names unchanged",
               (has & ~res["_rawseat"].isin(set(cand["_rawseat"]))).sum(),
               "district and taluka renames; GP prefixes and suffixes (GP, Gram Pan, Grampanchayat, Khurd/Kh)")
    winner_row = res["_seat"].map(contests["winner_row"]).where(has)
    ok = winner_row.notna()
    w = cand.loc[winner_row[ok].astype(int)]
    res.loc[ok, "winner"] = w["candidate_name"].values
    res.loc[ok, "winner_woman_from_candidates"] = w["candidate_woman"].values
    res.loc[ok, "votes"] = w["votes"].values
    res.loc[ok, "result_source_path"] = w["source_path"].values
    res.loc[ok, "result_source_row_number"] = w["source_row_number"].values
    report_row = res["_seat"].map(contests["report_row"]).where(has)
    for i in res.index[report_row.notna()]:
        res.at[i, "result_source_path"] = report_row[i]["source_path"]
        res.at[i, "result_source_row_number"] = report_row[i]["source_row_number"]
    ledger.log("R3", table, "winner_woman_from_candidates", "the winner's Candidate Gender cell in the counting file",
               "copied to the seat row", ok.sum(), "naming.md: a value read from another record carries _from_<evidence>")
    published = res["_seat"].map(contests["rule"]).isin(["W1", "W4", "W6"]) & ok & res["winner_basis"].eq("published")
    others = cand[(cand["nota_tally"] == False) & (cand["elected"] == False)]  # noqa: E712
    ordered = others.sort_values(["_seat", "votes"], ascending=[True, False])
    best_two = ordered.groupby("_seat").head(2).groupby("_seat")["votes"].agg(list)
    runner = ordered.drop_duplicates("_seat").set_index("_seat")
    tie = best_two.map(lambda v: len(v) == 2 and v[0] == v[1])
    res.loc[published, "runner_up_votes"] = res.loc[published, "_seat"].map(runner["votes"])
    res.loc[published, "runner_up_tie"] = res.loc[published, "_seat"].map(tie).fillna(False)
    res.loc[published, "runner_up"] = res.loc[published, "_seat"].map(runner["candidate_name"]).where(
        ~res.loc[published, "runner_up_tie"].astype(bool))
    res["margin"] = (pd.to_numeric(res["votes"]) - pd.to_numeric(res["runner_up_votes"])).where(published)
    ledger.log("R3", table, "runner_up", "two or more candidates tie for second place",
               "null; runner_up_tie = true; runner_up_votes kept", res["runner_up_tie"].fillna(False).astype(bool).sum(),
               "no order among tied candidates is printed")
    res["unopposed_from_candidates"] = ((res["seat_candidates"] == 1) & (res["no_votes_recorded"] == True)).where(has)  # noqa: E712
    ledger.log("R3", table, "unopposed_from_candidates", "one distinct candidate and no votes on any row", "true",
               res["unopposed_from_candidates"].fillna(False).astype(bool).sum(),
               "read from the counting rows; the source prints no unopposed marker")
    counting_reservation = res["_seat"].map(first_c["reserved_raw"].map(lambda v: tidy(v) if isinstance(v, str) else ""))
    res["reserved_raw_counting"] = counting_reservation.where(res["in_ward_seat_report"] & counting_reservation.fillna("").ne(""))
    both = res["in_ward_seat_report"] & counting_reservation.isin(list(RESERVATION)) & has
    res["reserved_source_conflict"] = (counting_reservation.map(nk) != res["reserved_raw"].fillna("").map(nk)).where(both)
    res["script"] = "latin"

    # counting-only seats that may be a Ward-Seat seat spelled differently: listed for hand review
    review = []
    counting_only, in_frame = res[~res["in_ward_seat_report"]], res[res["in_ward_seat_report"]]
    for _, a in counting_only.iterrows():
        pk, dk, tk, gk = a["_seat"].split("|")
        best = None
        for _, b in in_frame[in_frame["_seat"].str.startswith(pk + "|" + dk + "|")].iterrows():
            score = difflib.SequenceMatcher(None, gk, b["_seat"].split("|")[3]).ratio() + (0.05 if b["_seat"].split("|")[2] == tk else 0)
            if best is None or score > best[0]:
                best = (score, b)
        if best and best[0] >= 0.85:
            b = best[1]
            review.append(dict(programme=a["election_programme"], district=a["district"], counting_block=a["block"],
                               counting_gp=a["gram_panchayat"], ward_seat_block=b["block"], ward_seat_gp=b["gram_panchayat"],
                               score=round(best[0], 2), counting_reserved=a["reserved_raw"],
                               ward_seat_reserved=b["reserved_raw"],
                               twin_already_has_counting=bool(b["result_in_source"] == True),  # noqa: E712
                               decision="", reviewer=""))

    # ---------------------------------------------------------------- write
    for t, cols in ((cand, CANDIDATE_COLUMNS), (res, RESULT_COLUMNS)):
        for col in cols:
            if col in INTEGERS:
                t[col] = pd.to_numeric(t[col], errors="coerce").astype("Int64")
            elif col in BOOLEANS:
                t[col] = t[col].astype("boolean")
            elif col in INT8:
                t[col] = pd.to_numeric(t[col], errors="coerce").astype("Int8")
    cand_out = cand[CANDIDATE_COLUMNS].sort_values(
        ["year", "election_programme", "district", "block", "gram_panchayat", "candidate_rank", "source_path", "source_row_number"])
    res_out = res[RESULT_COLUMNS].sort_values(
        ["year", "election_programme", "district", "block", "gram_panchayat", "source_path", "source_row_number"])
    RELEASE.mkdir(parents=True, exist_ok=True)
    CHECKS.mkdir(parents=True, exist_ok=True)
    cand_out.to_parquet(RELEASE / "sarpanch_candidates.parquet", index=False)
    res_out.to_parquet(RELEASE / "sarpanch_results.parquet", index=False)
    pd.DataFrame(ledger.dropped, columns=["source_path", "source_row_number", "original_filename", "original_row_number",
                                          "reason", "kept_as"]).to_csv(CHECKS / "dropped_rows.csv", index=False)
    pd.DataFrame(ledger.changes).to_csv(CHECKS / "changes.csv", index=False)
    pd.DataFrame(conflicts_c + conflicts_w, columns=["seat_key_internal", "kept_path", "dropped_path", "kept_rows",
                                                     "dropped_rows"]).to_csv(CHECKS / "download_conflicts.csv", index=False)
    pd.DataFrame(review, columns=["programme", "district", "counting_block", "counting_gp", "ward_seat_block", "ward_seat_gp",
                                  "score", "counting_reserved", "ward_seat_reserved", "twin_already_has_counting",
                                  "decision", "reviewer"]).to_csv(CHECKS / "alias_review.csv", index=False)
    pd.DataFrame(vocab).groupby(["table", "reserved_raw", "reserved_caste", "reserved_woman"], dropna=False)["rows"].sum() \
        .reset_index().to_csv(CHECKS / "reserved_vocabulary.csv", index=False)
    woman_vocab.to_csv(CHECKS / "candidate_woman_vocabulary.csv", index=False)
    caste_vocab.to_csv(CHECKS / "candidate_caste_vocabulary.csv", index=False)
    assert not cand_out.duplicated(["source_path", "source_row_number"]).any()
    assert not res_out.duplicated("seat_event_id").any()
    assert res_out["source_path"].notna().all()
    print(f"candidates {len(cand_out):,} rows in {cand_out['contest_id'].nunique():,} contests; results {len(res_out):,} seats")


if __name__ == "__main__":
    build()
