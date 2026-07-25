from __future__ import annotations

from urllib.parse import urlparse

from watchdiff.db_fetcher import DbFetchResult
from watchdiff.db_models import ColumnDef, DbDiffMode, DbWatchConfig


def fetch_mysql(config: DbWatchConfig) -> DbFetchResult:
    try:
        import pymysql
        import pymysql.cursors
    except ImportError as exc:
        raise ImportError(
            "pymysql is required for MySQL monitoring. "
            "Run: pip install 'watchdiff-core[mysql]'"
        ) from exc

    conn = pymysql.connect(**_parse_dsn(config.connection_string), cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            sql = config.query or f"SELECT * FROM {_q(config.table)}"
            cur.execute(sql)
            rows = list(cur.fetchall())

            schema = None
            if config.diff_mode == DbDiffMode.SCHEMA:
                cur.execute(
                    """SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT
                       FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                       ORDER BY ORDINAL_POSITION""",
                    (config.table,),
                )
                schema = [
                    ColumnDef(
                        name=c["COLUMN_NAME"],
                        type=c["COLUMN_TYPE"],
                        nullable=c["IS_NULLABLE"] == "YES",
                        primary_key=c["COLUMN_KEY"] == "PRI",
                        default_value=c["COLUMN_DEFAULT"],
                    )
                    for c in cur.fetchall()
                ]
        return DbFetchResult(rows=rows, schema=schema)
    finally:
        conn.close()


def _q(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def _parse_dsn(dsn: str) -> dict[str, object]:
    u = urlparse(dsn)
    params: dict[str, object] = {
        "host":   u.hostname or "localhost",
        "user":   u.username,
        "passwd": u.password,
        "db":     u.path.lstrip("/"),
    }
    if u.port:
        params["port"] = u.port
    return params
