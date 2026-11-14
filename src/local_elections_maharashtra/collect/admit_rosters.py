"""Admit the RTI sarpanch reservation rosters (run once, by the depositor).

The rosters are replies to Right to Information requests, held as scans, and a workbook in
which they were typed up. The workbook also holds material that is not from an RTI reply, so
it is not committed. This step writes

- data/manual/rti_rosters/workbook_rows.csv: the workbook's "Reservation Data" rows for
  talukas whose RTI document is listed in data/manual/rti_documents.csv, cells unchanged,
  place and term columns only, with ``original_row_number``;
- data/manual/rti_rosters/documents.csv: each listed RTI document with sha256, size and
  pages (the scans themselves are not committed yet);
- data/search_log/roster_rows_not_admitted.csv: counts of workbook rows left out, by taluka,
  with the reason.

usage: python -m local_elections_maharashtra.collect.admit_rosters WORKBOOK.xlsx SCANS_FOLDER
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.paths import MANUAL, SEARCH_LOG

TERMS = ["2005-10", "2010-15", "2015-20", "2021-25"]
KEEP = ["Districtname", "SubDistrictname", "LBName_LL", "LBName", *TERMS, "Remarks", "Reference"]


def pages(path: Path):
    if path.suffix.lower() != ".pdf":
        return 1
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    return next((int(line.split()[1]) for line in out.splitlines() if line.startswith("Pages:")), None)


def main(workbook: Path, scans: Path) -> None:
    out = MANUAL / "rti_rosters"
    out.mkdir(parents=True, exist_ok=True)
    docs = pd.read_csv(MANUAL / "rti_documents.csv", dtype=str)
    docs["sha256"] = [hashlib.sha256((scans / d).read_bytes()).hexdigest() for d in docs["document"]]
    docs["bytes"] = [(scans / d).stat().st_size for d in docs["document"]]
    docs["pages"] = [pages(scans / d) for d in docs["document"]]
    docs["document"] = docs["document"].map(lambda d: Path(d).name)
    docs["committed"] = False
    docs.to_csv(out / "documents.csv", index=False)

    sheet = pd.read_excel(workbook, sheet_name="Reservation Data", dtype=str)
    sheet["original_row_number"] = sheet.index + 1
    rows = sheet[sheet[TERMS].notna().any(axis=1)].copy()
    district, taluka = rows["Districtname"].str.strip(), rows["SubDistrictname"].str.strip()
    kind = pd.Series("no RTI document on file", index=rows.index)
    for d in docs.itertuples():
        hit = (district == d.district) & ((taluka == d.taluka) | (d.taluka == "*"))
        kind[hit] = d.kind
    admitted = rows[kind.isin(["roster", "draw minutes"])]
    admitted[[*KEEP, "original_row_number"]].to_csv(out / "workbook_rows.csv", index=False)
    left = rows[~rows.index.isin(admitted.index)].assign(reason=kind, district=district, taluka=taluka)
    SEARCH_LOG.mkdir(parents=True, exist_ok=True)
    left.groupby(["district", "taluka", "reason"]).size().rename("gps").reset_index() \
        .to_csv(SEARCH_LOG / "roster_rows_not_admitted.csv", index=False)
    print(f"admitted {len(admitted):,} GP rows in {admitted.groupby([district, taluka]).ngroups} talukas; "
          f"left out {len(left):,} ({left['reason'].value_counts().to_dict()})")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
