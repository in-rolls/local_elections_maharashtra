"""data/MANIFEST.json: sha256, size and (for tables) rows and schema of every file under data/.

    python -m local_elections_maharashtra.build.manifest write
    python -m local_elections_maharashtra.build.manifest verify   # exits non-zero on any mismatch
"""

import hashlib
import json
import sys

import pandas as pd
import pyarrow.parquet as pq

from local_elections_maharashtra.paths import DATA, ROOT

MANIFEST = DATA / "MANIFEST.json"


def describe(path):
    data = path.read_bytes()
    entry = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    if path.suffix == ".parquet":
        schema = pq.read_schema(path)
        entry["rows"] = pq.ParquetFile(path).metadata.num_rows
        entry["schema"] = {f.name: str(f.type) for f in schema}
    elif path.suffix == ".csv":
        entry["rows"] = len(pd.read_csv(path, dtype=str, keep_default_na=False))
    return entry


def files():
    return sorted(p for p in DATA.rglob("*") if p.is_file() and p != MANIFEST and not p.name.startswith("."))


def write():
    manifest = {p.relative_to(ROOT).as_posix(): describe(p) for p in files()}
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"MANIFEST.json: {len(manifest)} files")


def verify() -> int:
    recorded = json.loads(MANIFEST.read_text())
    present = {p.relative_to(ROOT).as_posix() for p in files()}
    problems = [f"missing: {k}" for k in sorted(set(recorded) - present)]
    problems += [f"not in manifest: {k}" for k in sorted(present - set(recorded))]
    for key in sorted(set(recorded) & present):
        digest = hashlib.sha256((ROOT / key).read_bytes()).hexdigest()
        if digest != recorded[key]["sha256"]:
            problems.append(f"changed: {key}")
    print("\n".join(problems) or f"MANIFEST.json verified: {len(recorded)} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(write() if sys.argv[1:] == ["write"] else verify())
