"""Write data/README.md and the status part of README.md from data/checks/summary.json,
data/checks/checks.json and the ledgers, so that no number in either file is typed by hand.
The roster section at the end of data/README.md is written by build/readme_rosters.py and kept
as it is here."""

import json
import re

import pandas as pd

from local_elections_maharashtra.build.checks import EVIDENCE_ONLY, plain_key
from local_elections_maharashtra.build.readme_rosters import END as ROSTERS_END
from local_elections_maharashtra.build.readme_rosters import START as ROSTERS_START
from local_elections_maharashtra.paths import CHECKS, DATA, EXTRACTS, RELEASE, ROOT, SEARCH_LOG
from local_elections_maharashtra.readers import seat_aliases

RESULT_COLUMNS = {
    "state": "Maharashtra",
    "year": "Year of the programme, read from its name; null where the name prints no year",
    "programme_date": "Date printed in the programme name (dd-mm-yyyy), as a date; null where none is printed",
    "election_programme": "SEC election programme, as the Ward-Seat report spells it (single-spaced)",
    "election_programme_raw": "The programme name exactly as this row's source prints it",
    "election_type": "`By Election` where the programme name contains 'bye', else `General Election`",
    "election_duration": "The date as printed in the programme name, the event discriminator in the master's seat key",
    "district, block, gram_panchayat": "District, taluka and local body (GP), whitespace tidied; printed values in the `*_raw` columns",
    "tier, tier_local": "`gp_head`, `sarpanch`",
    "ward_no_raw": "The ward number printed for the seat: `999`, the SEC's number for the sarpanch seat, or another number where the SEC printed the sarpanch seat under a ward number (see Sources)",
    "seat_event_id": "Row identifier: sha1 of `original_sha256#original_row_number` (the SEC download as received and the row's place in it), first 12 hex digits. It does not change when the rows kept from a download change. All ids changed once, on 24 November 2026, from sha1 of `source_path#source_row_number`; no new id repeats an old one, and `checks/id_changes_2026-11-24.csv` maps old to new",
    "contest_id": "Links the seat to its rows in `sarpanch_candidates`: sha1 of `original_sha256#original_row_number` of the contest's first counting row, first 12 hex digits (changed with `seat_event_id`); null where no counting rows are attached",
    "reserved_raw": "The seat's reservation as printed in the Ward-Seat report, e.g. `B.C.C.(W)`",
    "reserved_caste_local": "The caste part of `reserved_raw` (`GEN`, `S.C.`, `S.T.`, `B.C.C.`)",
    "reserved_caste": "The seat's category: `NONE`, `SC`, `ST`, `BC` (B.C.C.). A property of the seat, never of the winner",
    "reserved_woman": "1 if the seat is reserved for a woman (`(W)`), else 0",
    "reserved_label, reserved_caste_scheme": "Pooled label (e.g. `BC Woman`); `sc_st_obc`",
    "reserved_raw_counting": "The reservation printed on the counting report's rows for the same seat",
    "reserved_source_conflict": "True where the Ward-Seat and counting reservations differ (both printed)",
    "electors_man, electors_woman, electors_other": "Electors for the seat as the Ward-Seat report prints them (Male / Female / Other Voters)",
    "in_ward_seat_report": "False for seats found only in counting reports",
    "result_in_source": "True where counting rows are attached; null where the seat's place name is shared (below)",
    "shared_place_name": "Two rows of one programme whose place names normalise to the same key; counting rows are not attached to either",
    "seat_candidates": "Distinct candidates (NOTA rows and repeated rows excluded); null for 2017",
    "source_rows_in_contest": "Counting rows of the contest as printed, NOTA rows included",
    "winner, winner_basis": "Winner by rules W1 to W6 (below); `published` or `sole_candidate`",
    "winner_woman_from_candidates": "The winner's Candidate Gender cell in the counting report (1 woman, 0 man)",
    "votes, runner_up, runner_up_votes, margin": "Winner's votes; next candidate; their votes; the difference",
    "runner_up_tie": "Two or more candidates tie for second place; `runner_up` is then null",
    "nota_votes": "Votes on the NOTA row (2018 on)",
    "unopposed_from_candidates": "One distinct candidate and no votes on any row; the source prints no unopposed marker",
    "no_votes_recorded": "Every counting row of the contest shows 0 votes",
    "nota_ranked_first, winner_tie, candidate_row_repeated": "NOTA has the most votes; two candidates printed at rank 1; one candidate printed twice",
    "winner_report_agrees": "Where an SEC winner report covers the seat: it names the same winner",
    "script": "`latin`",
    "source_path, source_row_number, source_sha256": "The committed file the row was read from, its 1-based data row (header excluded), and the file's sha256",
    "original_filename, original_sha256, original_row_number": "The SEC download as received; for extracts it is not committed (see Sources)",
    "result_source_path, result_source_row_number": "Where the winner is printed: the counting row, or the SEC winner report for winners taken from it",
}
CANDIDATE_COLUMNS = {
    "state, year, programme_date, election_programme(_raw), election_type, election_duration": "As in `sarpanch_results`",
    "division, district, block, gram_panchayat": "As printed, whitespace tidied; printed values in the `*_raw` columns",
    "tier, tier_local, ward_no_raw, contest_id": "As in `sarpanch_results`",
    "reserved_*": "The seat's reservation as printed on the counting row (`Ward Reservation`), read as in `sarpanch_results`",
    "candidate_name": "Candidate as printed, whitespace tidied; null on NOTA rows and on every 2017 row (see Known issues)",
    "candidate_name_raw": "The name cell exactly as printed",
    "candidate_name_placeholder": "True on 2017 rows, where the name cell prints `NOTA`",
    "nota_tally": "True on the None-of-the-above row; null for 2017, where the file does not mark it",
    "candidate_row_repeated": "The same name, votes and rank printed twice in one contest",
    "candidate_woman_raw, candidate_woman": "Candidate Gender as printed; 1 Female, 0 Male, null otherwise",
    "candidate_caste_raw, candidate_caste": "Candidate Cast as printed (the person's category); `NONE`, `SC`, `ST`, `BC`",
    "votes, candidate_rank": "Total Votes Secured; Rank, as printed",
    "elected": "True for the winner by rules W1 to W6; false for other candidates; null where no winner is named and on NOTA rows",
    "no_votes_recorded": "Every row of the contest shows 0 votes",
    "symbol_raw": "SymbolName as printed",
    "script, source_path, source_row_number, source_sha256, original_*": "As in `sarpanch_results`",
}


