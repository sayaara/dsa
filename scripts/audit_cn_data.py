#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only audit of legacy mainland-China (``cn``) data in the SQLite database.

Mainland China is a legacy, read-only market: existing rows keep loading, but nothing new can
be created as ``cn``. Run this against the real database to see whether any ``cn`` data is
left, which decides whether the ``cn`` code paths can ever be removed.

    python scripts/audit_cn_data.py [--db ./data/stock_analysis.db]

The database is opened read-only; nothing is modified. Exit code is 0 when no ``cn`` rows
exist and 1 when some do (so it can be scripted).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

MARKET_COLUMNS = ("market", "region")
# Tables that hold a stock code but no market column; a bare 6-digit code is an A-share.
CODE_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("analysis_history", "code"),
    ("stock_daily", "code"),
)
SIX_DIGIT = re.compile(r"^\d{6}(\.(SH|SZ|SS|BJ))?$", re.IGNORECASE)


def _tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [r[0] for r in rows]


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def audit(db_path: Path) -> Dict[str, Dict[str, int]]:
    """Return ``{table: {label: row_count}}`` for every place ``cn`` data can live."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        result: Dict[str, Dict[str, int]] = {}
        for table in _tables(conn):
            columns = _columns(conn, table)
            for column in MARKET_COLUMNS:
                if column in columns:
                    count = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE LOWER("{column}") = ?', ("cn",)
                    ).fetchone()[0]
                    if count:
                        result.setdefault(table, {})[f"{column} = 'cn'"] = count
        for table, column in CODE_COLUMNS:
            if table in _tables(conn) and column in _columns(conn, table):
                codes = [r[0] for r in conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}"')]
                count = sum(1 for code in codes if code and SIX_DIGIT.match(str(code).strip()))
                if count:
                    result.setdefault(table, {})[f"distinct six-digit {column} (A-share)"] = count
        return result
    finally:
        conn.close()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="./data/stock_analysis.db", help="path to the SQLite database")
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 2
    result = audit(db_path)
    if not result:
        print(f"No legacy cn data found in {db_path}.")
        return 0
    print(f"Legacy cn data found in {db_path}:")
    for table in sorted(result):
        for label, count in sorted(result[table].items()):
            print(f"  {table}: {count} ({label})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
