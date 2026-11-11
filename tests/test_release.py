"""The published tables keep their contract. Skipped until `make data` has run."""

import pandas as pd
import pytest

from local_elections_maharashtra.build.checks import naming_violations
from local_elections_maharashtra.build.release import CANDIDATE_COLUMNS, RESULT_COLUMNS
from local_elections_maharashtra.paths import RELEASE

CAND, RES = RELEASE / "sarpanch_candidates.parquet", RELEASE / "sarpanch_results.parquet"
pytestmark = pytest.mark.skipif(not (CAND.exists() and RES.exists()), reason="release not built")


@pytest.fixture(scope="module")
def tables():
    return pd.read_parquet(CAND), pd.read_parquet(RES)


def test_columns_and_names(tables):
    cand, res = tables
    assert list(cand.columns) == CANDIDATE_COLUMNS and list(res.columns) == RESULT_COLUMNS
    assert naming_violations(cand.columns) == [] and naming_violations(res.columns) == []


def test_keys(tables):
    cand, res = tables
    assert not cand.duplicated(["source_path", "source_row_number"]).any()
    assert not res["seat_event_id"].duplicated().any()


def test_2017_names_are_missing_and_kept_raw(tables):
    cand, _ = tables
    y = cand[cand["year"] == 2017]
    assert y["candidate_name"].isna().all() and (y["candidate_name_raw"].str.strip() == "NOTA").all()


def test_one_winner_per_contest_and_none_from_nota(tables):
    cand, res = tables
    elected = cand[cand["elected"].fillna(False)]
    assert not elected["contest_id"].duplicated().any()
    assert not elected["nota_tally"].fillna(False).any()
    assert res["winner"].notna().sum() == len(elected)


def test_reservation_is_a_seat_property(tables):
    _, res = tables
    coded = res["reserved_caste"].notna()
    assert set(res.loc[coded, "reserved_caste"]) <= {"SC", "ST", "BC", "NONE"}
    assert res.loc[coded, "reserved_woman"].isin([0, 1]).all()