def n(x):
    return f"{int(x):,}"


def table(rows, head):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render():
    s = json.loads((CHECKS / "summary.json").read_text())
    checks = json.loads((CHECKS / "checks.json").read_text())
    changes = pd.read_csv(CHECKS / "changes.csv")
    withheld = pd.read_csv(CHECKS / "withheld_by_programme.csv")
    not_used = pd.read_csv(SEARCH_LOG / "sources_not_used.csv")
    R, C = s["results"], s["candidates"]
    years = table([[y if y != "none" else "no year in the programme name", n(v["seats"]), n(v["with_counting"]),
                    n(v["no_counting"]), n(v["unattachable"]), n(v["winner_named"])] for y, v in R["by_year"].items()],
                  ["Year", "Seats", "With counting rows", "No counting rows", "Shared place name", "Winner named"])
    wr = s["winner_rules"]
    raw, ex = s["raw_unchanged"], s["extracts"]

    status = f"""<!-- status:start -->

| | |
|---|---:|
| Sarpanch seat events (`sarpanch_results`) | {n(R['rows'])} |
| from the SEC Ward-Seat Details reports | {n(R['in_ward_seat'])} |
| found only in SEC counting reports | {n(R['counting_only'])} |
| with counting rows attached | {n(R['result_in_source'].get('True', 0))} |
| winner named | {n(R['winner_named'])} |
| Counting rows (`sarpanch_candidates`) | {n(C['rows'])} in {n(C['contests'])} contests |
| Election programmes | {R['programmes']} ({n(R['by_election_seats'])} seats in by-elections) |

{years}

<!-- status:end -->"""
    readme = (ROOT / "README.md").read_text()
    start, end = readme.index("<!-- status:start -->"), readme.index("<!-- status:end -->") + len("<!-- status:end -->")
    (ROOT / "README.md").write_text(readme[:start] + status + readme[end:])

    ledger_rows = [[r.rule_id, r.table, r.column, str(r.raw_value), str(r.released_value), n(r.rows_affected)]
                   for r in changes.itertuples()]
    checks_rows = [[f"`{c['check']}`", c["appeals_to"], c["status"], c["result"]] for c in checks]
    withheld_rows = [[p, n(g["rows"].sum()), ", ".join(sorted(g["ward_no_printed"].astype(str).unique(), key=lambda x: (len(x), x)))]
                     for p, g in withheld.groupby("programme", sort=False)]
    nu = not_used.iloc[0]
    seats = pd.read_parquet(RELEASE / "sarpanch_results.parquet", columns=["ward_no_raw", "result_in_source", "election_programme"])
    cand = pd.read_parquet(RELEASE / "sarpanch_candidates.parquet", columns=["ward_no_raw", "contest_id"])
    other = seats[seats["ward_no_raw"].str.strip() != "999"]
    other_contests = cand.loc[cand["ward_no_raw"].str.strip() != "999", "contest_id"].nunique()
    other_rows = int((cand["ward_no_raw"].str.strip() != "999").sum())
    other_top = other["election_programme"].value_counts()
    wns = pd.read_csv(CHECKS / "ward_number_seats.csv", dtype=str, keep_default_na=False)
    wns_text = "; ".join(f"{v.split(': ', 1)[1] if ': ' in v else v}: {n(c)}" for v, c in wns["verdict"].value_counts().items())
    wc = pd.read_csv(CHECKS / "withheld_contests.csv")
    bench = json.loads((CHECKS / "withheld_contests_benchmark.json").read_text())
    member_cols = [c for c in wc.columns if c.startswith("ward-member contest")]
    unknown_cols = [c for c in wc.columns if c.startswith("cannot tell")]
    possible_cols = [c for c in wc.columns if c.startswith(("sarpanch contest", "possible sarpanch", "fits both"))]
    wc_member, wc_unknown, wc_possible = (int(wc[cols].to_numpy().sum()) for cols in (member_cols, unknown_cols, possible_cols))
    wc_fp = wc[wc["programme"].str.contains("First Phase", case=False)]
    unknown_text = "; ".join(f"{c.split(': ', 1)[1]}: {n(int(wc[c].sum()))}" for c in unknown_cols if int(wc[c].sum()))
    examined = pd.read_csv(SEARCH_LOG / "files_examined.csv", dtype=str, keep_default_na=False)
    examined = examined[examined["kind"].isin(["counting", "ward_seat", "winner_report"])]
    stem = examined["original_filename"].str.replace(r"(\s*\(\d+\)|\s+-\s+[\dT.-]+|_\d{1,2})?\.xlsx?$", "", regex=True)
    stem = stem.where(stem.str.match(r"(Counting_Report|Ward_seat_details_report)_\d\d_\d\d_\d{4}$"), "other names")
    report = examined["kind"].map({"counting": "Counting", "ward_seat": "Ward-Seat", "winner_report": "Winning Counting"})
    download_rows = [[rep, f"`{st}`" if st != "other names" else st, n(len(g)), n((g["deposit"] == "raw_unchanged").sum()),
                      n((g["deposit"] == "sarpanch_extract").sum()),
                      n(((g["deposit"] == "none") & (g["sarpanch_rows"] == "0")).sum()),
                      n((~g["deposit"].isin(["raw_unchanged", "sarpanch_extract"]) & ~((g["deposit"] == "none") & (g["sarpanch_rows"] == "0"))).sum())]
                     for (rep, st), g in examined.groupby([report, stem], sort=True)]
    # seat-level aliases and the evidence downloads behind them (nothing here is typed by hand)
    joined = seat_aliases()
    alias_years = sorted({re.findall(r"20\d\d", k.split("|")[0])[-1] for k in joined})
    res_all = pd.read_parquet(RELEASE / "sarpanch_results.parquet")
    cand_all = pd.read_parquet(RELEASE / "sarpanch_candidates.parquet")
    printed_cols = {"election_programme_raw": "Election Program Name", "district_raw": "District", "block_raw": "Taluka",
                    "gram_panchayat_raw": "LocalBody Name"}
    res_keys = plain_key(res_all.rename(columns=printed_cols))
    first_printed, first_joined = next(iter(joined.items())) if joined else ("", "")
    seat_row = res_all[res_keys == first_joined]
    example_ws = seat_row["gram_panchayat"].iloc[0] if len(seat_row) else ""
    example_counting = (cand_all.loc[cand_all["contest_id"].isin(seat_row["contest_id"]), "gram_panchayat"].iloc[0]
                        if len(seat_row) else "")
    all_examined = pd.read_csv(SEARCH_LOG / "files_examined.csv", dtype=str, keep_default_na=False)
    extracts_all = pd.read_csv(EXTRACTS, dtype=str, keep_default_na=False)
    ev = all_examined[all_examined["collection"].isin(EVIDENCE_ONLY)]
    ev_kept = extracts_all.loc[extracts_all["collection"].isin(EVIDENCE_ONLY), "original_filename"]
    stamps = sorted({"-".join(m) for f in ev["original_filename"] for m in re.findall(r"_(\d\d)_(\d\d)_(\d{4})", f)},
                    key=lambda d: d[6:] + d[3:5] + d[:2])
    ev_text = (f"{n(len(ev))} counting reports downloaded again later (file names stamped "
               f"{stamps[0]} to {stamps[-1]} by the portal; URL and time not recorded; collection "
               f"`{', '.join(sorted(EVIDENCE_ONLY))}`) were read with the others: {n(len(ev_kept))} are committed as "
               f"sarpanch-row extracts, as evidence for the {n(len(joined))} GPs joined across two spellings (see "
               "[What was changed](#what-was-changed-from-the-sources)), and the check `seat_aliases` confirms they "
               f"release no row; {n((ev['deposit'] == 'duplicate_bytes').sum())} repeat a committed file byte for byte; "
               f"{n((ev['deposit'] == 'examined_not_used').sum())} print only sarpanch contests already in the release and "
               "are listed, each with its reason, in `search_log/sources_not_used.csv`; "
               f"{n((ev['deposit'] == 'none').sum())} hold no sarpanch rows.") if len(ev) else ""
    not_used_other = not_used[~not_used["original_filename"].isin(ev["original_filename"])]
    nu = not_used_other.iloc[0]
    counting_only = res_all[~res_all["in_ward_seat_report"]]
    co_years = sorted(counting_only["year"].dropna().astype(int).unique())
    co_text = (f"{n(len(counting_only))} seats are still found only in counting reports"
               + (f", all of {', '.join(map(str, co_years))}" if co_years else "") + ". "
               + f"[`checks/alias_review.csv`](checks/alias_review.csv) lists {n(s['alias_review_pairs'])} of them whose "
               "name is close to a Ward-Seat seat of the same programme and district; the list uses a name-similarity "
               "threshold and can miss a pair. They are not joined, because no committed download prints them under the "
               "Ward-Seat spelling" + (" and 2017 counting rows print no candidate names to compare" if co_years == [2017] else "")
               + ". Such a GP may appear twice: as a seat found only in counting reports and as a Ward-Seat seat "
               "without counting rows.")
    doc = f"""# Data

## Sources

The rows of `sarpanch_results` and `sarpanch_candidates` come from reports of the Maharashtra
State Election Commission (SEC) election portal. The first downloads were made by hand in 2023 and 2024. File
names carry a date stamped by the portal; the URL and the time of each download were not
recorded, so `url` and `fetched_at_utc` are blank in [`raw/fetch_log.csv`](raw/fetch_log.csv).
The two reports of the one-GP programme of 11-09-2024 (Khuneshwar, Solapur) were downloaded from
the same portal on 24 November 2026 (collection `sec_portal_2026_11`); for them the log gives the
report page and the time, and the file names end in the portal's number for the programme
(`_prog375`), added when the files were collected.
{ev_text}
The RTI reservation rosters (`sarpanch_rti_reservations`) have their own sources, described in
[the roster section](#rti-sarpanch-reservation-rosters) at the end of this file.

| Report | What a row is | Columns used |
|---|---|---|
| Counting report | a candidate (or the NOTA count) in one contest | Election Program Name, LocalBody Name, Division, District, Taluka, Name of Contesting Candidate, Candidate Gender, Candidate Cast, Ward No., Ward Reservation, Total Votes Secured, SymbolName, Rank |
| Ward-Seat Details report | a seat in one programme, with its reservation and electors | Election Program Name, LocalBody Name, District, Taluka, Ward No, Ward Name, Reservation, Male / Female / Other Voters |
| Winning Counting report (608 and 1165 programmes) | the winner of one contest | used to decide ties and no-vote contests, and as a check |

Only sarpanch rows are deposited. A sarpanch row is a row of a programme whose name contains
"sarpan" that prints ward number 999, the SEC's number for the sarpanch seat, or that prints
another ward number for a seat the Ward-Seat report itself names for the sarpanch (its Ward Name
reads "SARPANCH PRABHAG", "SARPANCH WARD" and the like), or that prints the only ward number the
programme gives a GP whose seat row carries the whole GP's electors. The last kind is measured
against the ward-member Ward-Seat report of the same date, which is not deposited: only the sum of
the GP's member-ward electors is, with that download's name, sha256 and row numbers, in
[`extracted/member_gp_electors.csv`](extracted/member_gp_electors.csv). A seat row is taken when its electors are
within 2% of that sum, since a ward seat cannot hold the whole GP's electors; every GP considered,
admitted or not, is in [`checks/ward_number_seats.csv`](checks/ward_number_seats.csv) with its verdict ({wns_text}).
A counting row of the second and third kinds must also print the seat's reservation. None is taken
where the programme prints a ward-999 seat or contest for the same GP, or names more than one ward
of the GP for the sarpanch. {n(len(other))} seats ({n(other_top.iloc[0])} in the
"{other_top.index[0]}" programme) and {n(other_contests)} contests ({n(other_rows)} counting rows) come
in these ways; `ward_no_raw` keeps the printed number. How each committed file is held:

- **Unchanged** (`raw/sec/`): {raw['counting']['files']} counting reports ({raw['counting']['mb']} MB) and
  {raw['ward_seat']['files']} Ward-Seat reports ({raw['ward_seat']['mb']} MB) that hold only sarpanch rows. Each is listed in
  `raw/fetch_log.csv` with its sha256; byte-identical repeats are listed with `duplicate_of`.
- **Sarpanch-row extracts** (`extracted/sec_sarpanch_rows/`): {ex['counting']['files']} counting reports,
  {ex['ward_seat']['files']} Ward-Seat reports and {ex['winner_report']['files']} winner reports also hold other rows, so the files
  themselves are not committed. Only their sarpanch rows are, with cells unchanged and an added
  `original_row_number` column. [`extracted/sarpanch_extracts.csv`](extracted/sarpanch_extracts.csv) gives each original's name, sha256,
  size and the rows kept and withheld. For these rows `original_*` describes a file that is not
  in the repository.
- **Examined, not used** ([`search_log/sources_not_used.csv`](search_log/sources_not_used.csv)): `{nu['original_filename']}`
  ({n(nu['sarpanch_rows'])} sarpanch rows): {nu['reason']}; and the {n(len(not_used) - len(not_used_other))} later
  counting downloads described above.
- Every file examined is listed, without local paths, in [`search_log/files_examined.csv`](search_log/files_examined.csv):
  the election programme it prints, its rows and sarpanch rows, and where it is held or why it
  is not deposited.

**File numbers are not a series.** The portal names every export of one day alike
(`Counting_Report_03_06_2023.xls`), and the browser adds `(1)`, `(2)`, ... to each further
download. The number is the order of download; it does not identify a programme, and the
numbers in `raw/sec/` do not run without breaks because the other downloads are held as extracts
or hold no sarpanch rows. Almost every file prints one election programme, which
`search_log/files_examined.csv` names.

{table(download_rows, ['Report', 'File name stem', 'Downloads', 'Held unchanged', 'Held as sarpanch extract', 'No sarpanch rows, not deposited', 'Other'])}

## Tables

### `release/sarpanch_results.parquet`: one row per sarpanch seat event

A seat event is one GP in one SEC programme. The rows are the seats of the Ward-Seat reports,
with the counting report's contest attached where one exists, plus the seats found only in
counting reports. {s['columns']['results']} columns.

{table([[f'`{k}`' if ',' not in k else ', '.join(f'`{x.strip()}`' for x in k.split(',')), v] for k, v in RESULT_COLUMNS.items()], ['Column', 'Meaning'])}

### `release/sarpanch_candidates.parquet`: one row per counting-report row

Every sarpanch row of the counting report kept for each contest, NOTA rows included, so the table
reconciles row for row with its sources. {s['columns']['candidates']} columns.

{table([[f'`{k}`', v] for k, v in CANDIDATE_COLUMNS.items()], ['Column', 'Meaning'])}

## Winners

| Rule | Contests | When | Winner |
|---|---:|---|---|
| W1 | {n(wr.get('W1', 0))} | votes recorded; the rank-1 row is a candidate | that candidate (`published`) |
| W2 | {n(wr.get('W2', 0))} | votes recorded; the NOTA row has the most votes | null |
| W3 | {n(wr.get('W3', 0))} | no votes on any row; one distinct candidate | that candidate (`sole_candidate`) |
| W4 | {n(wr.get('W4', 0))} | no votes on any row; two or more distinct candidates | the SEC winner report's winner where one covers the contest, else null |
| W5 | {n(wr.get('W5', 0))} | 2017 (names not printed) | null |
| W6 | {n(wr.get('W6', 0))} | two or more candidates printed at rank 1 | the SEC winner report's winner where one covers the contest, else null |

## What was changed from the sources

Every value that differs from its source cell keeps the printed value in a `*_raw` column, and
every rule is counted in [`checks/changes.csv`](checks/changes.csv) ({n(s['changes_rules'])} rules). Rows not
released are listed in [`checks/dropped_rows.csv`](checks/dropped_rows.csv) with the copy that was kept;
reservation, gender and caste readings are in `checks/*_vocabulary.csv`; the place-name
aliases used to join reports are in [`manual/aliases.csv`](manual/aliases.csv) (printed names are not changed).
{n(len(joined))} GPs of {', '.join(alias_years)} are printed under one spelling in the counting download and another
in the Ward-Seat report ({example_counting} and {example_ws}, for example). They are joined as one seat under the
Ward-Seat spelling (level `seat` in the alias file, whose two columns hold programme, district, taluka and GP as
the build normalizes them), because a later download of the same counting report prints the same rows under that
spelling. The check `seat_aliases` compares the rows of each pair in the two downloads cell by cell.

{table(ledger_rows, ['Rule', 'Table', 'Column', 'Printed', 'Released', 'Rows'])}

## Known issues

These are properties of the files as received. The values come from the SEC's servers and
may be wrong where those are.

- **2017: no candidate names.** All {n(C['rows_2017'])} counting rows of 2017 print `NOTA` in the
  candidate-name column and leave gender and caste blank. Names are released as missing; the
  file does not mark which row, if any, is the NOTA count, so no 2017 winner is named.
- **Seats without counting rows.** {n(R['result_in_source'].get('False', 0))} seats in the Ward-Seat reports
  have no counting rows in these files (by year in the README).
- **Rows withheld.** {n(s['withheld_in_sarpanch_programmes']['rows'])} rows inside sarpanch-named programmes print
  a ward number other than 999 and are not sarpanch rows by the rule above ({n(s['withheld_in_sarpanch_programmes']['first_phase_2017_rows'])} of them in the
  7 Oct 2017 "First Phase" programme). They are not deposited. Compared with the Ward-Seat
  reports, contest by contest ([`checks/withheld_contests.csv`](checks/withheld_contests.csv)), {n(wc['contests'].sum())} withheld counting
  contests are {n(wc_member)} ward-member contests (the GP has several wards printed, its sarpanch contest is
  printed separately, or the votes fit the ward's electors in the ward-member Ward-Seat report of the same
  date), {n(wc_unknown)} that cannot be placed ({unknown_text}; {n(int(wc_fp[unknown_cols].to_numpy().sum()))} of them in the
  First Phase), and
  {n(wc_possible)} that may be sarpanch contests (their votes exceed what the ward's electors can cast for its
  seats, or fit both the ward's and the GP's). These {n(wc_possible)} are not released: none has a seat row that
  carries the GP's electors in the member report of the same date, which the rule above requires. Most are in
  GPs listed in [`checks/ward_number_seats.csv`](checks/ward_number_seats.csv) as "the seat row's electors differ from the GP's",
  where the Ward-Seat report prints one ward's electors for a contest whose votes point to the whole GP; the
  SEC files do not settle which is right. Votes in a sarpanch contest come to a median
  {bench['votes_over_gp_electors_median']:.0%} of the GP's electors
  ([`checks/withheld_contests_benchmark.json`](checks/withheld_contests_benchmark.json)); the withheld First Phase contests come to
  {wc_fp['median_votes_over_gp_electors'].iloc[0]:.0%} of the GP's electors and {wc_fp['median_votes_over_ward_electors'].iloc[0]:.0%} of their ward's.

{table(withheld_rows, ['Programme', 'Rows withheld', 'Ward numbers printed'])}

- **Programmes without a date.** {n(R['no_date'])} seats are in programmes whose name prints no full
  date ({n(R['no_year'])} with no year); {n(R['undated_key_collisions'])} of them share district, taluka, GP and
  year with another such seat.
- **Shared place names.** {n(R['flags']['shared_place_name'])} seat rows have place names that normalise to one
  key within a programme; counting rows are not attached to them.
- **Spelling twins.** {n(len(joined))} GPs printed under two spellings are joined (see
  [What was changed](#what-was-changed-from-the-sources)). {co_text}
- **Ties and no-vote contests.** {n(R['flags']['winner_tie'])} contests print two candidates at rank 1;
  {n(R['flags']['no_votes_recorded'])} contests show 0 votes on every row; {n(R['flags']['runner_up_tie'])} seats have a tie for
  second place.

## Checks

Generated by `make checks`. An `external` check compares with a record outside the release; an
`internal` one shows the release agrees with its own sources. `info` reports a count.
[`checks/hand_check.csv`](checks/hand_check.csv) lists 30 seeded-random rows for a person to compare with
the source file; its `verdict` column is filled in by hand.

{table(checks_rows, ['Check', 'Appeals to', 'Status', 'Result'])}
"""
    path = DATA / "README.md"
    old = path.read_text() if path.exists() else ""
    if ROSTERS_START in old and ROSTERS_END in old:
        rosters = old[old.index(ROSTERS_START):old.index(ROSTERS_END) + len(ROSTERS_END)]
    else:
        rosters = f"{ROSTERS_START}\n{ROSTERS_END}"
    path.write_text(doc + "\n" + rosters + "\n")
    print("wrote data/README.md (roster section kept) and the README.md status block")


if __name__ == "__main__":
    render()
