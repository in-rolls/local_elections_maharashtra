# RTI sarpanch reservation rosters

`release/sarpanch_rti_reservations.parquet`: one row per gram panchayat (GP) per reservation round,
giving the category the sarpanch seat was reserved for. 13,370 rows, 3,094 GPs in
35 talukas of 9 districts, rounds 1995 to 2020. The source is
the depositor's own Right to Information (RTI) requests to tahsil and district offices. The SEC's
reservations for the 2017-2023 elections are in `sarpanch_results` and are not repeated here.

| District | Talukas | GPs | GP-rounds | Rounds |
|---|---|---|---|---|
| Chandrapur | 2 | 108 | 400 | 2005-2020 |
| Dhule | 1 | 131 | 783 | 1995-2020 |
| Gondia | 2 | 117 | 412 | 2005-2020 |
| Kolhapur | 2 | 138 | 547 | 1995-2020 |
| Nanded | 2 | 95 | 286 | 2005-2020 |
| Palghar | 8 | 463 | 1,201 | 2010-2020 |
| Parbhani | 1 | 118 | 335 | 2010-2020 |
| Raigad | 6 | 399 | 906 | 2005-2020 |
| Satara | 11 | 1,387 | 8,500 | 1995-2020 |

| Round | GP-rounds | With a category |
|---|---|---|
| 1995 | 1,532 | 1,532 |
| 2000 | 1,535 | 1,535 |
| 2005 | 1,903 | 1,897 |
| 2010 | 2,598 | 2,589 |
| 2015 | 2,911 | 2,908 |
| 2020 | 2,891 | 2,891 |

## Sources

The RTI replies are scanned PDFs and photos: printed rosters (one row per GP, one column per
round), category lists, draw orders and draw minutes, and handwritten registers. They are
listed in [`manual/rti_rosters/documents.csv`](manual/rti_rosters/documents.csv) with their size and
sha256. The scans are not in this repository: several name private people (RTI applicants,
attendees at the draws, the children who drew the chits, phone numbers).

## How the data were made

1. **Typed workbook.** Research assistants read the RTI replies and typed the reservations into a
   workbook whose rows come from the SEC's list of GPs and term-expiry dates
   ([`manual/rti_rosters/workbook_rows.csv`](manual/rti_rosters/workbook_rows.csv), 3,014 rows used here). It has four
   round columns (2005-10, 2010-15, 2015-20, 2021-25), no 1995 or 2000 columns, and no page
   reference per row.
