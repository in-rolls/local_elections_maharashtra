"""Admit the original SEC downloads into the repository (run once, by the depositor).

The originals are not in this repository: several also hold ward-member rows, which are not
deposited. For each original file this step

- skips byte-identical repeats (logged with ``duplicate_of``) and files in
  ``data/manual/not_used.csv`` (logged in ``data/search_log/sources_not_used.csv``);
- copies a file that holds only ward-999 rows of programmes named for sarpanch unchanged to
  ``data/raw/sec/<report>/``;
- writes the sarpanch rows of any other file, cells unchanged, to
  ``data/extracted/sec_sarpanch_rows/<report>/<original name>.csv`` with an
  ``original_row_number`` column, and lists the original's name, sha256 and row counts in
  ``data/extracted/sarpanch_extracts.csv``.

A sarpanch row is a row of a programme named for sarpanch that prints ward number 999, or that
prints another ward number for a seat the Ward-Seat report itself names for the sarpanch
(``sarpanch_rows`` below). The second kind is found across files, so the folders are read twice.

Local folder paths are not written anywhere; each folder is named by its ``--source`` label.

usage: python -m local_elections_maharashtra.collect.admit \
           --source LABEL=PRIORITY=FOLDER [--source ...]
PRIORITY breaks ties when two downloads print a contest with the same number of rows
(lower wins).
"""

import argparse
import hashlib
import shutil
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.paths import (
    CHECKS,
    EXTRACTED,
    EXTRACTS,
    FETCH_LOG,
    MANUAL,
    RAW,
    ROOT,
    SEARCH_LOG,
)
from local_elections_maharashtra.readers import aliases, gp_key, kind_of, nk, read_table, sarpanch_mask, tidy

FOLDER = {"counting": "counting", "ward_seat": "ward_seat", "winner_report": "winner_reports"}
FILTER_RULE = ("programme name contains 'sarpan' and (Ward No == 999, or the Ward-Seat report names the ward "
               "for the sarpanch: see collect/admit.py)")


def seat_keys(table: pd.DataFrame, district_alias: dict, taluka_alias: dict) -> pd.Series:
    """Programme and place, as the release build joins counting rows to seats."""
    programme = table["Election Program Name"].map(nk).str.replace("copy", "", regex=False)
    return (programme + "|" + table["District"].map(nk).replace(district_alias) + "|"
            + table["Taluka"].map(nk).replace(taluka_alias) + "|" + table["LocalBody Name"].map(gp_key))


def reservation_key(cells: pd.Series) -> pd.Series:
    return cells.fillna("").map(lambda v: "".join(ch for ch in str(v).upper() if ch.isalnum() or ch in "()"))


class NamedSarpanchWards:
    """Seats the Ward-Seat report names for the sarpanch (Ward Name contains 'sarpan') under a ward
    number other than 999, in programmes named for sarpanch.

    - ``ward_seat_rows``: such a row is the GP's sarpanch seat, unless the same programme also
      prints a ward-999 seat for the GP (then it repeats that seat and stays withheld), or names
      more than one ward of the GP for the sarpanch (a GP has one sarpanch, so none is taken).
    - ``counting_rows``: a counting row with that programme, GP, ward number and the seat's
      reservation is a row of the sarpanch contest, unless the programme also prints a ward-999
      contest for the GP. A counting row that prints no reservation is never matched.
    """

    def __init__(self, tables: list[pd.DataFrame]):
        self.district_alias, self.taluka_alias = aliases()
        self.named: dict[tuple[str, str], set[str]] = {}
        self.seats_999: set[str] = set()
        self.contests_999: set[str] = set()
        for table in tables:
            kind = kind_of(table.columns)
            if kind not in ("ward_seat", "counting"):
                continue
            _, is_999, sarpanch_programme = sarpanch_mask(table)
            key = self.keys(table)
            if kind == "counting":
                self.contests_999.update(key[is_999 & sarpanch_programme])
                continue
            self.seats_999.update(key[is_999 & sarpanch_programme])
            named = sarpanch_programme & ~is_999 & table["Ward Name"].str.contains("sarpan", case=False, na=False)
            for k, ward, res in zip(key[named], table.loc[named, "Ward No"].str.strip(), reservation_key(table.loc[named, "Reservation"]), strict=True):
                self.named.setdefault((k, ward), set()).add(res)
        wards_named: dict[str, set[str]] = {}
        for k, ward in self.named:
            wards_named.setdefault(k, set()).add(ward)
        self.several = {k for k, wards in wards_named.items() if len(wards) > 1}
        self.named = {kw: res for kw, res in self.named.items() if kw[0] not in self.several}

    def keys(self, table: pd.DataFrame) -> pd.Series:
        return seat_keys(table, self.district_alias, self.taluka_alias)

    def ward_seat_rows(self, table: pd.DataFrame) -> pd.Series:
        _, is_999, sarpanch_programme = sarpanch_mask(table)
        named = table["Ward Name"].str.contains("sarpan", case=False, na=False)
        key = self.keys(table)
        return sarpanch_programme & ~is_999 & named & ~key.isin(self.seats_999) & ~key.isin(self.several)

    def counting_rows(self, table: pd.DataFrame) -> pd.Series:
        _, is_999, sarpanch_programme = sarpanch_mask(table)
        if "Ward Reservation" not in table.columns:  # no reservation printed: nothing to match on
            return pd.Series(False, index=table.index)
        ward_column = "Ward No." if "Ward No." in table.columns else "Ward No"
        key, ward, res = self.keys(table), table[ward_column].str.strip(), reservation_key(table["Ward Reservation"])
        match = pd.Series([r != "" and r in self.named.get((k, w), ()) for k, w, r in zip(key, ward, res, strict=True)], index=table.index)
        return sarpanch_programme & ~is_999 & match & ~key.isin(self.contests_999)


