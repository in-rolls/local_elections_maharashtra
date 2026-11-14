# Maharashtra Sarpanch Elections, 2017-2023

[![Code license: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)

Maharashtra's gram panchayat head (sarpanch) elections from the State Election Commission's (SEC)
reports, October 2017 to December 2023: one row per sarpanch seat event with its reservation
and, where the SEC's counting report has it, its candidates, votes and winner. Every row points
to the committed file and row it was read from.

This is a sister repository of [in-rolls/local_elections](https://github.com/in-rolls/local_elections).
Column names follow that repository's pooled schema.

## Status: read this first

<!-- status:start -->

| | |
|---|---:|
| Sarpanch seat events (`sarpanch_results`) | 20,622 |
| from the SEC Ward-Seat Details reports | 20,608 |
| found only in SEC counting reports | 14 |
| with counting rows attached | 16,906 |
| winner named | 12,956 |
| Counting rows (`sarpanch_candidates`) | 65,950 in 16,907 contests |
| Election programmes | 54 (396 seats in by-elections) |

| Year | Seats | With counting rows | No counting rows | Shared place name | Winner named |
|---|---|---|---|---|---|
| 2017 | 5,235 | 3,898 | 1,335 | 2 | 0 |
| 2018 | 2,145 | 1,163 | 982 | 0 | 1,154 |
| 2019 | 1,342 | 628 | 710 | 4 | 622 |
| 2020 | 48 | 32 | 16 | 0 | 32 |
| 2022 | 9,491 | 9,171 | 320 | 0 | 9,141 |
| 2023 | 2,352 | 2,014 | 338 | 0 | 2,007 |
| no year in the programme name | 9 | 0 | 9 | 0 | 0 |

<!-- status:end -->

- **Sarpanch seats only.** Ward-member seats are not in this repository.
- **2017 has no candidate names.** Every 2017 counting row prints `NOTA` in the name column; the
  names are released as missing and no 2017 winner is named. Votes and ranks are kept.
- **No sarpanch rows for January 2021 or 4 August 2022.** The SEC reports hold none for those
  programmes; the depositor notes that in those rounds the sarpanch was chosen by the elected
  members rather than by voters.
- **Seats without results.** Many seats in the SEC's seat reports have no counting rows in these
  files; they keep their reservation and electors (`result_in_source` is false).

Sources, every column, what was changed from the sources, known issues and the checks are in
[data/README.md](data/README.md).

## Sarpanch reservation rosters, 1995-2020

A second table gives the category each GP's sarpanch seat was reserved for in each round from
1995 to 2020, from the depositor's RTI requests to tahsil and district offices. Research
assistants typed the replies into a workbook; every page was then read again from the scans by
AI models, the typed values were checked and corrected against those readings, and the rounds the
workbook lacks (1995, 2000) were added from them. How it was made, how each value was checked
and what is not settled are in [data/README_rti_rosters.md](data/README_rti_rosters.md).

<!-- rosters:start -->

| | |
|---|---:|
| GP-rounds (`sarpanch_rti_reservations`) | 13,370 |
| GPs / talukas / districts | 3,094 / 35 / 9 |
| Rounds | 1995, 2000, 2005, 2010, 2015, 2020 |
| Values checked against the scans | 12,942 |
| Typed values corrected from the documents | 279 |
| Values from the scan readings only (1995 and 2000 rounds, blank cells, GPs not typed) | 3,233 |
| Blind check of 150 random cells | 150 agree, 0 disagree |

<!-- rosters:end -->

## Data

| File | Each row is |
|---|---|
| [data/release/sarpanch_results.parquet](data/release/sarpanch_results.parquet) | a sarpanch seat in one SEC election programme: its reservation, electors and, where counted, winner and votes |
| [data/release/sarpanch_candidates.parquet](data/release/sarpanch_candidates.parquet) | a row of the SEC counting report: a candidate, or the NOTA count, with votes and rank |
| [data/release/sarpanch_rti_reservations.parquet](data/release/sarpanch_rti_reservations.parquet) | a GP in one reservation round (1995-2020): the category its sarpanch seat was reserved for, from RTI replies |

```python
import pandas as pd

seats = pd.read_parquet("data/release/sarpanch_results.parquet")
rows = pd.read_parquet("data/release/sarpanch_candidates.parquet")
seats.groupby(["year", "reserved_caste"])["reserved_woman"].mean()
contest = rows[rows["contest_id"] == seats["contest_id"].dropna().iloc[0]]
```

## Reproducing

```
make sync     # uv environment
make data     # rebuild data/release/ and data/checks/ offline from data/raw/, data/extracted/, data/manual/
make check    # lint, tests, and data/MANIFEST.json hashes
```

`make admit` wrote `data/raw/` and `data/extracted/` from the original SEC downloads, which are
not in this repository; only the depositor can run it.

## Citation

See [CITATION.cff](CITATION.cff). Please record the commit you used.
