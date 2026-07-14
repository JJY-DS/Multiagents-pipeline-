"""
Integration tests running `compute_dormancy` (and the CLI entrypoint)
against the real fixture CSVs under `python/fixtures/`.

The fixtures encode twelve named boundary/scenario accounts (ACC001
through ACC012) chosen to exercise every dormancy rule at once:
individual/joint accounts, stale/fresh logins, transactions in each of
the three transaction tables, and accounts opened inside/outside the
2-month exclusion window. `python/fixtures/expected_dormancy_flags.csv`
is the hand-authored golden output for `as_of_date="2026-07-06"`.
"""
import os

import pandas as pd
import pytest

from dormancy import cli
from dormancy.core import compute_dormancy

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")

# The golden expected_dormancy_flags.csv was generated with this reference
# date -- see the module docstring in dormancy/cli.py for the same example
# invocation. All boundary accounts (ACC009-ACC012) are only correctly
# explained relative to this specific as_of_date.
AS_OF_DATE = "2026-07-06"


def _fixture_path(filename: str) -> str:
    return os.path.join(FIXTURES_DIR, filename)


@pytest.fixture
def loaded_fixtures():
    """Load the four source CSV tables as DataFrames."""
    accounts_df = pd.read_csv(_fixture_path("accounts.csv"))
    core_tx_df = pd.read_csv(_fixture_path("core_transactions.csv"))
    trading_tx_df = pd.read_csv(_fixture_path("trading_transactions.csv"))
    digital_df = pd.read_csv(_fixture_path("digital_payments.csv"))
    return accounts_df, core_tx_df, trading_tx_df, digital_df


def _sorted_reset(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Sort by `by` and reset the index for order-independent comparison."""
    return df.sort_values(by).reset_index(drop=True)


class TestComputeDormancyAgainstFixtures:
    def test_output_matches_expected_dormancy_flags_exactly(self, loaded_fixtures):
        accounts_df, core_tx_df, trading_tx_df, digital_df = loaded_fixtures

        output_df, _excluded_df = compute_dormancy(
            accounts_df, core_tx_df, trading_tx_df, digital_df, as_of_date=AS_OF_DATE
        )

        expected_df = pd.read_csv(_fixture_path("expected_dormancy_flags.csv"))

        # Compare via pandas DataFrame equality after sorting/reindexing
        # rather than a raw CSV text/byte diff -- a freshly written CSV
        # and a hand-authored golden file can legitimately differ in
        # line-ending style (CRLF vs LF) without representing a real
        # data difference.
        actual_sorted = _sorted_reset(output_df, "account_id")
        expected_sorted = _sorted_reset(expected_df, "account_id")

        # Normalize dtype: an empty/parsed CSV column and a freshly
        # computed int column can differ in dtype (e.g. int64 vs object)
        # without being a meaningful difference for this comparison.
        actual_sorted["dormancy"] = actual_sorted["dormancy"].astype(int)
        expected_sorted["dormancy"] = expected_sorted["dormancy"].astype(int)

        pd.testing.assert_frame_equal(actual_sorted, expected_sorted)

    def test_excluded_accounts_match_opened_within_2_months(self, loaded_fixtures):
        accounts_df, core_tx_df, trading_tx_df, digital_df = loaded_fixtures

        _output_df, excluded_df = compute_dormancy(
            accounts_df, core_tx_df, trading_tx_df, digital_df, as_of_date=AS_OF_DATE
        )

        expected_excluded_df = pd.DataFrame(
            {
                "account_id": ["ACC010", "ACC011"],
                "reason": ["opened_within_2_months", "opened_within_2_months"],
            }
        )

        actual_sorted = _sorted_reset(excluded_df, "account_id")
        expected_sorted = _sorted_reset(expected_excluded_df, "account_id")

        pd.testing.assert_frame_equal(actual_sorted, expected_sorted)

    def test_evaluated_and_excluded_accounts_partition_all_accounts(
        self, loaded_fixtures
    ):
        # Sanity check: every account in accounts.csv ends up in exactly
        # one of output_df or excluded_df, with no accounts lost/duplicated
        # (this fixture set has no duplicate account_id, unlike the
        # synthetic duplicate-id test in test_core.py).
        accounts_df, core_tx_df, trading_tx_df, digital_df = loaded_fixtures

        output_df, excluded_df = compute_dormancy(
            accounts_df, core_tx_df, trading_tx_df, digital_df, as_of_date=AS_OF_DATE
        )

        all_ids = set(accounts_df["account_id"])
        evaluated_ids = set(output_df["account_id"])
        excluded_ids = set(excluded_df["account_id"])

        assert evaluated_ids | excluded_ids == all_ids
        assert evaluated_ids & excluded_ids == set()
        assert len(output_df) + len(excluded_df) == len(accounts_df)


class TestCliSmoke:
    def test_cli_main_writes_expected_output_csvs(self, tmp_path):
        output_csv = tmp_path / "dormancy_flags.csv"
        excluded_csv = tmp_path / "excluded_accounts.csv"

        argv = [
            "--accounts-csv",
            _fixture_path("accounts.csv"),
            "--core-tx-csv",
            _fixture_path("core_transactions.csv"),
            "--trading-tx-csv",
            _fixture_path("trading_transactions.csv"),
            "--digital-payments-csv",
            _fixture_path("digital_payments.csv"),
            "--as-of-date",
            AS_OF_DATE,
            "--output-csv",
            str(output_csv),
            "--excluded-csv",
            str(excluded_csv),
        ]

        cli.main(argv)

        assert output_csv.exists()
        assert excluded_csv.exists()

        actual_df = _sorted_reset(pd.read_csv(output_csv), "account_id")
        expected_df = _sorted_reset(
            pd.read_csv(_fixture_path("expected_dormancy_flags.csv")), "account_id"
        )
        actual_df["dormancy"] = actual_df["dormancy"].astype(int)
        expected_df["dormancy"] = expected_df["dormancy"].astype(int)

        pd.testing.assert_frame_equal(actual_df, expected_df)

        excluded_df = pd.read_csv(excluded_csv)
        assert sorted(excluded_df["account_id"]) == ["ACC010", "ACC011"]
        assert set(excluded_df["reason"]) == {"opened_within_2_months"}
