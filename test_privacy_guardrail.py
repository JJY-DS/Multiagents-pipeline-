"""
Dedicated test for the privacy guardrail described in `dormancy/core.py`:
the primary output of `compute_dormancy` must never contain any column
beyond `account_id` / `dormancy`, even if the accounts table itself gains
extra (potentially sensitive/PII) columns.

Currently this guardrail is enforced with a bare `assert` inside
`compute_dormancy` rather than a dedicated exception type -- a known
review finding, not something this test suite modifies. Since the
current implementation only ever *builds* output_df from an explicit
`columns=["account_id", "dormancy"]` list (see compute_dormancy), extra
input columns are actually structurally prevented from leaking through
`itertuples`-based row access; this test exists to pin that behavior
down explicitly and catch any future refactor that changes how
output_df's columns are constructed.
"""
import os

import pandas as pd

from dormancy.core import ALLOWED_OUTPUT_COLUMNS, compute_dormancy

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")
AS_OF_DATE = "2026-07-06"


def _fixture_path(filename: str) -> str:
    return os.path.join(FIXTURES_DIR, filename)


def test_extra_column_on_accounts_df_does_not_leak_into_output():
    accounts_df = pd.read_csv(_fixture_path("accounts.csv")).copy()

    # Inject a synthetic PII-like column that would never legitimately
    # belong in the dormancy output.
    accounts_df["customer_name"] = "Jane Doe"

    core_tx_df = pd.read_csv(_fixture_path("core_transactions.csv"))
    trading_tx_df = pd.read_csv(_fixture_path("trading_transactions.csv"))
    digital_df = pd.read_csv(_fixture_path("digital_payments.csv"))

    output_df, _excluded_df = compute_dormancy(
        accounts_df, core_tx_df, trading_tx_df, digital_df, as_of_date=AS_OF_DATE
    )

    assert "customer_name" not in output_df.columns
    assert list(output_df.columns) == ["account_id", "dormancy"]
    assert set(output_df.columns) == {"account_id", "dormancy"}
    assert set(output_df.columns) <= ALLOWED_OUTPUT_COLUMNS


def test_multiple_extra_columns_on_accounts_df_do_not_leak_into_output():
    accounts_df = pd.read_csv(_fixture_path("accounts.csv")).copy()
    accounts_df["customer_name"] = "Jane Doe"
    accounts_df["ssn"] = "000-00-0000"
    accounts_df["email"] = "jane.doe@example.com"

    core_tx_df = pd.read_csv(_fixture_path("core_transactions.csv"))
    trading_tx_df = pd.read_csv(_fixture_path("trading_transactions.csv"))
    digital_df = pd.read_csv(_fixture_path("digital_payments.csv"))

    output_df, _excluded_df = compute_dormancy(
        accounts_df, core_tx_df, trading_tx_df, digital_df, as_of_date=AS_OF_DATE
    )

    leaked_columns = set(output_df.columns) - ALLOWED_OUTPUT_COLUMNS
    assert leaked_columns == set()
    assert set(output_df.columns) == {"account_id", "dormancy"}