def sarpanch_rows(table: pd.DataFrame, kind: str, named: NamedSarpanchWards) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(sarpanch rows, the ward-999 rows among them, rows in a programme named for sarpanch)."""
    keep, _is_999, sarpanch_programme = sarpanch_mask(table)
    if kind == "ward_seat":
        return keep | named.ward_seat_rows(table), keep, sarpanch_programme
    if kind == "counting":
        return keep | named.counting_rows(table), keep, sarpanch_programme
    return keep, keep, sarpanch_programme


def read_all(sources: list[tuple[str, int, Path]]) -> list[pd.DataFrame]:
    """Every readable table once, for the cross-file rule; files in not_used.csv are left out."""
    not_used = set(pd.read_csv(MANUAL / "not_used.csv", dtype=str)["original_filename"])
    seen, tables = set(), []
    for _label, _priority, folder in sources:
        for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if sha in seen or path.name in not_used:
                continue
            seen.add(sha)
            try:
                tables.append(read_table(data)[0])
            except Exception:  # noqa: BLE001, S112 - main() records unreadable files
                continue
    return tables


def main(sources: list[tuple[str, int, Path]]) -> None:
    not_used = pd.read_csv(MANUAL / "not_used.csv", dtype=str).set_index("original_filename")
    for d in (RAW / "sec", EXTRACTED / "sec_sarpanch_rows", SEARCH_LOG, CHECKS):
        d.mkdir(parents=True, exist_ok=True)
    named = NamedSarpanchWards(read_all(sources))
    seen: dict[str, dict] = {}
    examined, fetch, extracts, skipped, withheld = [], [], [], [], []
    for label, priority, folder in sources:
        for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            rec = {"original_filename": path.name, "collection": label, "sha256": sha, "bytes": len(data)}
            if sha in seen:
                first = seen[sha]
                rec.update(deposit="duplicate_bytes", duplicate_of=first["original_filename"], where="not stored: same bytes as another download")
                examined.append(rec)
                if first.get("repo_path", "").startswith("data/raw/"):
                    fetch.append(dict(path=f"{Path(first['repo_path']).parent.as_posix()}/{path.name}", url="",
                                      sha256=sha, bytes=len(data), fetched_at_utc="", method="manual",
                                      duplicate_of=first["repo_path"], collection=label, priority=priority))
                continue
            seen[sha] = rec
            try:
                table, fmt, n_tables = read_table(data)
            except Exception as error:  # noqa: BLE001 - recorded, not hidden
                rec.update(deposit="unreadable", note=str(error)[:80], where="not deposited: unreadable")
                examined.append(rec)
                continue
            kind = kind_of(table.columns)
            rec.update(format=fmt, n_tables=n_tables, rows=len(table), kind=kind or "not_a_seat_table")
            if "Election Program Name" in table.columns:
                programmes = sorted({tidy(x) for x in table["Election Program Name"] if tidy(x)})
                rec.update(programmes=len(programmes), election_programme=" | ".join(programmes))
            if kind is None:
                rec.update(deposit="none", where="not deposited: not a seat or counting table")
                examined.append(rec)
                continue
            keep, keep_999, sarpanch_programme = sarpanch_rows(table, kind, named)
            rec["sarpanch_rows"] = int(keep.sum())
            rec["sarpanch_rows_other_ward_no"] = int((keep & ~keep_999).sum())
            if path.name in not_used.index:
                rec.update(deposit="examined_not_used", where="not deposited: see search_log/sources_not_used.csv")
                skipped.append(dict(original_filename=path.name, original_sha256=sha, original_bytes=len(data),
                                    kind=kind, rows=len(table), sarpanch_rows=int(keep.sum()),
                                    reason=not_used.at[path.name, "reason"],
                                    decided_by=not_used.at[path.name, "decided_by"],
                                    decided_on=not_used.at[path.name, "decided_on"]))
                examined.append(rec)
                continue
            odd = ~keep & sarpanch_programme
            if odd.any():
                ward = "Ward No." if "Ward No." in table.columns else "Ward No"
                grouped = table[odd].assign(_w=table.loc[odd, ward].str.strip()).groupby(["Election Program Name", "_w"]).size()
                for (programme, ward_no), n in grouped.items():
                    withheld.append(dict(file=path.name, programme=tidy(programme), ward_no_printed=ward_no, rows=int(n)))
            if not keep.any():
                rec.update(deposit="none", where="not deposited: no sarpanch rows (ward-member rows only)")
                examined.append(rec)
                continue
            if keep_999.all():
                assert n_tables == 1, f"{path.name}: a file committed unchanged must hold one table"
                repo_path = f"data/raw/sec/{FOLDER[kind]}/{path.name}"
                (ROOT / repo_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, ROOT / repo_path)
                fetch.append(dict(path=repo_path, url="", sha256=sha, bytes=len(data), fetched_at_utc="",
                                  method="manual", duplicate_of="", collection=label, priority=priority))
                rec["deposit"] = "raw_unchanged"
            else:
                repo_path = f"data/extracted/sec_sarpanch_rows/{FOLDER[kind]}/{path.name}.csv"
                (ROOT / repo_path).parent.mkdir(parents=True, exist_ok=True)
                rows = table[keep].copy()
                rows["original_row_number"] = rows.index + 1
                rows.to_csv(ROOT / repo_path, index=False)
                extracts.append(dict(path=repo_path, sha256=hashlib.sha256((ROOT / repo_path).read_bytes()).hexdigest(),
                                     original_filename=path.name, original_sha256=sha, original_bytes=len(data),
                                     original_format=fmt, kind=kind, rows_kept=int(keep.sum()),
                                     rows_other_ward_no=int((keep & ~keep_999).sum()),
                                     rows_withheld=int((~keep).sum()), withheld_in_sarpanch_programme=int(odd.sum()),
                                     collection=label, priority=priority, filter_rule=FILTER_RULE))
                rec["deposit"] = "sarpanch_extract"
            rec["repo_path"] = rec["where"] = repo_path
            examined.append(rec)
    pd.DataFrame(fetch).to_csv(FETCH_LOG, index=False)
    pd.DataFrame(extracts).to_csv(EXTRACTS, index=False)
    pd.DataFrame(skipped).to_csv(SEARCH_LOG / "sources_not_used.csv", index=False)
    index = pd.DataFrame(examined).drop(columns=["repo_path"], errors="ignore")
    for column in ("n_tables", "rows", "programmes", "sarpanch_rows", "sarpanch_rows_other_ward_no"):
        index[column] = index[column].astype("Int64")
    index.to_csv(SEARCH_LOG / "files_examined.csv", index=False)
    pd.DataFrame(withheld).to_csv(CHECKS / "withheld_by_programme.csv", index=False)
    print(pd.DataFrame(examined)["deposit"].value_counts().to_string())


def parse_source(text: str) -> tuple[str, int, Path]:
    label, priority, folder = text.split("=", 2)
    return label, int(priority), Path(folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    main(parser.parse_args().source)
