# Data

## Sources

All rows come from reports of the Maharashtra State Election Commission (SEC) election portal,
downloaded by hand between 2023 and 2024. File names carry a date stamped by the portal; the URL
and the time of each download were not recorded, so `url` and `fetched_at_utc` are blank in
[`raw/fetch_log.csv`](raw/fetch_log.csv).

| Report | What a row is | Columns used |
|---|---|---|
| Counting report | a candidate (or the NOTA count) in one contest | Election Program Name, LocalBody Name, Division, District, Taluka, Name of Contesting Candidate, Candidate Gender, Candidate Cast, Ward No., Ward Reservation, Total Votes Secured, SymbolName, Rank |
| Ward-Seat Details report | a seat in one programme, with its reservation and electors | Election Program Name, LocalBody Name, District, Taluka, Ward No, Ward Name, Reservation, Male / Female / Other Voters |
| Winning Counting report (608 and 1165 programmes) | the winner of one contest | used to decide ties and no-vote contests, and as a check |

Only sarpanch rows are deposited: rows with ward number 999 in a programme whose name contains
"sarpan". How each committed file is held:

- **Unchanged** (`raw/sec/`): 29 counting reports (38.9 MB) and
  31 Ward-Seat reports (8.7 MB) that hold only sarpanch rows. Each is listed in
  `raw/fetch_log.csv` with its sha256; byte-identical repeats are listed with `duplicate_of`.
- **Sarpanch-row extracts** (`extracted/sec_sarpanch_rows/`): 17 counting reports,
  27 Ward-Seat reports and 2 winner reports also hold other rows, so the files
  themselves are not committed. Only their sarpanch rows are, with cells unchanged and an added
  `original_row_number` column. [`extracted/sarpanch_extracts.csv`](extracted/sarpanch_extracts.csv) gives each original's name, sha256,
  size and the rows kept and withheld. For these rows `original_*` describes a file that is not
  in the repository.
- **Examined, not used** ([`search_log/sources_not_used.csv`](search_log/sources_not_used.csv)): `CountingDataGP-Part1(2018-2020).xlsx`
  (5,360 sarpanch rows): consolidated workbook, not an SEC portal export; where a portal download prints the same contest, this workbook prints fewer rows; it has a Candidate Sub Category column that prints jati.
- Every file examined is listed, without local paths, in [`search_log/files_examined.csv`](search_log/files_examined.csv).

## Tables

### `release/sarpanch_results.parquet`: one row per sarpanch seat event

A seat event is one GP in one SEC programme. The rows are the seats of the Ward-Seat reports,
with the counting report's contest attached where one exists, plus the seats found only in
counting reports. 58 columns.

