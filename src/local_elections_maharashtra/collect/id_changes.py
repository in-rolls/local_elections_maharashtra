"""Old and new ids of rows whose ``seat_event_id`` or ``contest_id`` changed (run once, by the depositor).

On 24 November 2026 both ids changed definition: they are built from ``original_sha256`` and
``original_row_number`` (the SEC download as received and the row's place in it) instead of
``source_path`` and ``source_row_number`` (the row's place in the committed file), so that admitting
more rows from a download no longer renumbers the rest, and no new id repeats an old one. This writes every changed pair, matching rows of the
release at ``--old-commit`` with the current release by ``source_path`` and ``original_row_number``.

usage: python -m local_elections_maharashtra.collect.id_changes --old-commit COMMIT --out data/checks/id_changes_YYYY-MM-DD.csv
"""

import argparse
import io
import subprocess
from pathlib import Path

import pandas as pd

from local_elections_maharashtra.paths import RELEASE, ROOT


def old_table(commit: str, name: str) -> pd.DataFrame:
    data = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:data/release/{name}"], capture_output=True, check=True).stdout
    return pd.read_parquet(io.BytesIO(data))


def main(commit: str, out: Path) -> None:
    key = ["source_path", "original_row_number"]
    rows = []
    for name, column in (("sarpanch_results.parquet", "seat_event_id"), ("sarpanch_results.parquet", "contest_id"),
                         ("sarpanch_candidates.parquet", "contest_id")):
        old, new = old_table(commit, name), pd.read_parquet(RELEASE / name)
        m = old[[*key, column]].merge(new[[*key, column]], on=key, suffixes=("_old", "_new"))
        m = m[m[f"{column}_old"].notna() & (m[f"{column}_old"] != m[f"{column}_new"])]
        pairs = m[[f"{column}_old", f"{column}_new"]].drop_duplicates()
        rows.append(pairs.rename(columns={f"{column}_old": "old_id", f"{column}_new": "new_id"}).assign(id_column=column))
    t = pd.concat(rows).drop_duplicates(["id_column", "old_id", "new_id"])
    assert not t.duplicated(["id_column", "old_id"]).any(), "an old id maps to two new ids"
    for column in ("seat_event_id", "contest_id"):
        part = t[t["id_column"] == column]
        assert not set(part["new_id"]) & set(part["old_id"]), f"a new {column} repeats an old one: the mapping would chain"
    t[["id_column", "old_id", "new_id"]].sort_values(["id_column", "old_id"]).to_csv(out, index=False)
    print(t["id_column"].value_counts().to_dict())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old-commit", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    main(args.old_commit, args.out)
