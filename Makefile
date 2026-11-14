PY = .venv/bin/python
RUFF = .venv/bin/ruff

.PHONY: sync admit collect data checks manifest readme lint test check

sync:
	uv sync --frozen --all-groups

# Local only: reads the depositor's original SEC downloads (not in this repository) and writes
# data/raw/, data/extracted/ and the logs. Usage:
#   make admit SOURCES='--source NAME=/path/to/folder --source NAME=/path/to/folder ...'
admit:
	$(PY) -m local_elections_maharashtra.collect.admit $(SOURCES)

# The files were downloaded by hand from the SEC portal; there is nothing to fetch.
collect:
	@echo "Sources were downloaded manually from the SEC portal; see data/README.md. Nothing to collect."

data:
	$(PY) -m local_elections_maharashtra.build.release
	$(PY) -m local_elections_maharashtra.build.rosters
	$(MAKE) checks readme manifest

checks:
	$(PY) -m local_elections_maharashtra.build.checks

manifest:
	$(PY) -m local_elections_maharashtra.build.manifest write

readme:
	$(PY) -m local_elections_maharashtra.build.readme
	$(PY) -m local_elections_maharashtra.build.readme_rosters

lint:
	$(RUFF) check .

test:
	$(PY) -m pytest -q

check: lint test
	$(PY) -m local_elections_maharashtra.build.manifest verify
