# Working on this data repository

This is a point-in-time data collection. Follow the [data-repository policy](https://github.com/soodoku/data-repos#maintenance-policy).

- Preserve sources, collection dates, provenance, schemas and reproducible parsing commands. Every committed source file is listed in `data/raw/fetch_log.csv` or `data/extracted/sarpanch_extracts.csv` with its sha256; never overwrite one.
- `make data` rebuilds every release table offline from `data/raw/`, `data/extracted/` and `data/manual/`. Run `make check` once when code, inputs or outputs change.
- `make admit` reads the original SEC downloads, which are not in this repository, and only the depositor can run it.
- Only sarpanch rows (ward number 999 in a sarpanch programme) are deposited. Never commit a file that also holds ward-member rows; commit its sarpanch-row extract instead.
- Every value that differs from its source cell keeps the printed value in a `*_raw` column and is counted in `data/checks/changes.csv`.
- Do not add blanket CI, recurring dependency checks, version matrices, Docker/VM checks, pre-commit, Preen or package-release scaffolding.
- Ask when source meaning is unclear. Never infer substantive data values to make a check pass; never infer a person's sex from a name.