| Column | Meaning |
|---|---|
| `state` | Maharashtra |
| `year` | Year of the programme, read from its name; null where the name prints no year |
| `programme_date` | Date printed in the programme name (dd-mm-yyyy), as a date; null where none is printed |
| `election_programme` | SEC election programme, as the Ward-Seat report spells it (single-spaced) |
| `election_programme_raw` | The programme name exactly as this row's source prints it |
| `election_type` | `By Election` where the programme name contains 'bye', else `General Election` |
| `election_duration` | The date as printed in the programme name, the event discriminator in the master's seat key |
| `district`, `block`, `gram_panchayat` | District, taluka and local body (GP), whitespace tidied; printed values in the `*_raw` columns |
| `tier`, `tier_local` | `gp_head`, `sarpanch` |
| `ward_no_raw` | `999`, the SEC's ward number for the sarpanch seat |
| `seat_event_id` | Row identifier: sha1 of `source_path#source_row_number`, first 12 hex digits |
| `contest_id` | Links the seat to its rows in `sarpanch_candidates`; null where no counting rows are attached |
| `reserved_raw` | The seat's reservation as printed in the Ward-Seat report, e.g. `B.C.C.(W)` |
| `reserved_caste_local` | The caste part of `reserved_raw` (`GEN`, `S.C.`, `S.T.`, `B.C.C.`) |
| `reserved_caste` | The seat's category: `NONE`, `SC`, `ST`, `BC` (B.C.C.). A property of the seat, never of the winner |
| `reserved_woman` | 1 if the seat is reserved for a woman (`(W)`), else 0 |
| `reserved_label`, `reserved_caste_scheme` | Pooled label (e.g. `BC Woman`); `sc_st_obc` |
| `reserved_raw_counting` | The reservation printed on the counting report's rows for the same seat |
| `reserved_source_conflict` | True where the Ward-Seat and counting reservations differ (both printed) |
| `electors_man`, `electors_woman`, `electors_other` | Electors for the seat as the Ward-Seat report prints them (Male / Female / Other Voters) |
| `in_ward_seat_report` | False for seats found only in counting reports |
| `result_in_source` | True where counting rows are attached; null where the seat's place name is shared (below) |
| `shared_place_name` | Two rows of one programme whose place names normalise to the same key; counting rows are not attached to either |
| `seat_candidates` | Distinct candidates (NOTA rows and repeated rows excluded); null for 2017 |
| `source_rows_in_contest` | Counting rows of the contest as printed, NOTA rows included |
| `winner`, `winner_basis` | Winner by rules W1 to W6 (below); `published` or `sole_candidate` |
| `winner_woman_from_candidates` | The winner's Candidate Gender cell in the counting report (1 woman, 0 man) |
| `votes`, `runner_up`, `runner_up_votes`, `margin` | Winner's votes; next candidate; their votes; the difference |
| `runner_up_tie` | Two or more candidates tie for second place; `runner_up` is then null |
| `nota_votes` | Votes on the NOTA row (2018 on) |
| `unopposed_from_candidates` | One distinct candidate and no votes on any row; the source prints no unopposed marker |
| `no_votes_recorded` | Every counting row of the contest shows 0 votes |
| `nota_ranked_first`, `winner_tie`, `candidate_row_repeated` | NOTA has the most votes; two candidates printed at rank 1; one candidate printed twice |
| `winner_report_agrees` | Where an SEC winner report covers the seat: it names the same winner |
| `script` | `latin` |
| `source_path`, `source_row_number`, `source_sha256` | The committed file the row was read from, its 1-based data row (header excluded), and the file's sha256 |
| `original_filename`, `original_sha256`, `original_row_number` | The SEC download as received; for extracts it is not committed (see Sources) |
| `result_source_path`, `result_source_row_number` | Where the winner is printed: the counting row, or the SEC winner report for winners taken from it |

### `release/sarpanch_candidates.parquet`: one row per counting-report row

Every sarpanch row of the counting report kept for each contest, NOTA rows included, so the table
reconciles row for row with its sources. 45 columns.

