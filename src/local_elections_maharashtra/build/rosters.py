"""Build data/release/sarpanch_rti_reservations.parquet from the RTI roster documents.

One row per gram panchayat per reservation round for which a value is held. The round is given
as ``roster_year`` (1995, 2000, 2005, 2010, 2015, 2020). No election year is assigned.

Two sources, both read from the RTI replies:

1. The workbook typed by research assistants (data/manual/rti_rosters/workbook_rows.csv; rounds
   2005, 2010, 2015, 2020). Where a document shows the typed value is wrong,
   data/manual/corrections.csv gives the old value, the new value, the reason and the document
   page; the build applies it, keeps the typed value in ``workbook_value_raw`` and sets
   ``transcription_corrected``. It stops if a cell no longer holds the old value a correction names.
   Rows that duplicate another row are withheld (data/manual/rti_rosters/withheld_workbook_rows.csv).
2. Independent readings of the scans (data/manual/rti_rosters/settled_cells.csv, one row per GP
   and round, with every reading and the verdict). They check every workbook cell they cover
   (``document_check``) and add the values the workbook lacks: the 1995 and 2000 rounds, blank
   cells, and GPs missing from the workbook (``transcription = rti_reading_2026``).

A cell whose readings are not settled is released without a value (``document_check =
unsettled``). A round a document lists only in part (``round_scope = partial``) carries values for
the listed GPs only. Where a document states the caste category but not the women's reservation,
``reserved_woman`` is null.

Ledgers: data/checks/roster_vocabulary.csv, roster_changes.csv (every rule with its count),
roster_unsettled.csv, roster_superseded_draws.csv.
"""

import hashlib
import re

import pandas as pd

from local_elections_maharashtra.paths import CHECKS, MANUAL, RELEASE
from local_elections_maharashtra.readers import LABEL, tidy

TABLE = "sarpanch_rti_reservations"
SOURCE = "data/manual/rti_rosters/workbook_rows.csv"
READINGS = "data/manual/rti_rosters/settled_cells.csv"
# workbook column -> the year the RTI documents print for that round (1995 and 2000 are not in the workbook)
TERMS = {"2005-10": 2005, "2010-15": 2010, "2015-20": 2015, "2021-25": 2020}
CASTE = {"GEN": "NONE", "GENERAL": "NONE", "BCC": "BC", "OBC": "BC", "SC": "SC", "ST": "ST"}
LOCAL = {"NONE": "GEN", "BC": "BCC", "SC": "SC", "ST": "ST"}
CHECK = {"two_readings": "two_readings", "reading_agrees_workbook": "reading_agrees_workbook",
         "reading_and_sec": "reading_and_sec"}


def read_typed(value):
    """('BCC (W )' -> ('BC', 1)); anything that is not a category and an optional women's mark -> (None, None)."""
    letters = re.sub(r"[^A-Z]", "", str(value).upper())
    woman = letters.endswith("WOMEN") or (letters.endswith("W") and letters[:-1] in CASTE)
    caste = CASTE.get(re.sub(r"(WOMEN|W)$", "", letters) if woman else letters)
    return (caste, int(woman)) if caste else (None, None)


def check_of(status, basis):
    """Settled-cell verdict -> document_check category."""
    if status == "correction":
        return "corrected"
    if status == "settled":
        if basis.startswith("adjudicated") or "page viewed" in basis:
            return "page_viewed"
        return CHECK.get(basis, basis)
    if status == "unsettled":
        return "unsettled"
    return {"blank_on_document": "document_prints_no_category"}.get(status, status)


