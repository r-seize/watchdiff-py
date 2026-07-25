from __future__ import annotations

from watchdiff.db_fetcher import DbFetchResult
from watchdiff.db_models import ColumnDef, DbDiffMode, DbWatchConfig


def fetch_postgres(config: DbWatchConfig) -> DbFetchResult:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for PostgreSQL monitoring. "
            "Run: pip install 'watchdiff-core[postgres]'"
        ) from exc

    conn = psycopg2.connect(config.connection_string)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sql = config.query or f'SELECT * FROM {_q(config.table)}'
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

        schema = None
        if config.diff_mode == DbDiffMode.SCHEMA:
            cur.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                   FROM information_schema.columns
                   WHERE table_name = %s
                   ORDER BY ordinal_position""",
                (config.table,),
            )
            cols = cur.fetchall()

            cur.execute(
                """SELECT kcu.column_name
                   FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage kcu
                     ON tc.constraint_name = kcu.constraint_name
                   WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'""",
                (config.table,),
            )
            pk_cols = {r["column_name"] for r in cur.fetchall()}

            schema = [
                ColumnDef(
                    name=c["column_name"],
                    type=c["data_type"],
                    nullable=c["is_nullable"] == "YES",
                    primary_key=c["column_name"] in pk_cols,
                    default_value=c["column_default"],
                )
                for c in cols
            ]
        return DbFetchResult(rows=rows, schema=schema)
    finally:
        conn.close()


def _q(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'