| Column | Meaning |
|---|---|
| `state, year, programme_date, election_programme(_raw), election_type, election_duration` | As in `sarpanch_results` |
| `division, district, block, gram_panchayat` | As printed, whitespace tidied; printed values in the `*_raw` columns |
| `tier, tier_local, ward_no_raw, contest_id` | As in `sarpanch_results` |
| `reserved_*` | The seat's reservation as printed on the counting row (`Ward Reservation`), read as in `sarpanch_results` |
| `candidate_name` | Candidate as printed, whitespace tidied; null on NOTA rows and on every 2017 row (see Known issues) |
| `candidate_name_raw` | The name cell exactly as printed |
| `candidate_name_placeholder` | True on 2017 rows, where the name cell prints `NOTA` |
| `nota_tally` | True on the None-of-the-above row; null for 2017, where the file does not mark it |
| `candidate_row_repeated` | The same name, votes and rank printed twice in one contest |
| `candidate_woman_raw, candidate_woman` | Candidate Gender as printed; 1 Female, 0 Male, null otherwise |
| `candidate_caste_raw, candidate_caste` | Candidate Cast as printed (the person's category); `NONE`, `SC`, `ST`, `BC` |
| `votes, candidate_rank` | Total Votes Secured; Rank, as printed |
| `elected` | True for the winner by rules W1 to W6; false for other candidates; null where no winner is named and on NOTA rows |
| `no_votes_recorded` | Every row of the contest shows 0 votes |
| `symbol_raw` | SymbolName as printed |
| `script, source_path, source_row_number, source_sha256, original_*` | As in `sarpanch_results` |

## Winners

| Rule | Contests | When | Winner |
|---|---:|---|---|
| W1 | 11,872 | votes recorded; the rank-1 row is a candidate | that candidate (`published`) |
| W2 | 1 | votes recorded; the NOTA row has the most votes | null |
| W3 | 1,080 | no votes on any row; one distinct candidate | that candidate (`sole_candidate`) |
| W4 | 36 | no votes on any row; two or more distinct candidates | the SEC winner report's winner where one covers the contest, else null |
| W5 | 3,899 | 2017 (names not printed) | null |
| W6 | 19 | two or more candidates printed at rank 1 | the SEC winner report's winner where one covers the contest, else null |

## What was changed from the sources

Every value that differs from its source cell keeps the printed value in a `*_raw` column, and
every rule is counted in [`checks/changes.csv`](checks/changes.csv) (64 rules). Rows not
released are listed in [`checks/dropped_rows.csv`](checks/dropped_rows.csv) with the copy that was kept;
reservation, gender and caste readings are in `checks/*_vocabulary.csv`; the place-name
aliases used to join reports are in [`manual/aliases.csv`](manual/aliases.csv) (printed names are not changed).

| Rule | Table | Column | Printed | Released | Rows |
|---|---|---|---|---|---|
| R4 | source rows (counting) | row selection | rows other than Ward No 999 in a sarpanch programme | withheld (not deposited) | 6,320 |
| R4 | source rows (ward_seat) | row selection | rows other than Ward No 999 in a sarpanch programme | withheld (not deposited) | 489 |
| R5 | source rows | row selection | no district, taluka or GP name in the source row | dropped; listed in dropped_rows.csv | 4 |
| R5 | source rows | row selection | same contest in another download (identical rows) | dropped; listed in dropped_rows.csv | 42,904 |
| R6 | sarpanch_candidates | election_programme | programme printed with a different spelling or spacing in another file | the Ward-Seat report's spelling; this row's own in election_programme_raw | 11 |
| R9 | sarpanch_candidates | programme_date, year, election_type, election_duration | programme name | read from the programme name | 65,950 |
| R9 | sarpanch_candidates | programme_date | programme name without a dd-mm-yyyy date | nan | 1,355 |
| R9 | sarpanch_candidates | year | programme name without a year | nan | 0 |
| R6 | sarpanch_candidates | division | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in division_raw | 0 |
| R6 | sarpanch_candidates | district | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in district_raw | 0 |
| R6 | sarpanch_candidates | block | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in block_raw | 0 |
| R6 | sarpanch_candidates | gram_panchayat | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in gram_panchayat_raw | 0 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | GEN | NONE, 0 | 16,332 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | GEN(W) | NONE, 1 | 14,309 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | B.C.C. | BC, 0 | 7,299 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | S.T. | ST, 0 | 7,174 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | B.C.C.(W) | BC, 1 | 6,615 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | S.T.(W) | ST, 1 | 6,368 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | S.C. | SC, 0 | 4,004 |
| R8 | sarpanch_candidates | reserved_caste, reserved_woman | S.C.(W) | SC, 1 | 3,849 |
| R8 | sarpanch_candidates | reserved_caste_local | reserved_raw | reserved_raw without the (W) suffix | 65,950 |
| R6 | sarpanch_candidates | candidate_name | edge or repeated whitespace | trimmed; printed value in candidate_name_raw | 1 |
| R1 | sarpanch_candidates | candidate_name | NOTA (every 2017 row) | null; candidate_name_placeholder = true | 15,530 |
| R1 | sarpanch_candidates | nota_tally | (2017) | nan | 15,530 |
| R2 | sarpanch_candidates | candidate_name, nota_tally | NOTA (2018 on) | candidate_name null; nota_tally = true | 12,028 |
| R8 | sarpanch_candidates | candidate_woman | Female | 1 | 19,975 |
| R8 | sarpanch_candidates | candidate_woman | Male | 0 | 18,398 |
| R8 | sarpanch_candidates | candidate_woman | Other | nan | 19 |
| R11 | sarpanch_candidates | candidate_woman, candidate_caste | (blank) on 2017 rows | nan | 15,530 |
| R11 | sarpanch_candidates | candidate_woman, candidate_caste | (blank) on NOTA rows | nan | 12,028 |
| R8 | sarpanch_candidates | candidate_caste | GEN | NONE | 14,295 |
| R8 | sarpanch_candidates | candidate_caste | B.C.C | BC | 9,681 |
| R8 | sarpanch_candidates | candidate_caste | ST | ST | 9,517 |
| R8 | sarpanch_candidates | candidate_caste | SC | SC | 4,899 |
| R7 | sarpanch_candidates | votes, candidate_rank | text | integer | 65,950 |
| R7 | all tables | every cell of .xls/.xlsx sources | spreadsheet number | whole numbers written without .0 | 67,649 |
| R3 | sarpanch_candidates | candidate_row_repeated | same name, votes and rank printed twice in one contest | flag true on each copy | 59 |
| R3-W1 | sarpanch_results | winner | (contest) | votes recorded; the rank-1 row is a candidate: winner as published | 11,872 |
| R3-W2 | sarpanch_results | winner | (contest) | votes recorded; NOTA has the most votes: winner null | 1 |
| R3-W3 | sarpanch_results | winner | (contest) | no votes on any row; one distinct candidate: that candidate (sole_candidate) | 1,080 |
| R3-W4 | sarpanch_results | winner | (contest) | no votes on any row; two or more distinct candidates: null unless an SEC winner report names one | 36 |
| R3-W5 | sarpanch_results | winner | (contest) | 2017: names not in the source: winner null | 3,899 |
| R3-W6 | sarpanch_results | winner | (contest) | two or more candidates printed at rank 1: null unless an SEC winner report names one | 19 |
| R3 | sarpanch_results | winner, winner_basis, result_source_path | (contest) | taken from the SEC winner report (608 and 1165 programmes) | 4 |
| R6 | sarpanch_results | election_programme | programme printed with a different spelling or spacing in another file | the Ward-Seat report's spelling; this row's own in election_programme_raw | 17 |
| R9 | sarpanch_results | programme_date, year, election_type, election_duration | programme name | read from the programme name | 20,608 |
| R9 | sarpanch_results | programme_date | programme name without a dd-mm-yyyy date | nan | 822 |
| R9 | sarpanch_results | year | programme name without a year | nan | 9 |
| R6 | sarpanch_results | district | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in district_raw | 0 |
| R6 | sarpanch_results | block | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in block_raw | 0 |
| R6 | sarpanch_results | gram_panchayat | edge, repeated or embedded whitespace (tabs, newlines) | single spaces, trimmed; printed value in gram_panchayat_raw | 1,652 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | GEN | NONE, 0 | 4,754 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | GEN(W) | NONE, 1 | 4,662 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | B.C.C.(W) | BC, 1 | 2,413 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | B.C.C. | BC, 0 | 2,391 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | S.T.(W) | ST, 1 | 2,144 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | S.T. | ST, 0 | 2,000 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | S.C.(W) | SC, 1 | 1,139 |
| R8 | sarpanch_results | reserved_caste, reserved_woman | S.C. | SC, 0 | 1,105 |
| R8 | sarpanch_results | reserved_caste_local | reserved_raw | reserved_raw without the (W) suffix | 20,608 |
| R10 | sarpanch_results | (join) | district, taluka or GP printed differently in the Ward-Seat and counting files | joined through data/manual/aliases.csv; printed names unchanged | 537 |
| R3 | sarpanch_results | winner_woman_from_candidates | the winner's Candidate Gender cell in the counting file | copied to the seat row | 12,956 |
| R3 | sarpanch_results | runner_up | two or more candidates tie for second place | null; runner_up_tie = true; runner_up_votes kept | 20 |
| R3 | sarpanch_results | unopposed_from_candidates | one distinct candidate and no votes on any row | true | 1,080 |

## Known issues

These are properties of the files as received. The values come from the SEC's servers and
may be wrong where those are.

- **2017: no candidate names.** All 15,530 counting rows of 2017 print `NOTA` in the
  candidate-name column and leave gender and caste blank. Names are released as missing; the
  file does not mark which row, if any, is the NOTA count, so no 2017 winner is named.
- **Seats without counting rows.** 3,710 seats in the Ward-Seat reports
  have no counting rows in these files (by year in the README).
- **Rows withheld.** 6,825 rows inside sarpanch-named programmes print
  a ward number other than 999 (5,719 of them in the
  7 Oct 2017 "First Phase" programme). They are not deposited:

| Programme | Rows withheld | Ward numbers printed |
|---|---|---|
| First Phase G P Sarpanch General Election 07-10-2017 | 5,719 | 1, 2, 3, 4, 5, 6 |
| Second Phase G P Sarpanch General Election 16-10-2017 | 573 | 1, 2, 3, 4, 6 |
| 735 Gram Panchayat Sarpanch General Election Date 26-12-2017_Copy | 54 | 1, 2, 3, 4 |
| 317 Gram Panchayat Sarpanch General Election Date 25-02-2018 | 11 | 1, 123 |
| May 2018 Gram panchayat sARPANCH General Election | 75 | 1, 2, 3, 4, 5 |
| GP Sarpanch Election Date-26-09-2018 | 56 | 1, 2, 3, 4, 5, 6 |
| Sarpanch General Election Gramapanchayt Date 24-02-2019 | 28 | 1, 2, 3 |
| Pune and Solapur 3 GP Gen Election Grampanchayat for Sarpanch Date 24-02-2019 | 5 | 1, 2, 3 |
| 557 Grampanchayat Sarpanch General Election Date 24-03-2019 | 21 | 1, 2, 3 |
| Sarpanch Bye Election in June 2019 | 24 | 1, 2, 3 |
| 67 Grampanchayt General Sarpancha Election Date 31-08-2019 | 17 | 1, 2, 3 |
| 112 Grampanchayt General Election for Sarpanch Date 08-12-2019 | 11 | 1, 2, 3 |
| 608 Grampanchayat Sarpanch General Election Poll Date 18-09-2022 | 38 | 1 |
| 1165 Grampanchayat Sarpanch General Election Poll Date 13-10-2022 | 83 | 1, 3, 4, 5 |
| sarpanch Bye Election 2018 | 4 | 1, 2, 3 |
| 2nd Programme For Gram Panchayat Sarpanch Bye Election 2018 | 2 | 1 |
| May 2018 - Gram panchayat SARPANCH Bye Election | 44 | 1, 2, 3 |
| 2 nd Program May 2018 Gram panchayat Sarpanch General Election | 6 | 1 |
| 2 nd Program May - 2018 Gram panchayat Sarpanch General Election | 2 | 1 |
| GP Bye Sarpanch Election Date- 26-09-2018 | 7 | 1, 2, 3 |
| Sarpanch Bye Election Date- 24-03-2019 | 13 | 1, 2, 3 |
| 146 Grampanchayt Sarpancha General Election Date 23-06-2019 | 6 | 1, 2, 3 |
| Sarpanch Bye Election Date 08-12-2019 | 19 | 1, 2, 3 |
| 34 Grampanchayat Sarpanch General Election Date 09-01-2020 | 5 | 1, 2, 3, 4 |
| Gram Panchayat Sarpanch General Election 07-10-2017 Fist Phase | 2 | 1, 2 |

- **Programmes without a date.** 823 seats are in programmes whose name prints no full
  date (9 with no year); 34 of them share district, taluka, GP and
  year with another such seat.
- **Shared place names.** 6 seat rows have place names that normalise to one
  key within a programme; counting rows are not attached to them.
- **Spelling twins.** [`checks/alias_review.csv`](checks/alias_review.csv) lists 9 seats found
  only in counting reports whose name is close to a Ward-Seat seat of the same programme
  and district. They are not merged.
- **Ties and no-vote contests.** 19 contests print two candidates at rank 1;
  1,277 contests show 0 votes on every row; 20 seats have a tie for
  second place.

## Checks

Generated by `make checks`. An `external` check compares with a record outside the release; an
`internal` one shows the release agrees with its own sources. `info` reports a count.
[`checks/hand_check.csv`](checks/hand_check.csv) lists 30 seeded-random rows for a person to compare with
the source file; its `verdict` column is filled in by hand.

| Check | Appeals to | Status | Result |
|---|---|---|---|
| `row_accounting` | internal | pass | 106 of 106 committed source files balance: sarpanch rows recounted from each file = released + evidence-only (winner reports) + dropped. |
| `provenance` | internal | pass | 86,558 rows and 12,956 winner rows reopened at source_path and row: 0 hash, 0 value, 0 original-row and 0 winner mismatches. |
| `keys` | internal | pass | candidate rows unique on source_path + source_row_number; seat_event_id unique; every seat has a source_path; every contest_id on a seat exists among the candidates. |
| `column_names` | internal | pass | central docs/naming.md rules: 0 violations in both tables. |
| `allowed_values` | internal | pass | values outside the master's enums: none. |
| `reservation_ward_seat_vs_counting` | internal | info | Seats where both the Ward-Seat report and the counting file print a reservation code: 16,892; they differ on 0. |
| `winner_vs_sec_winner_report` | external | info | SEC winner reports (608 and 1165 programmes) name the same winner as rules W1 and W3 for 1,692 of 1,692 seats they cover. |
| `women_share_by_category` | external | info | Share of seats reserved for women within each category: BC 50.2%, NONE 49.5%, SC 50.7%, ST 51.7%. |
