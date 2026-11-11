"""Admit the original SEC downloads into the repository (run once, by the depositor).

The originals are not in this repository: several also hold ward-member rows, which are not
deposited. For each original file this step

- skips byte-identical repeats (logged with ``duplicate_of``) and files in
  ``data/manual/not_used.csv`` (logged in ``data/search_log/sources_not_used.csv``);
- copies a file that holds only sarpanch rows (ward 999 in a programme named for sarpanch)
  unchanged to ``data/raw/sec/<report>/``;
- writes the sarpanch rows of any other file, cells unchanged, to
  ``data/extracted/sec_sarpanch_rows/<report>/<original name>.csv`` with an
  ``original_row_number`` column, and lists the original's name, sha256 and row counts in
  ``data/extracted/sarpanch_extracts.csv``.

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
from local_elections_maharashtra.readers import kind_of, read_table, sarpanch_mask, tidy

FOLDER = {"counting": "counting", "ward_seat": "ward_seat", "winner_report": "winner_reports"}
FILTER_RULE = "Ward No == 999 and programme name contains 'sarpan'"


def main(sources: list[tuple[str, int, Path]]) -> None:
    not_used = pd.read_csv(MANUAL / "not_used.csv", dtype=str).set_index("original_filename")
    for d in (RAW / "sec", EXTRACTED / "sec_sarpanch_rows", SEARCH_LOG, CHECKS):
        d.mkdir(parents=True, exist_ok=True)
    seen: dict[str, dict] = {}
    examined, fetch, extracts, skipped, withheld = [], [], [], [], []
    for label, priority, folder in sources:
        for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            rec = {"original_filename": path.name, "collection": label, "sha256": sha, "bytes": len(data)}
            if sha in seen:
                first = seen[sha]
                rec.update(deposit="duplicate_bytes", duplicate_of=first["original_filename"])
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
                rec.update(deposit="unreadable", note=str(error)[:80])
                examined.append(rec)
                continue
            kind = kind_of(table.columns)
            rec.update(format=fmt, n_tables=n_tables, rows=len(table), kind=kind or "not_a_seat_table")
            if kind is None:
                rec["deposit"] = "none"
                examined.append(rec)
                continue
            keep, is_999, sarpanch_programme = sarpanch_mask(table)
            rec["sarpanch_rows"] = int(keep.sum())
            if path.name in not_used.index:
                rec["deposit"] = "examined_not_used"
                skipped.append(dict(original_filename=path.name, original_sha256=sha, original_bytes=len(data),
                                    kind=kind, rows=len(table), sarpanch_rows=int(keep.sum()),
                                    reason=not_used.at[path.name, "reason"],
                                    decided_by=not_used.at[path.name, "decided_by"],
                                    decided_on=not_used.at[path.name, "decided_on"]))
                examined.append(rec)
                continue
            odd = ~is_999 & sarpanch_programme
            if odd.any():
                ward = "Ward No." if "Ward No." in table.columns else "Ward No"
                grouped = table[odd].assign(_w=table.loc[odd, ward].str.strip()).groupby(["Election Program Name", "_w"]).size()
                for (programme, ward_no), n in grouped.items():
                    withheld.append(dict(file=path.name, programme=tidy(programme), ward_no_printed=ward_no, rows=int(n)))
            if not keep.any():
                rec["deposit"] = "none"
                examined.append(rec)
                continue
            if keep.all():
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
                                     rows_withheld=int((~keep).sum()), withheld_in_sarpanch_programme=int(odd.sum()),
                                     collection=label, priority=priority, filter_rule=FILTER_RULE))
                rec["deposit"] = "sarpanch_extract"
            rec["repo_path"] = repo_path
            examined.append(rec)
    pd.DataFrame(fetch).to_csv(FETCH_LOG, index=False)
    pd.DataFrame(extracts).to_csv(EXTRACTS, index=False)
    pd.DataFrame(skipped).to_csv(SEARCH_LOG / "sources_not_used.csv", index=False)
    pd.DataFrame(examined).drop(columns=["repo_path"], errors="ignore").to_csv(SEARCH_LOG / "files_examined.csv", index=False)
    pd.DataFrame(withheld).to_csv(CHECKS / "withheld_by_programme.csv", index=False)
    print(pd.DataFrame(examined)["deposit"].value_counts().to_string())


def parse_source(text: str) -> tuple[str, int, Path]:
    label, priority, folder = text.split("=", 2)
    return label, int(priority), Path(folder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    main(parser.parse_args().source)
