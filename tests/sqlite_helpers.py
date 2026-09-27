# -*- coding: utf-8 -*-
"""SQLite helpers shared by tests that inspect database files directly."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def sqlite_connection(path) -> Iterator[sqlite3.Connection]:
    """Open a sqlite3 connection that commits like ``with conn`` and is always closed.

    ``with sqlite3.connect(...)`` only ends the transaction; the connection stays
    open until garbage collection. On Windows an open handle keeps the file
    locked, so temporary database directories cannot be removed afterwards.
    """
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@contextmanager
def temporary_database_dir() -> Iterator[str]:
    """TemporaryDirectory that disposes the DatabaseManager engine before removing files.

    The engine keeps pooled connections to a SQLite file open; on Windows the
    directory cannot be deleted while they exist.
    """
    from src.storage import DatabaseManager

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            yield tmpdir
        finally:
            DatabaseManager.reset_instance()
