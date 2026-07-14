"""
Unit tests for `dormancy.core`: `to_timestamp`, `is_stale`,
`evaluate_login_staleness`, and `compute_dormancy`.

These tests use small, synthetic DataFrames constructed in-line rather
than the CSV fixtures under `python/fixtures/` -- the fixture-driven
end-to-end scenario lives in `test_pipeline.py`. Keeping unit tests
synthetic makes each boundary condition explicit and independent of
fixture file contents.
"""
import datetime
from collections import namedtuple

import pandas as pd
import pytest

from dormancy.core import (
    compute_dormancy,
    evaluate_login_staleness,
    is_stale,
    to_timestamp,
)

ACCOUNTS_COLUMNS = [
    "account_id",
    "account_type",
    "primary_customer_id",
    "joint_customer_id",
    "account_open_date",
    "primary_last_login_date",
    "joint_last_login_date",
]


def make_accounts_df(rows):
    """Build an accounts DataFrame with the full expected column set."""
    return pd.DataFrame(rows, columns=ACCOUNTS_COLUMNS)


def make_tx_df(account_ids=()):
    """Build a minimal transaction DataFrame with just an account_id column."""
    return pd.DataFrame({"account_id": list(account_ids)}, columns=["account_id"])


# A namedtuple stand-in for the row objects `DataFrame.itertuples(index=False)`
# yields, matching what `evaluate_login_staleness` is documented to accept.
Row = namedtuple(
    "Row", ["account_type", "primary_last_login_date", "joint_last_login_date"]
)


# ---------------------------------------------------------------------------
# to_timestamp
# ---------------------------------------------------------------------------


class TestToTimestamp:
    def test_to_timestamp_with_none_returns_none(self):
        assert to_timestamp(None) is None

    def test_to_timestamp_with_empty_string_returns_none(self):
        assert to_timestamp("") is None

    def test_to_timestamp_with_whitespace_only_string_returns_none(self):
        assert to_timestamp("   ") is None

    def test_to_timestamp_with_nan_returns_none(self):
        assert to_timestamp(float("nan")) is None

    def test_to_timestamp_with_nat_returns_none(self):
        assert to_timestamp(pd.NaT) is None

    def test_to_timestamp_with_iso_string_returns_timestamp(self):
        assert to_timestamp("2020-01-01") == pd.Timestamp("2020-01-01")

    def test_to_timestamp_with_existing_timestamp_returns_equal_timestamp(self):
        value = pd.Timestamp("2020-01-01")
        assert to_timestamp(value) == value

    def test_to_timestamp_with_datetime_date_returns_timestamp(self):
        assert to_timestamp(datetime.date(2020, 1, 1)) == pd.Timestamp("2020-01-01")


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------


class TestIsStale:
    cutoff = pd.Timestamp("2025-06-06")

    def test_is_stale_with_null_login_date_is_true(self):
        assert is_stale(None, self.cutoff) is True

    def test_is_stale_with_login_exactly_on_cutoff_is_false(self):
        # The single most important boundary in this module: the cutoff
        # itself is EXCLUSIVE, so an exact-match login is NOT stale.
        assert is_stale(self.cutoff, self.cutoff) is False

    def test_is_stale_with_login_one_day_before_cutoff_is_true(self):
        one_day_before = self.cutoff - pd.Timedelta(days=1)
        assert is_stale(one_day_before, self.cutoff) is True

    def test_is_stale_with_login_one_day_after_cutoff_is_false(self):
        one_day_after = self.cutoff + pd.Timedelta(days=1)
        assert is_stale(one_day_after, self.cutoff) is False


# ---------------------------------------------------------------------------
# evaluate_login_staleness
# ---------------------------------------------------------------------------


class TestEvaluateLoginStaleness:
    login_cutoff = pd.Timestamp("2025-06-06")
    stale_date = "2020-01-01"
    fresh_date = "2026-06-01"

    def test_individual_account_with_stale_login_is_dormant(self):
        row = Row("individual", self.stale_date, None)
        assert evaluate_login_staleness(row, self.login_cutoff) == 1

    def test_individual_account_with_fresh_login_is_not_dormant(self):
        row = Row("individual", self.fresh_date, None)
        assert evaluate_login_staleness(row, self.login_cutoff) == 0

    def test_joint_account_with_both_logins_stale_is_dormant(self):
        row = Row("joint", self.stale_date, self.stale_date)
        assert evaluate_login_staleness(row, self.login_cutoff) == 1

    def test_joint_account_with_primary_stale_joint_fresh_is_not_dormant(self):
        row = Row("joint", self.stale_date, self.fresh_date)
        assert evaluate_login_staleness(row, self.login_cutoff) == 0

    def test_joint_account_with_primary_fresh_joint_stale_is_not_dormant(self):
        row = Row("joint", self.fresh_date, self.stale_date)
        assert evaluate_login_staleness(row, self.login_cutoff) == 0

    def test_joint_account_with_both_logins_fresh_is_not_dormant(self):
        row = Row("joint", self.fresh_date, self.fresh_date)
        assert evaluate_login_staleness(row, self.login_cutoff) == 0

    def test_unknown_account_type_raises_value_error_mentioning_bad_value(self):
        row = Row("corporate", self.stale_date, None)
        with pytest.raises(ValueError, match="corporate"):
            evaluate_login_staleness(row, self.login_cutoff)


# ---------------------------------------------------------------------------
# compute_dormancy
# ---------------------------------------------------------------------------