def build():
    path = MANUAL / "rti_rosters" / "workbook_rows.csv"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    typed = pd.read_csv(path, dtype=str, keep_default_na=False)
    typed["source_row_number"] = range(1, len(typed) + 1)
    docs = pd.read_csv(MANUAL / "rti_rosters" / "documents.csv", dtype=str)
    held = pd.read_csv(MANUAL / "rti_rosters" / "withheld_workbook_rows.csv", dtype=str)
    held_rows = set(held["source_row_number"].astype(int))
    rpath = MANUAL / "rti_rosters" / "settled_cells.csv"
    rdigest = hashlib.sha256(rpath.read_bytes()).hexdigest()
    cells = pd.read_csv(rpath, dtype=str, keep_default_na=False)
    cells["roster_year"] = cells["roster_year"].astype(int)
    assert not cells.duplicated(["district", "block", "workbook_row", "gram_panchayat_document", "roster_year"]).any()
    paired = cells[cells["workbook_row"] != ""].assign(source_row_number=lambda d: d["workbook_row"].astype(int))
    assert not paired.duplicated(["source_row_number", "roster_year"]).any(), "a workbook cell has two verdicts"
    assert not set(paired["source_row_number"]) & held_rows, "a reading is paired to a withheld workbook row"

    # corrections: the typed cell must still hold old_value
    fixes = pd.read_csv(MANUAL / "corrections.csv", dtype=str, keep_default_na=False)
    fixes = fixes[fixes["table"] == TABLE]
    assert not fixes.duplicated(["source_row_number", "column"]).any(), "two corrections for one cell"
    wide = typed.copy()
    for fix in fixes.itertuples():
        assert fix.source_path == SOURCE and fix.column in TERMS, f"correction names an unknown cell: {fix}"
        row = wide.index[wide["source_row_number"] == int(fix.source_row_number)][0]
        held_value = wide.at[row, fix.column]
        assert held_value == fix.old_value, f"row {fix.source_row_number} {fix.column}: holds {held_value!r}, correction expects {fix.old_value!r}"
        wide.at[row, fix.column] = fix.new_value

    ids = [c for c in wide.columns if c not in TERMS]
    long = wide.melt(id_vars=ids, value_vars=list(TERMS), var_name="workbook_column", value_name="reserved_raw")
    was = typed.melt(id_vars=["source_row_number"], value_vars=list(TERMS), var_name="workbook_column",
                     value_name="workbook_value_raw")
    long = long.merge(was, on=["source_row_number", "workbook_column"], validate="1:1")
    fix_key = fixes.assign(source_row_number=fixes["source_row_number"].astype(int)).rename(columns={"column": "workbook_column"})
    long = long.merge(fix_key[["source_row_number", "workbook_column", "reason", "supporting_source"]],
                      on=["source_row_number", "workbook_column"], how="left", validate="1:1")
    long["roster_year"] = long["workbook_column"].map(TERMS)
    n_held = int((long["source_row_number"].isin(held_rows) & (long["reserved_raw"].str.strip() != "")).sum())
    long = long[~long["source_row_number"].isin(held_rows)]
    verdict = paired[["source_row_number", "roster_year", "status", "basis", "value", "women_unknown", "round_scope"]]
    long = long.merge(verdict, on=["source_row_number", "roster_year"], how="left", validate="1:1")
    # workbook cell blank but the readings hold a settled value: released from the readings (below)
    from_readings = long[(long["reserved_raw"].str.strip() == "") & long["status"].isin(["settled"]) & (long["value"] != "")]
    long = long[long["reserved_raw"].str.strip() != ""].copy()
    read = long["reserved_raw"].map(read_typed)
    corrected = long["reason"].notna()
    long["document_check"] = [check_of(s, b) if isinstance(s, str) else "not_read" for s, b in zip(long["status"], long["basis"], strict=True)]
    long.loc[corrected, "document_check"] = "corrected"
    # an unsettled cell keeps no value unless its one reading equals the typed value
    unsettled = long["document_check"] == "unsettled"
    agrees = unsettled & (long["value"] != "") & (long["value"].fillna("") == long["reserved_raw"].map(
        lambda v: (LOCAL.get(read_typed(v)[0], "") + ("(W)" if read_typed(v)[1] else "")) if read_typed(v)[0] else ""))
    long.loc[agrees, "document_check"] = "one_reading_degraded_page"
    blank = long["document_check"] == "unsettled"
    out = pd.DataFrame({
        "state": "Maharashtra",
        "district": long["Districtname"].map(tidy), "district_raw": long["Districtname"],
        "block": long["SubDistrictname"].map(tidy), "block_raw": long["SubDistrictname"],
        "gram_panchayat": long["LBName"].map(tidy), "gram_panchayat_raw": long["LBName"],
        "gram_panchayat_devanagari": long["LBName_LL"].map(tidy).replace("", None),
        "tier": "gp_head", "tier_local": "sarpanch",
        "roster_year": long["roster_year"].astype("Int64"),
        "workbook_column": long["workbook_column"],
        "roster_year_basis": "workbook_column",
        "round_scope": long["round_scope"].replace({"": "all"}).fillna("all"),
        "reserved_raw": long["reserved_raw"],
        "reserved_caste_local": [None if b else LOCAL.get(r[0]) for r, b in zip(read, blank, strict=True)],
        "reserved_caste": [None if b else r[0] for r, b in zip(read, blank, strict=True)],
        "reserved_woman": pd.array([None if (b or wu == "True") else r[1] for r, b, wu in zip(read, blank, long["women_unknown"], strict=True)], dtype="Int8"),
        "reserved_label": [None if (b or not r[0]) else LABEL.get(r) for r, b in zip(read, blank, strict=True)],
        "reserved_caste_scheme": "sc_st_obc",
        "workbook_value_raw": long["workbook_value_raw"],
        "transcription_corrected": corrected.astype("boolean"),
        "correction_reason": long["reason"],
        "correction_source": long["supporting_source"],
        "document_check": long["document_check"],
        "document_check_detail": long["basis"],
        "workbook_remarks": long["Remarks"].replace("", None),
        "transcription": "workbook_2023",
        "script": "latin",
        "source_path": SOURCE, "source_row_number": long["source_row_number"].astype("Int64"),
        "source_sha256": digest, "original_row_number": long["original_row_number"].astype("Int64"),
    })
    out.loc[out["reserved_woman"].isna() & out["reserved_caste"].notna(), "reserved_label"] = None

    # ---- values held only by the readings: rounds 1995/2000, blank workbook cells, GPs not in the workbook
    wbrows = typed.set_index("source_row_number")
    add = cells[cells["status"].isin(["settled", "correction"]) & (cells["value"] != "")].copy()
    add_wb = add[(add["workbook_row"] != "") & ~add["roster_year"].isin(TERMS.values())]
    add_blank = add.merge(from_readings[["source_row_number", "roster_year"]].astype({"source_row_number": str}),
                          left_on=["workbook_row", "roster_year"], right_on=["source_row_number", "roster_year"])
    add_new = add[add["workbook_row"] == ""]
    extra = pd.concat([add_wb.assign(kind="round not in the workbook"), add_blank.assign(kind="workbook cell blank"),
                       add_new.assign(kind="GP not in the workbook")], ignore_index=True)
    rows = []
    for c in extra.itertuples():
        r = wbrows.loc[int(c.workbook_row)] if c.workbook_row else None
        caste = {"GEN": "NONE", "BCC": "BC", "SC": "SC", "ST": "ST"}[c.value.replace("(W)", "")]
        woman = None if c.women_unknown == "True" else int(c.value.endswith("(W)"))
        rows.append({
            "state": "Maharashtra",
            "district": tidy(r["Districtname"]) if r is not None else c.district,
            "district_raw": r["Districtname"] if r is not None else c.district,
            "block": tidy(r["SubDistrictname"]) if r is not None else c.block,
            "block_raw": r["SubDistrictname"] if r is not None else c.block,
            "gram_panchayat": tidy(r["LBName"]) if r is not None else c.gram_panchayat_document,
            "gram_panchayat_raw": r["LBName"] if r is not None else c.gram_panchayat_document,
            "gram_panchayat_devanagari": (tidy(r["LBName_LL"]) or None) if r is not None else c.gram_panchayat_document,
            "tier": "gp_head", "tier_local": "sarpanch", "roster_year": c.roster_year,
            "workbook_column": next((k for k, v in TERMS.items() if v == c.roster_year), None) if r is not None else None,
            "roster_year_basis": "document", "round_scope": c.round_scope or "all",
            "reserved_raw": c.value, "reserved_caste_local": LOCAL[caste], "reserved_caste": caste, "reserved_woman": woman,
            "reserved_label": LABEL.get((caste, woman)) if woman is not None else None, "reserved_caste_scheme": "sc_st_obc",
            "workbook_value_raw": (r[next(k for k, v in TERMS.items() if v == c.roster_year)] if r is not None and c.roster_year in TERMS.values() else None),
            "transcription_corrected": False, "correction_reason": None, "correction_source": c.documents.replace(" || ", "; "),
            "document_check": check_of(c.status, c.basis), "document_check_detail": c.basis, "workbook_remarks": None,
            "transcription": "rti_reading_2026", "script": "latin" if r is not None else "devanagari",
            "source_path": READINGS, "source_row_number": int(c.workbook_row) if c.workbook_row else None,
            "source_sha256": rdigest, "original_row_number": (int(r["original_row_number"]) if r is not None else None),
            "_kind": c.kind,
        })
    extra_df = pd.DataFrame(rows)
    kinds = extra_df["_kind"].value_counts().to_dict() if len(extra_df) else {}
    extra_df = extra_df.drop(columns="_kind")
    out = pd.concat([out, extra_df.astype({"reserved_woman": "Int8", "roster_year": "Int64", "source_row_number": "Int64",
                                           "original_row_number": "Int64", "transcription_corrected": "boolean"})], ignore_index=True)
    out["roster_year"] = out["roster_year"].astype("Int64")
    out["reserved_woman"] = out["reserved_woman"].astype("Int8")
    key = ["district", "block", "gram_panchayat", "roster_year"]
    dup = out[out.duplicated(key, keep=False)]
    assert dup.empty, f"a GP-round appears twice:\n{dup[key + ['source_path']].head(10)}"

    by_taluka = docs[docs["taluka"] != "*"].groupby(["district", "taluka"])["document"].agg("; ".join)
    by_district = docs[docs["taluka"] == "*"].groupby("district")["document"].agg("; ".join)
    keys = list(zip(out["district"], out["block"], strict=True))
    out["rti_documents"] = [by_taluka.get(k, by_district.get(k[0])) for k in keys]
    kinds_doc = docs.drop_duplicates(["district", "taluka"]).set_index(["district", "taluka"])["kind"]
    out["rti_document_kind"] = [kinds_doc.get(k, kinds_doc.get((k[0], "*"))) for k in keys]
    out["provenance_level"] = "document"
    out = out.sort_values(["district", "block", "gram_panchayat", "roster_year"]).reset_index(drop=True)
    out.to_parquet(RELEASE / "sarpanch_rti_reservations.parquet", index=False)

    vocab = out.groupby(["reserved_raw", "reserved_caste", "reserved_woman"], dropna=False).size().rename("rows").reset_index()
    vocab.sort_values("rows", ascending=False).to_csv(CHECKS / "roster_vocabulary.csv", index=False)
    cells[cells["status"] == "unsettled"].to_csv(CHECKS / "roster_unsettled.csv", index=False)
    pd.read_csv(MANUAL / "rti_rosters" / "superseded_draws.csv", dtype=str).to_csv(CHECKS / "roster_superseded_draws.csv", index=False)
    changes = []

    def log(rule, column, raw, released, n, reason):
        changes.append(dict(rule_id=rule, table=TABLE, column=column, raw_value=raw, released_value=released,
                            rows_affected=int(n), reason=reason))

    wbo = out[out["source_path"] == SOURCE]
    for column, year in TERMS.items():
        log("T1", "roster_year", f"workbook column {column}", year, (wbo["workbook_column"] == column).sum(),
            "the round as a year; the workbook's label is kept in workbook_column")
    fixed = out[out["transcription_corrected"].fillna(False)]
    for (reason, source), n in fixed.groupby([fixed["correction_reason"].str.split(";").str[0],
                                               fixed["correction_source"].str.split(" (", regex=False).str[0].str[:60]]).size().items():
        log("T2", "reserved_raw", "typed value in workbook_value_raw", "value from the RTI document", n, f"{reason} [{source}]")
    assert int(fixed.shape[0]) == len(fixes), "a correction is missing from the release"
    for col in ("district", "block", "gram_panchayat"):
        log("T3", col, "edge or repeated whitespace", f"trimmed; typed value in {col}_raw", (out[col] != out[col + "_raw"]).sum(),
            "whitespace only")
    log("T4", "reserved_caste, reserved_woman", "typed spellings", "pooled values", out["reserved_caste"].notna().sum(),
        "read through data/checks/roster_vocabulary.csv; central canon.py scheme sc_st_obc")
    log("T4", "reserved_caste, reserved_woman", "not a category (e.g. '-')", "null",
        (out["reserved_caste"].isna() & (out["document_check"] != "unsettled")).sum(), "unknown, never unreserved")
    for kind, n in kinds.items():
        log("T5", "all", "no workbook value", "value from two settled readings of the RTI document", n, kind)
    log("T6", "all", "workbook row duplicating another", "withheld", n_held,
        "data/manual/rti_rosters/withheld_workbook_rows.csv")
    log("T7", "reserved_caste, reserved_woman", "typed value; readings not settled", "null", (out["document_check"] == "unsettled").sum(),
        "the readings disagree with the typed value or with each other; data/checks/roster_unsettled.csv")
    log("T8", "reserved_woman", "caste stated, women's reservation not stated", "null",
        (out["reserved_woman"].isna() & out["reserved_caste"].notna()).sum(), "a list giving the caste category only, or a table printing no women's marks")
    for chk, n in out["document_check"].value_counts().items():
        log("T9", "document_check", "", chk, n, "how the released value was checked against the RTI document")
    pd.DataFrame(changes).to_csv(CHECKS / "roster_changes.csv", index=False)
    print(f"rosters: {len(out):,} GP-rounds, {out.groupby(['district', 'block', 'gram_panchayat']).ngroups:,} GPs, "
          f"{out.groupby(['district', 'block']).ngroups} talukas; {int(fixed.shape[0])} corrected from the documents; "
          f"{len(extra_df)} from the readings only {kinds}; {int((out['document_check'] == 'unsettled').sum())} unsettled; "
          f"withheld workbook cells {n_held}")
    print(out.groupby("roster_year").size().to_string())
    print(out["document_check"].value_counts().to_string())


if __name__ == "__main__":
    build()
