"""DuckDB ad-hoc query utility for Delta Lake tables.

Reads Delta Lake tables as Parquet files via DuckDB's ``parquet_scan()``.
Useful for debugging and validation without spinning up a full Spark session.

Usage:
    # List all sessions
    python scripts/query_delta.py --table interviews --limit 20

    # List suspicious segments
    python scripts/query_delta.py --table transcript_segments \\
        --sql "SELECT * FROM t WHERE suspicious_flag = true"

    # Custom query
    python scripts/query_delta.py --table transcript_segments \\
        --sql "SELECT session_id, COUNT(*) AS n FROM t GROUP BY session_id"

Note:
    Delta Lake uses checkpoint + _delta_log JSON files for transaction history.
    This utility reads the current Parquet snapshot (all non-deleted files),
    which is equivalent to the committed state at query time.
"""

from __future__ import annotations

import argparse
import sys

import duckdb

import config


def _parquet_glob(table_path: str) -> str:
    """Return the DuckDB parquet_scan() glob pattern for a Delta table.

    Args:
        table_path: Absolute path to the Delta table root directory.

    Returns:
        DuckDB parquet_scan expression covering all Parquet data files.
    """
    # Normalise path separators for DuckDB (forward slash works on all platforms)
    normalized = table_path.replace("\\", "/")
    return f"parquet_scan('{normalized}/**/*.parquet')"


def query_table(
    table_name: str,
    delta_lake_path: str,
    sql: str | None = None,
    limit: int = 50,
) -> None:
    """Run a DuckDB query over a Delta Lake table and print the result.

    Args:
        table_name: "interviews" or "transcript_segments".
        delta_lake_path: Base path where Delta tables are stored.
        sql: Optional SQL query; uses table alias ``t``. Overrides ``limit``.
        limit: Maximum rows to return when no custom SQL is provided.
    """
    table_path = f"{delta_lake_path}/{table_name}"
    scan_expr = _parquet_glob(table_path)

    con = duckdb.connect()

    if sql:
        # Replace table alias ``t`` with the parquet_scan expression
        resolved = sql.replace(" t ", f" {scan_expr} ").replace(" t\n", f" {scan_expr}\n")
        # Fallback: if user wrote "FROM t" directly
        if "FROM t" in resolved:
            resolved = resolved.replace("FROM t", f"FROM {scan_expr}")
        query = resolved
    else:
        query = f"SELECT * FROM {scan_expr} LIMIT {limit}"

    try:
        result = con.execute(query).fetchdf()
    except duckdb.IOException as exc:
        print(f"Error: could not read table '{table_name}' at {table_path}: {exc}", file=sys.stderr)
        print("Make sure the Delta table has been written at least once.", file=sys.stderr)
        sys.exit(1)
    finally:
        con.close()

    if result.empty:
        print(f"(no rows in '{table_name}')")
        return

    # Pretty-print with pandas
    with (
        __import__("pandas").option_context(
            "display.max_rows", None,
            "display.max_columns", None,
            "display.width", 200,
        )
    ):
        print(result.to_string(index=False))
    print(f"\n{len(result)} row(s)")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ad-hoc DuckDB query tool for TrustSignal Delta Lake tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--table",
        required=True,
        choices=["interviews", "transcript_segments"],
        help="Delta table to query.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum rows to return (default: 50). Ignored when --sql is provided.",
    )
    parser.add_argument(
        "--sql",
        default=None,
        help=(
            "Custom SQL query. Use 't' as the table alias. "
            "Example: \"SELECT session_id, COUNT(*) FROM t GROUP BY session_id\""
        ),
    )
    parser.add_argument(
        "--delta-path",
        default=config.DELTA_LAKE_PATH,
        help=f"Base path for Delta Lake tables (default: {config.DELTA_LAKE_PATH!r}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    query_table(
        table_name=args.table,
        delta_lake_path=args.delta_path,
        sql=args.sql,
        limit=args.limit,
    )
