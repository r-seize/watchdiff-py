from __future__ import annotations

from dataclasses import dataclass

from watchdiff.db_models import ColumnDef, DbDriver, DbWatchConfig, Row


@dataclass
class DbFetchResult:
    rows:   list[Row]
    schema: list[ColumnDef] | None = None


class DbFetcher:
    def fetch(self, config: DbWatchConfig) -> DbFetchResult:
        if config.driver == DbDriver.SQLITE:
            from watchdiff.db_fetcher.sqlite import fetch_sqlite
            return fetch_sqlite(config)
        if config.driver == DbDriver.POSTGRES:
            from watchdiff.db_fetcher.postgres import fetch_postgres
            return fetch_postgres(config)
        if config.driver == DbDriver.MYSQL:
            from watchdiff.db_fetcher.mysql import fetch_mysql
            return fetch_mysql(config)
        raise ValueError(f"Unsupported driver: {config.driver}")

    async def fetch_async(self, config: DbWatchConfig) -> DbFetchResult:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch, config)
