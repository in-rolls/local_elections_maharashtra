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

A sarpanch row is a row of a programme named for sarpanch that prints ward number 999; or that
prints another ward number for a seat the Ward-Seat report itself names for the sarpanch; or that
prints the one ward number of a GP whose seat row carries the whole GP's electors, measured
against the ward-member Ward-Seat report of the same date (``data/extracted/member_gp_electors.csv``,
written by ``collect/member_electors.py``). See ``NamedSarpanchWards``. The second and third kinds
are found across files, so the folders are read twice.

Local folder paths are not written anywhere; each folder is named by its ``--source`` label.

Files keep the names they arrived with. Two downloads may carry the same name with different bytes
(the portal names a file by its report and date). A repository path belongs to the download whose
sha256 the committed logs record for it (``fetch_log.csv``, ``sarpanch_extracts.csv``), or to the first
download that writes it in this run; admit stops before another download is written there
(``write_once``). An extract of the same download may be rewritten when the row rule changes.

A source folder may hold a hidden ``.fetched.csv`` (``original_filename, url, fetched_at_utc``) for
downloads whose time and report page were recorded; those values go to the fetch log. Without it
both stay blank, as for the downloads of 2023 and 2024.

usage: python -m local_elections_maharashtra.collect.admit \
           --source LABEL=PRIORITY=FOLDER [--source ...]