class TestComputeDormancy:
    # Fixed reference date used across these unit tests for readable,
    # reproducible boundary arithmetic:
    #   exclusion_cutoff = 2026-07-06 - 2 months  = 2026-05-06
    #   login_cutoff     = 2026-07-06 - 13 months = 2025-06-06
    AS_OF_DATE = "2026-07-06"
    EXCLUSION_CUTOFF = "2026-05-06"
    STALE_LOGIN = "2020-01-01"
    FRESH_LOGIN = "2026-06-01"
    OLD_OPEN_DATE = "2020-01-01"

    def test_zero_transactions_and_stale_login_is_dormant(self):
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "individual",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert excluded_df.empty
        assert output_df.loc[output_df["account_id"] == "ACCX", "dormancy"].iloc[0] == 1

    @pytest.mark.parametrize("tx_table", ["core", "trading", "digital"])
    def test_transaction_in_a_single_table_prevents_dormancy_regardless_of_login(
        self, tx_table
    ):
        # A stale login would normally flag this account dormant -- but a
        # transaction in ANY ONE of the three tables must override that.
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "individual",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        core_tx_df = make_tx_df(["ACCX"] if tx_table == "core" else [])
        trading_tx_df = make_tx_df(["ACCX"] if tx_table == "trading" else [])
        digital_df = make_tx_df(["ACCX"] if tx_table == "digital" else [])

        output_df, excluded_df = compute_dormancy(
            accounts_df,
            core_tx_df,
            trading_tx_df,
            digital_df,
            as_of_date=self.AS_OF_DATE,
        )
        assert excluded_df.empty
        assert output_df.loc[output_df["account_id"] == "ACCX", "dormancy"].iloc[0] == 0

    def test_account_opened_exactly_on_exclusion_boundary_is_excluded(self):
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "individual",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": self.EXCLUSION_CUTOFF,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert output_df.empty
        assert list(excluded_df["account_id"]) == ["ACCX"]
        assert list(excluded_df["reason"]) == ["opened_within_2_months"]

    def test_account_opened_one_day_before_exclusion_boundary_is_not_excluded(self):
        # One day *before* the cutoff means opened slightly earlier
        # (less recently), so it should fall OUTSIDE the exclusion window.
        open_date = pd.Timestamp(self.EXCLUSION_CUTOFF) - pd.Timedelta(days=1)
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "individual",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": open_date.strftime("%Y-%m-%d"),
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert excluded_df.empty
        assert list(output_df["account_id"]) == ["ACCX"]

    def test_account_opened_one_day_after_exclusion_boundary_is_excluded(self):
        open_date = pd.Timestamp(self.EXCLUSION_CUTOFF) + pd.Timedelta(days=1)
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "individual",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": open_date.strftime("%Y-%m-%d"),
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert output_df.empty
        assert list(excluded_df["account_id"]) == ["ACCX"]

    def test_empty_accounts_df_returns_empty_output_with_correct_columns(self):
        empty_accounts_df = make_accounts_df([])
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            empty_accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert list(output_df.columns) == ["account_id", "dormancy"]
        assert list(excluded_df.columns) == ["account_id", "reason"]
        assert output_df.empty
        assert excluded_df.empty

    def test_empty_transaction_tables_fall_through_to_login_staleness(self):
        # With all three transaction tables empty, no account can possibly
        # be marked non-dormant via the transaction check -- dormancy must
        # be decided purely by login recency.
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "STALE_ACC",
                    "account_type": "individual",
                    "primary_customer_id": "CUST1",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                },
                {
                    "account_id": "FRESH_ACC",
                    "account_type": "individual",
                    "primary_customer_id": "CUST2",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.FRESH_LOGIN,
                    "joint_last_login_date": None,
                },
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert excluded_df.empty
        result = output_df.set_index("account_id")["dormancy"]
        assert result["STALE_ACC"] == 1
        assert result["FRESH_ACC"] == 0

    def test_duplicate_account_id_produces_two_output_rows_known_issue(self):
        # KNOWN ISSUE (from code review): compute_dormancy does not
        # validate/deduplicate on account_id. A duplicated account_id in
        # accounts_df currently produces one output row per input row,
        # rather than raising or collapsing to a single row. This test
        # documents the CURRENT behavior -- it is not asserting this is
        # correct or desired long-term behavior, just pinning it so a
        # future fix is a deliberate, visible change to this test.
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "DUP1",
                    "account_type": "individual",
                    "primary_customer_id": "CUST1",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                },
                {
                    "account_id": "DUP1",
                    "account_type": "individual",
                    "primary_customer_id": "CUST1",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.FRESH_LOGIN,
                    "joint_last_login_date": None,
                },
            ]
        )
        empty_tx = make_tx_df()
        output_df, excluded_df = compute_dormancy(
            accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
        )
        assert excluded_df.empty
        assert len(output_df) == 2
        assert list(output_df["account_id"]) == ["DUP1", "DUP1"]
        assert list(output_df["dormancy"]) == [1, 0]

    def test_unrecognized_account_type_raises_value_error_from_compute_dormancy(self):
        accounts_df = make_accounts_df(
            [
                {
                    "account_id": "ACCX",
                    "account_type": "corporate",
                    "primary_customer_id": "CUSTX",
                    "joint_customer_id": None,
                    "account_open_date": self.OLD_OPEN_DATE,
                    "primary_last_login_date": self.STALE_LOGIN,
                    "joint_last_login_date": None,
                }
            ]
        )
        empty_tx = make_tx_df()
        with pytest.raises(ValueError, match="corporate"):
            compute_dormancy(
                accounts_df, empty_tx, empty_tx, empty_tx, as_of_date=self.AS_OF_DATE
            )
