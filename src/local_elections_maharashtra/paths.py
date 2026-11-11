"""Every folder of the repository, named once."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
EXTRACTED = DATA / "extracted"
MANUAL = DATA / "manual"
RELEASE = DATA / "release"
CHECKS = DATA / "checks"
SEARCH_LOG = DATA / "search_log"
FETCH_LOG = RAW / "fetch_log.csv"
EXTRACTS = EXTRACTED / "sarpanch_extracts.csv"