PRIORITY breaks ties when two downloads print a contest with the same number of rows
(lower wins).
"""

import argparse
import hashlib
import re
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.paths import (
    CHECKS,
    EXTRACTED,
    EXTRACTS,
    FETCH_LOG,
    MANUAL,
    MEMBER_ELECTORS,
    RAW,
    ROOT,
    SEARCH_LOG,
)
from local_elections_maharashtra.readers import (
    aliases,
    gp_key,
    kind_of,
    nk,
    read_table,
    sarpanch_mask,
    seat_aliases,
    tidy,
)

FOLDER = {"counting": "counting", "ward_seat": "ward_seat", "winner_report": "winner_reports"}
FILTER_RULE = ("programme name contains 'sarpan' and (Ward No == 999, or the Ward-Seat report names the ward "
               "for the sarpanch, or the GP's one ward row carries the GP's electors: see collect/admit.py)")


def committed_owners() -> dict[str, str]:
    """Repository path -> sha256 of the download it holds, as the committed logs record it."""
    owners: dict[str, str] = {}
    if FETCH_LOG.exists():
        f = pd.read_csv(FETCH_LOG, dtype=str, keep_default_na=False)
        owners.update(zip(f.loc[f["duplicate_of"] == "", "path"], f.loc[f["duplicate_of"] == "", "sha256"], strict=True))
    if EXTRACTS.exists():
        e = pd.read_csv(EXTRACTS, dtype=str, keep_default_na=False)
        owners.update(zip(e["path"], e["original_sha256"], strict=True))
    return owners


def write_once(target: Path, data: bytes, sha: str, owners: dict[str, str], origin: str) -> None:
    """Write ``data`` (a download, or the extract of one) to ``target`` unless the path belongs to another download.

    ``owners`` maps repository paths to the sha256 of the download that holds them: seeded from the
    committed logs and extended as this run writes. A path owned by another download means two
    downloads share a name: nothing is written, and the depositor decides which to keep out of the sources.
    """
    path = target.relative_to(ROOT).as_posix()
    if owners.setdefault(path, sha) != sha:
        raise SystemExit(f"{path} belongs to another download ({owners[path][:12]}); not replaced by {origin} "
                         f"({sha[:12]}). Two downloads share this name: keep one of them out of the --source folders.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def seat_keys(table: pd.DataFrame, district_alias: dict, taluka_alias: dict) -> pd.Series:
    """Programme and place, as the release build joins counting rows to seats."""
    programme = table["Election Program Name"].map(nk).str.replace("copy", "", regex=False)
    key = (programme + "|" + table["District"].map(nk).replace(district_alias) + "|"
           + table["Taluka"].map(nk).replace(taluka_alias) + "|" + table["LocalBody Name"].map(gp_key))
    return key.replace(seat_aliases())


ELECTORS_TOLERANCE = 0.02  # a seat row's electors within 2% of the GP's member electors
DATE = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(20\d{2})")


def programme_date(name: str) -> str | None:
    """The last dd-mm-yyyy date printed in a programme name, as yyyy-mm-dd; None where none is printed."""
    found = DATE.findall(str(name))
    if not found:
        return None
    d, m, y = found[-1]
    return f"{int(y)}-{int(m):02d}-{int(d):02d}"


def place_key(district: pd.Series, taluka: pd.Series, gp: pd.Series, district_alias: dict, taluka_alias: dict) -> pd.Series:
    return district.map(nk).replace(district_alias) + "|" + taluka.map(nk).replace(taluka_alias) + "|" + gp.map(gp_key)


def electors(table: pd.DataFrame) -> pd.Series:
    return sum(pd.to_numeric(table[c], errors="coerce").fillna(0) for c in ("Male Voters", "Female Voters", "Other Voters"))


def reservation_key(cells: pd.Series) -> pd.Series:
    return cells.fillna("").map(lambda v: "".join(ch for ch in str(v).upper() if ch.isalnum() or ch in "()"))


class NamedSarpanchWards:
    """Sarpanch seats printed under a ward number other than 999, in programmes named for sarpanch.

    Two kinds:

    - **named**: the Ward-Seat report names the ward for the sarpanch (Ward Name contains 'sarpan'),
      unless the same programme also prints a ward-999 seat for the GP (then it repeats that seat and
      stays withheld), or names more than one ward of the GP for the sarpanch (a GP has one
      sarpanch, so none is taken).
    - **electorate**: in every Ward-Seat download the programme prints the GP under one ward number
      only, in one row (the same reservation and electors wherever printed), with no ward-999 row
      and no named row; the programme name prints a date; and the row's electors are within
      ``ELECTORS_TOLERANCE`` of the GP's electors in the ward-member Ward-Seat report of that date
      (``member_gp_electors.csv``). A ward seat cannot hold the whole GP's electors.

    ``ward_seat_rows`` returns the seat rows of both kinds. ``counting_rows`` returns the counting
    rows with the seat's programme, GP, ward number and reservation, unless the programme also prints
    a ward-999 contest for the GP; for the electorate kind, also unless the counting downloads print
    the GP under a second ward number. A counting row that prints no reservation is never matched.
    ``ward_number_seats`` lists every GP considered for the electorate kind, with its verdict.
    """

    def __init__(self, tables: list[pd.DataFrame], member_electors: pd.DataFrame | None = None):
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
        if member_electors is None:
            member_electors = (pd.read_csv(MEMBER_ELECTORS, dtype=str, keep_default_na=False)
                               if MEMBER_ELECTORS.exists() else pd.DataFrame())
        self._electorate(tables, member_electors)

    def _electorate(self, tables: list[pd.DataFrame], member_electors: pd.DataFrame) -> None:
        named_keys = {k for k, _ in self.named}
        seat_rows, counting_wards = [], {}
        for table in tables:
            kind = kind_of(table.columns)
            if kind not in ("ward_seat", "counting"):
                continue
            _, is_999, sarpanch_programme = sarpanch_mask(table)
            key = self.keys(table)
            if kind == "counting":
                ward_column = "Ward No." if "Ward No." in table.columns else "Ward No"
                other = sarpanch_programme & ~is_999
                for k, w in zip(key[other], table.loc[other, ward_column].str.strip(), strict=True):
                    counting_wards.setdefault(k, set()).add(w)
                continue
            named = table["Ward Name"].str.contains("sarpan", case=False, na=False)
            pick = sarpanch_programme & ~is_999 & ~named & ~key.isin(self.seats_999) & ~key.isin(self.several) & ~key.isin(named_keys)
            if pick.any():
                part = table[pick]
                seat_rows.append(pd.DataFrame({
                    "key": key[pick], "election_programme": part["Election Program Name"].map(tidy),
                    "district": part["District"].map(tidy), "block": part["Taluka"].map(tidy),
                    "gram_panchayat": part["LocalBody Name"].map(tidy), "ward_no": part["Ward No"].str.strip(),
                    "ward_name": part["Ward Name"].map(tidy), "reservation": part["Reservation"].map(tidy),
                    "res": reservation_key(part["Reservation"]), "electors": electors(part).astype(int)}))
        cols = ["key", "election_programme", "district", "block", "gram_panchayat", "ward_numbers", "rows_distinct",
                "ward_name", "reservation", "electors", "programme_date", "member_electors", "member_wards",
                "electors_over_member", "verdict"]
        self.electorate: dict[tuple[str, str], set[str]] = {}
        self.counting_wards = counting_wards
        if not seat_rows:
            self.ward_number_seats = pd.DataFrame(columns=cols)
            return
        s = pd.concat(seat_rows, ignore_index=True)
        if len(member_electors):
            m = member_electors.assign(place=place_key(member_electors["district"], member_electors["block"],
                                                       member_electors["gram_panchayat"], self.district_alias, self.taluka_alias))
            member = m.set_index(["programme_date", "place"])
        out = []
        for k, g in s.groupby("key", sort=True):
            distinct = g.drop_duplicates(["ward_no", "res", "electors"])
            first = g.iloc[0]
            date = programme_date(first["election_programme"])
            place = k.split("|", 1)[1]
            rec = dict(key=k, election_programme=first["election_programme"], district=first["district"],
                       block=first["block"], gram_panchayat=first["gram_panchayat"],
                       ward_numbers=";".join(sorted(g["ward_no"].unique(), key=lambda x: (len(x), x))),
                       rows_distinct=len(distinct), ward_name=first["ward_name"], reservation=first["reservation"],
                       electors=int(first["electors"]), programme_date=date, member_electors=None, member_wards=None,
                       electors_over_member=None)
            hit = member.loc[(date, place)] if date and len(member_electors) and (date, place) in member.index else None
            if hit is not None and isinstance(hit, pd.DataFrame):
                hit = None  # two member records for one GP and date: not used
            if g["ward_no"].nunique() > 1:
                verdict = "withheld: the programme prints the GP under several ward numbers"
            elif len(distinct) > 1:
                verdict = "withheld: downloads print the GP's row with different reservation or electors"
            elif date is None:
                verdict = "withheld: the programme name prints no date to find the member report"
            elif hit is None:
                verdict = "withheld: no member Ward-Seat report of the same date for the GP"
            elif hit["status"] != "ok":
                verdict = f"withheld: member report not usable ({hit['status']})"
            else:
                total = int(hit["electors"])
                rec.update(member_electors=total, member_wards=int(hit["wards"]),
                           electors_over_member=round(first["electors"] / total, 4) if total else None)
                if int(hit["wards"]) < 2:
                    verdict = "withheld: the member report holds one ward of the GP, so its electors cannot tell"
                elif total and abs(first["electors"] - total) <= ELECTORS_TOLERANCE * total:
                    verdict = "admitted: the seat row carries the GP's electors"
                    self.electorate[(k, first["ward_no"])] = {first["res"]}
                else:
                    verdict = "withheld: the seat row's electors differ from the GP's"
            rec["verdict"] = verdict
            out.append(rec)
        table = pd.DataFrame(out, columns=cols).astype({"member_electors": "Int64", "member_wards": "Int64"})
        # a row that is not taken may be a ward-member seat, which this repository does not publish
        held = ~table["verdict"].str.startswith("admitted")
        table.loc[held, ["ward_name", "reservation"]] = ""
        table["electors"] = table["electors"].astype("Int64").mask(held)
        table["electors_over_member"] = table["electors_over_member"].mask(held)
        self.ward_number_seats = table

    def keys(self, table: pd.DataFrame) -> pd.Series:
        return seat_keys(table, self.district_alias, self.taluka_alias)

    def ward_seat_rows(self, table: pd.DataFrame) -> pd.Series:
        _, is_999, sarpanch_programme = sarpanch_mask(table)
        named = table["Ward Name"].str.contains("sarpan", case=False, na=False)
        key = self.keys(table)
        by_name = sarpanch_programme & ~is_999 & named & ~key.isin(self.seats_999) & ~key.isin(self.several)
        ward, res = table["Ward No"].str.strip(), reservation_key(table["Reservation"])
        by_electors = pd.Series([r in self.electorate.get((k, w), ()) for k, w, r in zip(key, ward, res, strict=True)],
                                index=table.index)
        return by_name | (sarpanch_programme & ~is_999 & ~named & by_electors)

    def counting_rows(self, table: pd.DataFrame) -> pd.Series:
        _, is_999, sarpanch_programme = sarpanch_mask(table)
        if "Ward Reservation" not in table.columns:  # no reservation printed: nothing to match on
            return pd.Series(False, index=table.index)
        ward_column = "Ward No." if "Ward No." in table.columns else "Ward No"
        key, ward, res = self.keys(table), table[ward_column].str.strip(), reservation_key(table["Ward Reservation"])
        match = pd.Series([r != "" and (r in self.named.get((k, w), ())
                                        or (r in self.electorate.get((k, w), ()) and len(self.counting_wards.get(k, ())) == 1))
                           for k, w, r in zip(key, ward, res, strict=True)], index=table.index)
        return sarpanch_programme & ~is_999 & match & ~key.isin(self.contests_999)


def sarpanch_rows(table: pd.DataFrame, kind: str, named: NamedSarpanchWards) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(sarpanch rows, the ward-999 rows among them, rows in a programme named for sarpanch)."""
    keep, _is_999, sarpanch_programme = sarpanch_mask(table)
    if kind == "ward_seat":
        return keep | named.ward_seat_rows(table), keep, sarpanch_programme
    if kind == "counting":
        return keep | named.counting_rows(table), keep, sarpanch_programme
    return keep, keep, sarpanch_programme


