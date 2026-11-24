"""The GP electors that admit's electorate rule compares with (run by the depositor).

Some sarpanch programmes print a GP's sarpanch seat under a ward number other than 999 (see
``collect/admit.py``, ``NamedSarpanchWards``). Whether such a row is the sarpanch seat is told by its
electors: a ward seat cannot hold the whole GP's electors. The whole GP's electors come from the
SEC Ward-Seat report of the ward-member programme held on the same date, which is not deposited
here (only sarpanch rows are). This step writes, for each GP admit considers, only the sum of the
electors of the GP's member wards on that date, with the member download's name, sha256 and row
numbers, to ``data/extracted/member_gp_electors.csv``. No candidate and no ward-level figure is
written.

Input: the depositor's member release table (a parquet file with one row per member seat, its
Ward-Seat electors and provenance columns ``original_filename``, ``original_sha256``,
``original_row_number``), and the same ``--source`` folders as admit.

A ward's electors are the value its member rows print; where the rows of one ward print different
values, or the GP has member rows of two programmes on the date, the GP is recorded with that
status and no total, and admit does not use it.

usage: python -m local_elections_maharashtra.collect.member_electors \\
           --source LABEL=PRIORITY=FOLDER [--source ...] --member-results PATH
"""

import argparse
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.collect.admit import NamedSarpanchWards, parse_source, place_key, read_all
from local_elections_maharashtra.paths import MEMBER_ELECTORS
from local_elections_maharashtra.readers import aliases

COLUMNS = ["programme_date", "district", "block", "gram_panchayat", "election_programme", "wards", "ward_numbers",
           "electors_man", "electors_woman", "electors_other", "electors", "status", "original_filename",
           "original_sha256", "original_row_numbers"]


def main(sources, member_results: Path) -> None:
    da, ta = aliases()
    named = NamedSarpanchWards(read_all(sources), member_electors=pd.DataFrame())
    wanted = named.ward_number_seats.dropna(subset=["programme_date"])
    wanted = wanted[~wanted["verdict"].str.contains("several ward numbers|different reservation")]
    want = set(zip(wanted["programme_date"], wanted["key"].str.split("|", n=1).str[1], strict=True))

    m = pd.read_parquet(member_results)
    m = m[m["in_ward_seat_report"].fillna(False).astype(bool)].copy()
    if "ward_seat_row_repeated" in m.columns:
        m = m[~m["ward_seat_row_repeated"].fillna(False).astype(bool)]
    m["programme_date"] = pd.to_datetime(m["programme_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    m["place"] = place_key(m["district"], m["block"], m["gram_panchayat"], da, ta)
    m = m[[(d, p) in want for d, p in zip(m["programme_date"], m["place"], strict=True)]]
    out = []
    for (date, _place), g in m.groupby(["programme_date", "place"], sort=True):
        rec = dict(programme_date=date, district=g["district"].iloc[0], block=g["block"].iloc[0],
                   gram_panchayat=g["gram_panchayat"].iloc[0], election_programme=" | ".join(sorted(g["election_programme"].unique())),
                   original_filename=";".join(sorted(g["original_filename"].unique())),
                   original_sha256=";".join(sorted(g["original_sha256"].unique())),
                   original_row_numbers=";".join(str(int(x)) for x in sorted(g["original_row_number"].unique())))
        per = g.groupby("ward_no")[["electors_man", "electors_woman", "electors_other"]].nunique(dropna=False)
        if g["election_programme"].nunique() > 1:
            rec["status"] = "member rows of two programmes on this date"
        elif (per > 1).any().any():
            rec["status"] = "the rows of one ward print different electors"
        else:
            wards = g.drop_duplicates("ward_no")
            sums = {c: int(wards[c].fillna(0).sum()) for c in ("electors_man", "electors_woman", "electors_other")}
            rec.update(sums, electors=sum(sums.values()), wards=len(wards), status="ok",
                       ward_numbers=";".join(sorted(wards["ward_no"].astype(str), key=lambda x: (len(x), x))))
        out.append(rec)
    pd.DataFrame(out, columns=COLUMNS).to_csv(MEMBER_ELECTORS, index=False)
    t = pd.DataFrame(out, columns=COLUMNS)
    print(f"{len(want)} GP-dates wanted; {len(t)} found in the member report; status: {t['status'].value_counts().to_dict()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    parser.add_argument("--member-results", required=True, type=Path)
    args = parser.parse_args()
    main(args.source, args.member_results)
