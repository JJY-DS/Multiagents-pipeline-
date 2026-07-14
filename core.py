"""
Core business logic for dormant bank account flagging.

This module contains pure functions (no filesystem or network I/O) that
implement the dormancy detection algorithm described in the approved
feature plan. All functions operate on pandas DataFrames / row-like
objects and are designed to be independently testable without touching
the filesystem.

Dormancy rule (summary):
  - Accounts opened within 2 months (INCLUSIVE) of the reference date are
    excluded from evaluation entirely, and reported separately for audit.
  - An account with ANY transaction, ever (full history, not a rolling
    window), in ANY of the three transaction tables (core, trading,
    digital payments) is never dormant.
  - Otherwise, for accounts with zero transactions, dormancy is
    determined purely by login staleness:
      * individual accounts: dormant if the primary holder's last login
        is stale (or the holder never logged in).
      * joint accounts: dormant only if BOTH holders' last logins are
        stale (or null).
  - "Stale" means the login is strictly more than 13 months before the
    reference date (the 13-month boundary itself is EXCLUSIVE, i.e. NOT
    stale).

The only fields ever emitted in the primary output are `account_id` and
`dormancy` -- see ALLOWED_OUTPUT_COLUMNS below. This is enforced with a
runtime assertion so that any future accidental column leak (e.g. if the
accounts table grows PII columns) fails loudly rather than silently
shipping sensitive data.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from dateutil.relativedelta import relativedelta

# Privacy guardrail: the primary output must never contain anything
# beyond these columns. Enforced at runtime in compute_dormancy(), not
# just in tests, per the approved plan.
ALLOWED_OUTPUT_COLUMNS = {"account_id", "dormancy"}

# Boundary widths, in calendar months, per the approved plan. Using
# relativedelta (rather than a fixed day-count) gives calendar-accurate
# month arithmetic (e.g. correctly handles month-end/leap-year cases).
EXCLUSION_WINDOW_MONTHS = 2
LOGIN_STALENESS_MONTHS = 13


def to_timestamp(value) -> Optional[pd.Timestamp]:
    """
    Convert a value to a pandas Timestamp, normalizing all "null-like"
    representations to None.

    Args:
        value: An ISO date string, datetime-like object, pandas
            Timestamp, or a null-like value (None, float('nan'),
            pandas.NaT, or an empty/whitespace-only string).

    Returns:
        A pandas.Timestamp, or None if `value` represents a null.
    """
    if value is None:
        return None
    # isinstance check first: pd.isna() on an arbitrary non-scalar can
    # raise, but every value we receive here is expected to be scalar
    # (a single cell from a DataFrame row).
    if isinstance(value, str):
        if value.strip() == "":
            return None
        return pd.Timestamp(value)
    if pd.isna(value):
        return None
    return pd.Timestamp(value)


def is_stale(login_date, cutoff: pd.Timestamp) -> bool:
    """
    Determine whether a login date counts as "stale" relative to a cutoff.

    An account holder who has never logged in (a null login date) is
    always considered stale -- there is no evidence of recent activity.
    Otherwise the comparison is a strict "less than" against the cutoff,
    so a login falling exactly ON the cutoff date is NOT stale (the
    13-month boundary is exclusive, per the approved plan).

    Args:
        login_date: The last-login date, in any form accepted by
            `to_timestamp` (including null).
        cutoff: The pandas Timestamp before which a login counts as
            stale.

    Returns:
        True if the login is stale (or the holder never logged in),
        False otherwise.
    """
    timestamp = to_timestamp(login_date)
    if timestamp is None:
        return True  # Never logged in => stale.
    return timestamp < cutoff  # Strict inequality: exact cutoff is NOT stale.


def evaluate_login_staleness(account_row, login_cutoff: pd.Timestamp) -> int:
    """
    Decide the dormancy flag (0 or 1) for an account known to have ZERO
    transactions, based solely on login recency.

    This single function intentionally handles both individual and joint
    accounts: both share the exact same is_stale/null/cutoff evaluation
    for each login column, and only differ in how many login columns
    must be stale before the account is flagged dormant (one for
    individual, both for joint). Splitting this into separate
    evaluate_individual/evaluate_joint functions would duplicate that
    shared logic across two copies for no benefit.

    Args:
        account_row: A row-like object (e.g. a namedtuple from
            `DataFrame.itertuples()`, or a pandas Series) exposing
            `account_type`, `primary_last_login_date`, and (only
            required for joint accounts) `joint_last_login_date`.
        login_cutoff: The pandas Timestamp before which a login is
            considered stale.

    Returns:
        1 if the account is dormant, 0 otherwise.

    Raises:
        ValueError: If `account_row.account_type` is not exactly
            "individual" or "joint" (case-sensitive). We deliberately do
            NOT silently default an unrecognized type -- see plan
            assumptions.
    """
    primary_stale = is_stale(account_row.primary_last_login_date, login_cutoff)

    if account_row.account_type == "individual":
        return 1 if primary_stale else 0

    if account_row.account_type == "joint":
        joint_stale = is_stale(account_row.joint_last_login_date, login_cutoff)
        return 1 if (primary_stale and joint_stale) else 0

    raise ValueError(f"Unknown account_type: {account_row.account_type!r}")


def compute_dormancy(
    accounts_df: pd.DataFrame,
    core_tx_df: pd.DataFrame,
    trading_tx_df: pd.DataFrame,
    digital_df: pd.DataFrame,
    as_of_date=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Evaluate dormancy for every account in `accounts_df` as of a single,
    uniformly-applied reference date.

    Args:
        accounts_df: DataFrame with columns account_id, account_type,
            primary_customer_id, joint_customer_id, account_open_date,
            primary_last_login_date, joint_last_login_date.
            `joint_customer_id` / `joint_last_login_date` are expected to
            be null for individual accounts.
        core_tx_df: DataFrame with (at least) an `account_id` column
            (core banking transactions).
        trading_tx_df: DataFrame with (at least) an `account_id` column
            (trading transactions).
        digital_df: DataFrame with (at least) an `account_id` column
            (digital payments).
        as_of_date: Optional ISO date string / Timestamp used as the
            single reference date for all boundary calculations across
            the whole run. Defaults to today's date (wall-clock,
            normalized to midnight) if omitted.

    Returns:
        A tuple (output_df, excluded_df):
          - output_df: columns exactly {"account_id", "dormancy"}, one
            row per evaluated (non-excluded) account, in the same order
            as `accounts_df`.
          - excluded_df: columns {"account_id", "reason"}, one row per
            account excluded from evaluation (dropped from output_df).

    Raises:
        ValueError: If any evaluated account has an account_type other
            than "individual" or "joint" (propagated from
            `evaluate_login_staleness`).
        AssertionError: If the computed output ever contains columns
            beyond ALLOWED_OUTPUT_COLUMNS -- a privacy guardrail that
            must fail loudly at runtime, not just in tests.
    """
    as_of = (
        to_timestamp(as_of_date)
        if as_of_date is not None
        else pd.Timestamp.now().normalize()
    )
    exclusion_cutoff = as_of - relativedelta(months=EXCLUSION_WINDOW_MONTHS)
    login_cutoff = as_of - relativedelta(months=LOGIN_STALENESS_MONTHS)

    # "Zero transactions" means full history, not a rolling window: an
    # account counts as having transacted if it has ANY row, at ANY
    # date, in ANY of the three transaction tables. Recency is handled
    # entirely by the login-staleness rule below, not by windowing this
    # check.
    tx_account_ids = (
        set(core_tx_df["account_id"])
        | set(trading_tx_df["account_id"])
        | set(digital_df["account_id"])
    )

    evaluated_rows = []
    excluded_rows = []

    for row in accounts_df.itertuples(index=False):
        open_date = to_timestamp(row.account_open_date)

        # Inclusive boundary: an account opened exactly 2 months before
        # the reference date is excluded (not just accounts opened
        # strictly more recently).
        if open_date is not None and open_date >= exclusion_cutoff:
            excluded_rows.append(
                {"account_id": row.account_id, "reason": "opened_within_2_months"}
            )
            continue  # Dropped from the primary output entirely.

        has_transactions = row.account_id in tx_account_ids

        if has_transactions:
            dormancy = 0
        else:
            dormancy = evaluate_login_staleness(row, login_cutoff)

        evaluated_rows.append({"account_id": row.account_id, "dormancy": dormancy})

    # Explicit `columns=` keeps the schema correct even when a list is
    # empty (e.g. no excluded accounts in a given run).
    output_df = pd.DataFrame(evaluated_rows, columns=["account_id", "dormancy"])
    excluded_df = pd.DataFrame(excluded_rows, columns=["account_id", "reason"])

    # Privacy guardrail: must fail loudly at runtime, not just in tests.
    assert set(output_df.columns) <= ALLOWED_OUTPUT_COLUMNS, (
        f"Output columns {set(output_df.columns)} exceed allowed columns "
        f"{ALLOWED_OUTPUT_COLUMNS}"
    )

    return output_df, excluded_df
