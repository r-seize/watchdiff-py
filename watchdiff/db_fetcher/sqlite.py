from __future__ import annotations

import sqlite3

from watchdiff.db_fetcher import DbFetchResult
from watchdiff.db_models import ColumnDef, DbDiffMode, DbWatchConfig


def fetch_sqlite(config: DbWatchConfig) -> DbFetchResult:
    path = config.connection_string.removeprefix("sqlite://")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        sql  = config.query or f'SELECT * FROM {_q(config.table)}'
        cur  = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

        schema = None
        if config.diff_mode == DbDiffMode.SCHEMA:
            cur = conn.execute(f"PRAGMA table_info({_q(config.table)})")
            schema = [
                ColumnDef(
                    name=r["name"],
                    type=r["type"],
                    nullable=r["notnull"] == 0,
                    primary_key=r["pk"] != 0,
                    default_value=r["dflt_value"],
                )
                for r in cur.fetchall()
            ]
        return DbFetchResult(rows=rows, schema=schema)
    finally:
        conn.close()


def _q(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'
