"""Write data/README.md and the status part of README.md from data/checks/summary.json,
data/checks/checks.json and the ledgers, so that no number in either file is typed by hand.
The roster section at the end of data/README.md is written by build/readme_rosters.py and kept
as it is here."""

import json

import pandas as pd

from local_elections_maharashtra.build.readme_rosters import END as ROSTERS_END
from local_elections_maharashtra.build.readme_rosters import START as ROSTERS_START
from local_elections_maharashtra.paths import CHECKS, DATA, ROOT, SEARCH_LOG

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
    "ward_no_raw": "`999`, the SEC's ward number for the sarpanch seat",
    "seat_event_id": "Row identifier: sha1 of `source_path#source_row_number`, first 12 hex digits",
    "contest_id": "Links the seat to its rows in `sarpanch_candidates`; null where no counting rows are attached",
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
    doc = f"""# Data

## Sources

The rows of `sarpanch_results` and `sarpanch_candidates` come from reports of the Maharashtra
State Election Commission (SEC) election portal, downloaded by hand between 2023 and 2024. File
names carry a date stamped by the portal; the URL and the time of each download were not
recorded, so `url` and `fetched_at_utc` are blank in [`raw/fetch_log.csv`](raw/fetch_log.csv).
The RTI reservation rosters (`sarpanch_rti_reservations`) have their own sources, described in
[the roster section](#rti-sarpanch-reservation-rosters) at the end of this file.

| Report | What a row is | Columns used |
|---|---|---|
| Counting report | a candidate (or the NOTA count) in one contest | Election Program Name, LocalBody Name, Division, District, Taluka, Name of Contesting Candidate, Candidate Gender, Candidate Cast, Ward No., Ward Reservation, Total Votes Secured, SymbolName, Rank |
| Ward-Seat Details report | a seat in one programme, with its reservation and electors | Election Program Name, LocalBody Name, District, Taluka, Ward No, Ward Name, Reservation, Male / Female / Other Voters |
| Winning Counting report (608 and 1165 programmes) | the winner of one contest | used to decide ties and no-vote contests, and as a check |

Only sarpanch rows are deposited: rows with ward number 999 in a programme whose name contains
"sarpan". How each committed file is held:

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
  ({n(nu['sarpanch_rows'])} sarpanch rows): {nu['reason']}.
- Every file examined is listed, without local paths, in [`search_log/files_examined.csv`](search_log/files_examined.csv).

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
  a ward number other than 999 ({n(s['withheld_in_sarpanch_programmes']['first_phase_2017_rows'])} of them in the
  7 Oct 2017 "First Phase" programme). They are not deposited:

{table(withheld_rows, ['Programme', 'Rows withheld', 'Ward numbers printed'])}

- **Programmes without a date.** {n(R['no_date'])} seats are in programmes whose name prints no full
  date ({n(R['no_year'])} with no year); {n(R['undated_key_collisions'])} of them share district, taluka, GP and
  year with another such seat.
- **Shared place names.** {n(R['flags']['shared_place_name'])} seat rows have place names that normalise to one
  key within a programme; counting rows are not attached to them.
- **Spelling twins.** [`checks/alias_review.csv`](checks/alias_review.csv) lists {n(s['alias_review_pairs'])} seats found
  only in counting reports whose name is close to a Ward-Seat seat of the same programme
  and district. They are not merged.
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