def fetch_notes(folder: Path) -> dict[str, dict]:
    """Download time and report page per file, where the folder records them (see the module docstring)."""
    note = folder / ".fetched.csv"
    if not note.exists():
        return {}
    return pd.read_csv(note, dtype=str, keep_default_na=False).set_index("original_filename").to_dict("index")


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
    owners = committed_owners()
    examined, fetch, extracts, skipped, withheld = [], [], [], [], []
    for label, priority, folder in sources:
        notes = fetch_notes(folder)
        for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            noted = notes.get(path.name, {})
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
                write_once(ROOT / repo_path, data, sha, owners, f"{path.name} of collection {label}")
                fetch.append(dict(path=repo_path, url=noted.get("url", ""), sha256=sha, bytes=len(data),
                                  fetched_at_utc=noted.get("fetched_at_utc", ""),
                                  method="manual", duplicate_of="", collection=label, priority=priority))
                rec["deposit"] = "raw_unchanged"
            else:
                repo_path = f"data/extracted/sec_sarpanch_rows/{FOLDER[kind]}/{path.name}.csv"
                rows = table[keep].copy()
                rows["original_row_number"] = rows.index + 1
                write_once(ROOT / repo_path, rows.to_csv(index=False).encode(), sha, owners, f"{path.name} of collection {label}")
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
    named.ward_number_seats.drop(columns=["key"]).to_csv(CHECKS / "ward_number_seats.csv", index=False)
    print(pd.DataFrame(examined)["deposit"].value_counts().to_string())
    print(named.ward_number_seats["verdict"].value_counts().to_string())


def parse_source(text: str) -> tuple[str, int, Path]:
    label, priority, folder = text.split("=", 2)
    return label, int(priority), Path(folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    main(parser.parse_args().source)