2. **Readings of the scans.** Every page carrying sarpanch reservations was then read again, from
   the scan, by AI models (Anthropic's Claude), each reader seeing only the scan. In Satara district
   every page was read twice, independently. Elsewhere a reading that agrees with the typed
   workbook counts as a check; a second independent reading was made wherever the reading and
   the workbook differ, wherever the workbook has no value, on every handwritten or degraded page,
   and on a random tenth of the pages of each district. Draw orders and minutes were read for the
   final category of each GP in each round, and their totals were checked against the counts the
   documents print. All readings, per document and page, are in
   [`manual/rti_rosters/document_readings.csv`](manual/rti_rosters/document_readings.csv).
3. **Settling each cell.** A value is released when the readings agree with each other and either
   agree with the typed value, or (where the workbook has none) two readings or one reading and
   the SEC's published reservation agree. A typed value is corrected only where two readings agree
   against it and the page was viewed, the SEC agrees with the readings, or the document's printed
   counts reconcile. Every decision is in [`manual/rti_rosters/settled_cells.csv`](manual/rti_rosters/settled_cells.csv), every
   page adjudication in [`manual/rti_rosters/adjudications.csv`](manual/rti_rosters/adjudications.csv), and every GP pairing made by
   hand in [`manual/rti_rosters/pairings.csv`](manual/rti_rosters/pairings.csv). Cells that do not settle are released without a
   value.
4. **Superseded draws.** Where a later draw replaced an earlier one in the same round (a re-draw
   after a court order, or the 2011 re-draws that raised women's seats to 50%), only the final draw
   is released. The draw events are in [`manual/rti_rosters/superseded_draws.csv`](manual/rti_rosters/superseded_draws.csv).

## How each value was checked

| `document_check` | Meaning | Rows |
|---|---|---|
| `two_readings` | two independent readings of the scan agree | 10,944 |
| `reading_agrees_workbook` | one reading of the scan agrees with the typed workbook | 1,612 |
| `not_read` | typed value kept; no reading covers this cell | 415 |
| `corrected` | the typed value was corrected from the document (see `correction_reason`, `correction_source`) | 279 |
| `reading_and_sec` | one reading of the scan agrees with the SEC's published reservation | 72 |
| `page_viewed` | readings settled by viewing the page | 22 |
| `document_prints_no_category` | the document prints no category for this round | 13 |
| `one_reading_degraded_page` | typed value kept; one reading on a degraded page agrees, no second reading | 8 |
| `unsettled` | released without a value: the readings or the documents disagree | 5 |

## Blind check

A random sample of 150 released cells (seed 20261114), stratified by how each value was
checked (corrected values 30, handwritten pages 30, one reading agreeing with the workbook 20, values from the readings only 30, SEC-backed or page-viewed 10, two readings 30), was read again from the scans by fresh AI
readers who saw no released, typed or earlier values. 141 agree in full; 9 agree on
the caste category where the pages shown carry no women's draw; 0 disagree. With no error in 150 cells, the error rate is below 2.0% at 95% confidence.
The sample and every answer are in [`checks/roster_spot_check.csv`](checks/roster_spot_check.csv). The check was made by AI
readers, not by a person.

Where the SEC's published reservation for the 2017-2023 elections can be matched to a GP and
round, the released value agrees with it in 1,866 of 1,877 cells.

## Columns

36 columns.

| Column | Meaning |
|---|---|
| `district`, `block`, `gram_panchayat` | District, taluka and GP, whitespace tidied; typed values in the `*_raw` columns. For GPs not in the workbook, the name as the document prints it (Devanagari, `script` = `devanagari`) |
| `gram_panchayat_devanagari` | The GP's Devanagari name, from the workbook or the document |
| `tier`, `tier_local` | `gp_head`, `sarpanch` |
| `roster_year` | The reservation round as a year: 1995, 2000, 2005, 2010, 2015, 2020. No election year is assigned |
| `workbook_column`, `roster_year_basis` | The workbook column the value was typed in (null for values from the readings only); `workbook_column` or `document` |
| `round_scope` | `partial` where the document lists only some categories for the round (values only for the GPs it lists), else `all` |
| `reserved_raw` | The value as typed in the workbook (after any correction), or as read from the document |
| `reserved_caste_local`, `reserved_caste` | `GEN`, `BCC`, `SC`, `ST`; pooled `NONE`, `BC`, `SC`, `ST`. A property of the seat |
| `reserved_woman` | 1 women's seat, 0 not; null where the document gives the caste category only |
| `reserved_label`, `reserved_caste_scheme` | Pooled label (e.g. `SC Woman`); `sc_st_obc` |
| `workbook_value_raw` | The value the research assistants typed, before any correction |
| `transcription_corrected`, `correction_reason`, `correction_source` | Whether the typed value was corrected; why; the document and page |
| `document_check`, `document_check_detail` | How the released value was checked against the RTI document (see *How each value was checked*) |
| `workbook_remarks` | The research assistants' remark on the row, if any |
| `transcription` | `workbook_2023` (typed by research assistants) or `rti_reading_2026` (from the scan readings only) |
| `source_path`, `source_row_number`, `source_sha256`, `original_row_number` | The committed file and row the value comes from; its hash; the row in the original workbook |
| `rti_documents`, `rti_document_kind`, `provenance_level` | The RTI replies for this taluka (see `manual/rti_rosters/documents.csv`); their kind; `document` |

## What was changed from the sources

Every rule is counted in [`checks/roster_changes.csv`](checks/roster_changes.csv); typed spellings and how each is read
are in [`checks/roster_vocabulary.csv`](checks/roster_vocabulary.csv).

- 279 typed values are corrected from the documents, in 48 groups
  ([`manual/corrections.csv`](manual/corrections.csv): old value, new value, reason, document and page). The typed
  value stays in `workbook_value_raw`.
- 3,233 values come from the readings only (rule T5).
- 3 workbook rows are withheld because they duplicate another row
  ([`manual/rti_rosters/withheld_workbook_rows.csv`](manual/rti_rosters/withheld_workbook_rows.csv)).
- 5 typed values are released without a category because the readings or the documents
  disagree with them, and 191 further GP-rounds from the readings are not released
  ([`checks/roster_unsettled.csv`](checks/roster_unsettled.csv)).

## Known issues

- Readings and the blind check were made by AI models. The corrections record this in their
  `reviewer` field.
- 119 values give the caste category without the women's reservation (`reserved_woman` null): lists that
  name the caste only, and Panvel's 2010-15 table, which prints no women's marks.
- 777 values come from rounds the document lists only in part (`round_scope` = `partial`); GPs the
  list does not name have no row for that round.
- Tala, 2010-15: the 4 November 2011 re-draw lists five GPs as women's seats, while the 2020 minutes
  say two of them held no women's seat in 2010-15 or 2015-20. Whether the re-draw took effect is
  not settled; the five cells are released without a category. The 2011 re-draws of Dharmabad and
  Parbhani are released as final; no document here contradicts them.
- 415 typed values have no reading behind them (`not_read`): the RTI pages for those
  cells were not found among the replies held.
- Mokhada's "previous term" columns print no years; they are not released.
- GPs that are not in the workbook carry the name the document prints, in Devanagari.

## Files

| File | What it holds |
|---|---|
| `manual/rti_rosters/workbook_rows.csv` | the typed workbook rows, unchanged |
| `manual/corrections.csv` | every correction to a typed value |
| `manual/rti_rosters/settled_cells.csv` | one row per GP and round: every reading, the verdict and its basis |
| `manual/rti_rosters/document_readings.csv` | the readings per document and page |
| `manual/rti_rosters/adjudications.csv` | every disagreement settled on the page |
| `manual/rti_rosters/pairings.csv` | GP names paired to workbook rows by hand or by rule |
| `manual/rti_rosters/withheld_workbook_rows.csv` | duplicate workbook rows not released |
| `manual/rti_rosters/superseded_draws.csv` | draws replaced by a later draw |
| `manual/rti_rosters/documents.csv` | the RTI replies: file name, kind, size, sha256 |
| `checks/roster_*.csv` | ledgers: changes, vocabulary, unsettled cells, the blind check |
