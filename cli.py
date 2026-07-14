"""
Command-line entrypoint for the dormancy flagging pipeline.

Reads the four source CSV tables, runs `compute_dormancy`, and writes
two output CSVs: the primary dormancy flags and a secondary audit file
of accounts excluded from evaluation.

Usage (run from inside the `python/` directory):

    python -m dormancy.cli \\
        --accounts-csv fixtures/accounts.csv \\
        --core-tx-csv fixtures/core_transactions.csv \\
        --trading-tx-csv fixtures/trading_transactions.csv \\
        --digital-payments-csv fixtures/digital_payments.csv \\
        --as-of-date 2026-07-06 \\
        --output-csv dormancy_flags.csv \\
        --excluded-csv excluded_accounts.csv
"""
from __future__ import annotations

import argparse

import pandas as pd

from dormancy.core import compute_dormancy


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Construct the argparse parser for the dormancy CLI.

    Returns:
        A configured argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description="Flag dormant bank accounts as of a reference date."
    )
    parser.add_argument(
        "--accounts-csv", required=True, help="Path to the accounts CSV table."
    )
    parser.add_argument(
        "--core-tx-csv",
        required=True,
        help="Path to the core_transactions CSV table.",
    )
    parser.add_argument(
        "--trading-tx-csv",
        required=True,
        help="Path to the trading_transactions CSV table.",
    )
    parser.add_argument(
        "--digital-payments-csv",
        required=True,
        help="Path to the digital_payments CSV table.",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        help=(
            "ISO date (YYYY-MM-DD) reference date applied uniformly to "
            "the whole run. Defaults to today's date if omitted."
        ),
    )
    parser.add_argument(
        "--output-csv",
        default="dormancy_flags.csv",
        help=(
            "Path to write the primary dormancy flags output "
            "(default: dormancy_flags.csv)."
        ),
    )
    parser.add_argument(
        "--excluded-csv",
        default="excluded_accounts.csv",
        help=(
            "Path to write the excluded-accounts audit output "
            "(default: excluded_accounts.csv)."
        ),
    )
    return parser


def main(argv=None) -> None:
    """
    Parse CLI arguments, run the dormancy pipeline, and write both output
    CSVs to disk.

    Args:
        argv: Optional list of argument strings (defaults to
            `sys.argv[1:]` via argparse when None). Primarily useful for
            testing the CLI without shelling out to a subprocess.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    accounts_df = pd.read_csv(args.accounts_csv)
    core_tx_df = pd.read_csv(args.core_tx_csv)
    trading_tx_df = pd.read_csv(args.trading_tx_csv)
    digital_df = pd.read_csv(args.digital_payments_csv)

    output_df, excluded_df = compute_dormancy(
        accounts_df,
        core_tx_df,
        trading_tx_df,
        digital_df,
        as_of_date=args.as_of_date,
    )

    output_df.to_csv(args.output_csv, index=False)
    excluded_df.to_csv(args.excluded_csv, index=False)

    print(
        f"Wrote {len(output_df)} evaluated account(s) to {args.output_csv} "
        f"and {len(excluded_df)} excluded account(s) to {args.excluded_csv}."
    )


if __name__ == "__main__":
    main()
