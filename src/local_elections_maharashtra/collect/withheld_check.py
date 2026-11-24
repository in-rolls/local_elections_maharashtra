"""What are the counting rows still withheld from sarpanch-named programmes? (run by the depositor)

Some SEC exports named for a sarpanch programme also print contests with a ward number other
than 999. ``admit`` deposits those the Ward-Seat report names for the sarpanch; the rest are
withheld. This step reads the same original downloads and asks, contest by contest, whether a
withheld contest is a ward-member contest or could be a sarpanch contest, using the SEC's own
Ward-Seat reports:

- a GP elects one sarpanch, so a GP with withheld contests in several wards, or with its
  sarpanch contest (ward 999) printed separately in the same programme, has ward-member contests;
- otherwise the contest's votes are compared with the ward's electors in the SEC Ward-Seat report
  of the ward-member programme of the same date (``--member-results``; not deposited): a ward-member
  contest cannot receive more votes than its ward has electors. The electors printed on the
  sarpanch programme's own row are not used for this, since a sarpanch seat printed under a ward
  number carries the whole GP's electors there. Votes in a sarpanch contest come from the whole GP;
  ``benchmark`` gives the range seen in the ward-999 contests. Without a member report of the same
  date the contest is marked "cannot tell".

Only counts per programme are written to the repository (``data/checks/withheld_contests.csv``
and ``withheld_contests_benchmark.json``). The contest-level table holds ward-member results and
is written only to the private folder given by ``--detail``.

usage: python -m local_elections_maharashtra.collect.withheld_check \
           --source LABEL=PRIORITY=FOLDER [--source ...] --member-results PATH --detail PRIVATE_FOLDER
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.collect.admit import NamedSarpanchWards, parse_source, read_all
from local_elections_maharashtra.paths import CHECKS, MANUAL
from local_elections_maharashtra.readers import aliases, gp_key, kind_of, nk, read_table, sarpanch_mask, seat_aliases, tidy

MONTHS = "january february march april may june july august september october november december".split()
VERDICTS = [
    "sarpanch contest: the seat report names this ward SARPANCH PRABHAG",
    "cannot tell: the seat report names several wards of the GP for the sarpanch",
    "ward-member contest: several wards of the GP are printed",
    "ward-member contest: the GP's sarpanch contest is printed separately",
    "ward-member contest: votes fit the ward's electors in the member report of the same date",
    "possible sarpanch contest: votes exceed the ward's electors in the member report of the same date",
    "fits both the ward's electors and the GP's",
    "cannot tell: no member report of the same date for the ward",
]


def link(programme: str) -> str:
    """Key that ties a counting programme to the Ward-Seat rows of the same election: the
    dd-mm-yyyy date in the name, else month and year, else the name itself."""
    name = tidy(programme)
    date = re.findall(r"(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(20\d{2})", name)
    if date:
        d, m, y = date[-1]
        return f"{int(y)}-{int(m):02d}-{int(d):02d}"
    low = name.lower()
    month = next((m for m in MONTHS if m in low or m[:3] + " " in low), None)
    year = re.search(r"20\d{2}", low)
    if month and year:
        return f"{year.group(0)}-{month}"
    return nk(name).replace("copy", "")


def norm_res(value) -> str:
    return re.sub(r"[^A-Z()]", "", str(value).upper())


def member_wards(member_results: Path, da: dict, ta: dict) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """From the member report: electors of each ward, (date, place, ward) -> electors, where its rows agree; of each
    GP, (date, place); and the seats of each ward, by (date, place, ward) and by (date, place, ward, reservation)."""
    m = pd.read_parquet(member_results)
    m = m[m["in_ward_seat_report"].fillna(False).astype(bool)].copy()
    m["date"] = pd.to_datetime(m["programme_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    m["g"] = [f"{da.get(nk(d), nk(d))}|{ta.get(nk(b), nk(b))}|{gp_key(g)}" for d, b, g in zip(m["district"], m["block"], m["gram_panchayat"], strict=True)]
    m["electors"] = m[["electors_man", "electors_woman", "electors_other"]].fillna(0).sum(axis=1)
    m["ward"] = m["ward_no"].astype(str).str.strip()
    per = m.dropna(subset=["date"]).groupby(["date", "g", "ward"])["electors"].agg(["min", "max"])
    ward = per.loc[per["min"] == per["max"], "max"]
    ok = per.groupby(level=[0, 1]).apply(lambda x: bool((x["min"] == x["max"]).all()))
    gp = ward.groupby(level=[0, 1]).sum()
    m["res"] = m["reserved_raw"].map(norm_res)
    seats = m.dropna(subset=["date"])
    return (ward, gp[gp.index.isin(ok[ok].index)], seats.groupby(["date", "g", "ward"]).size(),
            seats.groupby(["date", "g", "ward", "res"]).size())


def main(sources, member_results: Path, detail: Path) -> None:
    da, ta = aliases()
    m_ward, m_gp, m_seats, m_seats_res = member_wards(member_results, da, ta)
    not_used = set(pd.read_csv(MANUAL / "not_used.csv", dtype=str)["original_filename"])

    joined = seat_aliases()

    def place(t):
        """District|taluka|GP, with the GPs of data/manual/aliases.csv (level seat) under their Ward-Seat spelling."""
        out = []
        for p, d, b, g in zip(t["Election Program Name"], t["District"], t["Taluka"], t["LocalBody Name"], strict=True):
            key = f"{nk(p).replace('copy', '')}|{da.get(nk(d), nk(d))}|{ta.get(nk(b), nk(b))}|{gp_key(g)}"
            out.append(joined.get(key, key).split("|", 1)[1])
        return out

    named = NamedSarpanchWards(read_all(sources))
    seen, counting, seats = set(), [], []
    for label, _priority, folder in sources:
        for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")):
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if sha in seen or path.name in not_used:
                continue
            seen.add(sha)
            try:
                table, _fmt, _n = read_table(data)
            except Exception:  # noqa: BLE001, S112 - admit records unreadable files
                continue
            kind = kind_of(table.columns)
            if kind == "counting":
                keep, is_999, sarpanch_programme = sarpanch_mask(table)
                admitted = named.counting_rows(table)
                t = table[sarpanch_programme].copy()
                t["is_999"] = is_999[sarpanch_programme]
                t["admitted"] = admitted[sarpanch_programme]
                t["file"], t["collection"] = path.name, label
                counting.append(t)
            elif kind == "ward_seat":
                seats.append(table)
    c = pd.concat(counting, ignore_index=True)
    c["programme"] = c["Election Program Name"].map(tidy)
    c["link"], c["g"] = c["programme"].map(link), place(c)
    c["ward"] = c["Ward No."].str.strip()
    c["res"] = c["Ward Reservation"].map(norm_res)
    c["votes"] = pd.to_numeric(c["Total Votes Secured"], errors="coerce")
    # the same contest can be printed in two downloads: keep each programme's rows from one file
    first_file = c.groupby(["programme", "g", "ward", "res"])["file"].transform("min")
    c = c[c["file"] == first_file]

    s = pd.concat(seats, ignore_index=True).drop_duplicates()
    s["link"], s["g"] = s["Election Program Name"].map(link), place(s)
    s["ward"] = s["Ward No"].str.strip()
    s["res"] = s["Reservation"].map(norm_res)
    s["electors"] = sum(pd.to_numeric(s[col], errors="coerce").fillna(0) for col in ("Male Voters", "Female Voters", "Other Voters"))
    s["returned"] = pd.to_numeric(s["No. of Candidates to be returned from Reservation"], errors="coerce").fillna(1)
    s["named_sarpanch"] = s["Ward Name"].str.contains("sarpan", case=False, na=False)
    seat = s.groupby(["link", "g", "ward"]).agg(res=("res", lambda x: sorted(set(x))), electors=("electors", "max"), rows=("res", "size"))
    # a seat row whose ward number is not 999 but whose Ward Name says sarpanch (e.g. "SARPANCH PRABHAG")
    named = s[s["named_sarpanch"] & (s["ward"] != "999")].groupby(["link", "g", "ward"]).agg(
        res=("res", lambda x: sorted(set(x))), electors=("electors", "max"))
    several = {k for k, n in named.reset_index().groupby(["link", "g"])["ward"].nunique().items() if n > 1}
    returned = s.groupby(["link", "g", "ward", "res"])["returned"].sum()

    # benchmark: votes in ward-999 contests over the GP's electors in the same programme's sarpanch seat
    bench = c[c["is_999"]].groupby(["link", "g"])["votes"].sum().rename("votes").reset_index()
    gp_el = seat.xs("999", level="ward")["electors"].rename("gp_electors")
    bench = bench.join(gp_el, on=["link", "g"])
    ratio = (bench["votes"] / bench["gp_electors"])[(bench["votes"] > 0) & (bench["gp_electors"] > 0)]
    low, high = float(ratio.quantile(0.01)), 1.05
    benchmark = dict(ward_999_contests=int(len(ratio)), votes_over_gp_electors_median=round(float(ratio.median()), 3),
                     votes_over_gp_electors_p01=round(low, 3), votes_over_gp_electors_p99=round(float(ratio.quantile(0.99)), 3),
                     sarpanch_fit_range=[round(low, 3), high])

    w = c[~c["is_999"] & ~c["admitted"]]
    has_999 = set(map(tuple, c.loc[c["is_999"], ["link", "g"]].drop_duplicates().to_numpy()))
    wards_in_gp = w.groupby(["programme", "g"])["ward"].nunique()
    rows = []
    for (programme, lk, g, ward, res), grp in w.groupby(["programme", "link", "g", "ward", "res"]):
        votes = float(grp["votes"].sum())
        member = seat.loc[(lk, g, ward)] if (lk, g, ward) in seat.index else None
        sarpanch = seat.loc[(lk, g, "999")] if (lk, g, "999") in seat.index else None
        seats_in_contest = (returned.loc[(lk, g, ward)].sum() if res == "" else returned.get((lk, g, ward, res), 1)) if member is not None else 1
        ward_el = m_ward.get((lk, g, ward)) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", lk) else None
        # seats the contest fills, from the member report: each voter casts one vote per seat
        if ward_el:
            seats_in_contest = int(m_seats.get((lk, g, ward), 1) if res == "" else m_seats_res.get((lk, g, ward, res), 1))
        gp_el = m_gp.get((lk, g)) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", lk) else None
        if gp_el is None and sarpanch is not None and sarpanch["electors"] > 0:
            gp_el = sarpanch["electors"]
        fits_sarpanch = bool(gp_el and low <= votes / gp_el <= high)
        named_seat = named.loc[(lk, g, ward)] if (lk, g, ward) in named.index else None
        if (lk, g) in several:
            verdict = VERDICTS[1]
        elif named_seat is not None and res != "" and res in named_seat["res"]:
            verdict = VERDICTS[0]
        elif wards_in_gp[(programme, g)] > 1:
            verdict = VERDICTS[2]
        elif (lk, g) in has_999:
            verdict = VERDICTS[3]
        elif not ward_el:
            verdict = VERDICTS[7]
        elif votes > 1.05 * ward_el * seats_in_contest:
            verdict = VERDICTS[5]
        elif fits_sarpanch:
            verdict = VERDICTS[6]
        else:
            verdict = VERDICTS[4]
        rows.append(dict(programme=programme, file=grp["file"].iloc[0], place=g, ward_no_printed=ward, reservation_printed=res,
                         rows=len(grp), votes=votes,
                         ward_seat_reservations=";".join(member["res"]) if member is not None else "",
                         ward_named_sarpanch=named_seat is not None,
                         named_seat_reservation=";".join(named_seat["res"]) if named_seat is not None else "",
                         named_seat_electors=named_seat["electors"] if named_seat is not None else None,
                         gp_has_999_seat=sarpanch is not None,
                         ward_electors_member_report=ward_el,
                         gp_electors_member_report=m_gp.get((lk, g)),
                         sarpanch_seat_reservation=";".join(sarpanch["res"]) if sarpanch is not None else "",
                         gp_electors=sarpanch["electors"] if sarpanch is not None else None,
                         votes_over_ward_electors=votes / ward_el if ward_el else None,
                         votes_over_gp_electors=votes / sarpanch["electors"] if sarpanch is not None and sarpanch["electors"] else None,
                         verdict=verdict))
    out = pd.DataFrame(rows)
    detail.mkdir(parents=True, exist_ok=True)
    out.to_csv(detail / "withheld_contests_detail.csv", index=False)

    summary = out.groupby("programme").agg(contests=("place", "size"), rows=("rows", "sum"), gps=("place", "nunique"),
                                           median_votes_over_ward_electors=("votes_over_ward_electors", "median"),
                                           median_votes_over_gp_electors=("votes_over_gp_electors", "median"))
    counts = out.groupby(["programme", "verdict"]).size().unstack(fill_value=0).reindex(columns=VERDICTS, fill_value=0)
    summary = summary.join(counts).round(3).reset_index()
    order = out.groupby("programme")["file"].first().map(lambda f: (link(out.loc[out["file"] == f, "programme"].iloc[0]), f))
    summary = summary.assign(_o=summary["programme"].map(order)).sort_values("_o").drop(columns="_o")
    summary.to_csv(CHECKS / "withheld_contests.csv", index=False)
    (CHECKS / "withheld_contests_benchmark.json").write_text(json.dumps(benchmark, indent=1) + "\n")
    print(json.dumps(benchmark))
    print(out["verdict"].value_counts().to_string())
    print(f"{len(out)} contests, {int(out['rows'].sum())} rows; detail written to the private folder")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    parser.add_argument("--member-results", required=True, type=Path)
    parser.add_argument("--detail", required=True, type=Path)
    args = parser.parse_args()
    main(args.source, args.member_results, args.detail)
