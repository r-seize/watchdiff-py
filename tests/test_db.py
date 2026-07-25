"""
Tests for v0.2.0 DB monitoring: models, diff engine, fetcher (SQLite), scheduler.
All tests use only stdlib — no psycopg2 / pymysql required.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from watchdiff.db_diff import DbDiffEngine
from watchdiff.db_fetcher import DbFetcher
from watchdiff.db_models import (
    ColumnDef,
    DbChangeKind,
    DbDiffMode,
    DbDiffReport,
    DbDriver,
    DbSnapshot,
    DbWatchConfig,
    DbWatcherStatus,
    SchemaChangeInfo,
    ThresholdInfo,
    db_has_changes,
    db_report_summary,
    db_snapshot_key,
    make_db_watch_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs: Any) -> DbWatchConfig:
    return make_db_watch_config("sqlite:///test.db", "users", **kwargs)


def _snap(rows: list[dict], schema: list[ColumnDef] | None = None) -> DbSnapshot:
    return DbSnapshot.create("sqlite:///test.db", "users", rows, schema)


def _engine() -> DbDiffEngine:
    return DbDiffEngine()


# ---------------------------------------------------------------------------
# make_db_watch_config
# ---------------------------------------------------------------------------

class TestMakeDbWatchConfig:
    def test_defaults(self) -> None:
        cfg = make_db_watch_config("sqlite:///app.db", "orders")
        assert cfg.connection_string == "sqlite:///app.db"
        assert cfg.table == "orders"
        assert cfg.diff_mode == DbDiffMode.ROW
        assert cfg.interval == 300
        assert cfg.alert_on_insert is True
        assert cfg.alert_on_delete is True
        assert cfg.alert_on_update is True
        assert cfg.dry_run is False
        assert cfg.webhooks == []
        assert cfg.webhook_retries == 3

    def test_driver_detection_sqlite(self) -> None:
        cfg = make_db_watch_config("sqlite:///app.db", "t")
        assert cfg.driver == DbDriver.SQLITE

    def test_driver_detection_postgres(self) -> None:
        cfg = make_db_watch_config("postgresql://user:pass@host/db", "t")
        assert cfg.driver == DbDriver.POSTGRES

    def test_driver_detection_postgres_short(self) -> None:
        cfg = make_db_watch_config("postgres://localhost/db", "t")
        assert cfg.driver == DbDriver.POSTGRES

    def test_driver_detection_mysql(self) -> None:
        cfg = make_db_watch_config("mysql://user:pass@host/db", "t")
        assert cfg.driver == DbDriver.MYSQL

    def test_diff_mode_string_to_enum(self) -> None:
        cfg = make_db_watch_config("sqlite:///x.db", "t", diff_mode="schema")
        assert cfg.diff_mode == DbDiffMode.SCHEMA

    def test_label_defaults_to_table(self) -> None:
        cfg = make_db_watch_config("sqlite:///x.db", "my_table")
        assert "my_table" in cfg.label

    def test_custom_label(self) -> None:
        cfg = make_db_watch_config("sqlite:///x.db", "t", label="My Watcher")
        assert cfg.label == "My Watcher"

    def test_primary_key(self) -> None:
        cfg = make_db_watch_config("sqlite:///x.db", "t", primary_key=["id"])
        assert cfg.primary_key == ["id"]

    def test_webhooks(self) -> None:
        cfg = make_db_watch_config("sqlite:///x.db", "t", webhooks=["https://hook.example.com"])
        assert cfg.webhooks == ["https://hook.example.com"]


# ---------------------------------------------------------------------------
# db_snapshot_key
# ---------------------------------------------------------------------------

class TestDbSnapshotKey:
    def test_returns_string(self) -> None:
        key = db_snapshot_key("sqlite:///app.db", "users")
        assert isinstance(key, str)
        assert "users" in key

    def test_stable(self) -> None:
        k1 = db_snapshot_key("sqlite:///app.db", "users")
        k2 = db_snapshot_key("sqlite:///app.db", "users")
        assert k1 == k2

    def test_different_tables(self) -> None:
        k1 = db_snapshot_key("sqlite:///app.db", "users")
        k2 = db_snapshot_key("sqlite:///app.db", "orders")
        assert k1 != k2

    def test_different_connections(self) -> None:
        k1 = db_snapshot_key("sqlite:///app.db", "users")
        k2 = db_snapshot_key("postgresql://localhost/db", "users")
        assert k1 != k2

    def test_format_starts_with_db(self) -> None:
        key = db_snapshot_key("sqlite:///app.db", "users")
        assert key.startswith("db::")


# ---------------------------------------------------------------------------
# DbSnapshot
# ---------------------------------------------------------------------------

class TestDbSnapshot:
    def test_create_computes_checksum(self) -> None:
        snap = DbSnapshot.create("sqlite:///x.db", "t", [{"id": 1}], None)
        assert snap.checksum
        assert len(snap.checksum) == 64  # sha256 hex

    def test_same_rows_same_checksum(self) -> None:
        rows = [{"id": 1, "name": "Alice"}]
        s1 = DbSnapshot.create("sqlite:///x.db", "t", rows, None)
        s2 = DbSnapshot.create("sqlite:///x.db", "t", rows, None)
        assert s1.checksum == s2.checksum

    def test_different_rows_different_checksum(self) -> None:
        s1 = DbSnapshot.create("sqlite:///x.db", "t", [{"id": 1}], None)
        s2 = DbSnapshot.create("sqlite:///x.db", "t", [{"id": 2}], None)
        assert s1.checksum != s2.checksum

    def test_captured_at_utc(self) -> None:
        snap = DbSnapshot.create("sqlite:///x.db", "t", [], None)
        assert snap.captured_at.tzinfo is not None


# ---------------------------------------------------------------------------
# DbDiffEngine — row mode
# ---------------------------------------------------------------------------

class TestDiffEngineRow:
    def _cfg(self, **kw: Any) -> DbWatchConfig:
        return _make_config(diff_mode="row", **kw)

    def test_no_changes(self) -> None:
        rows = [{"id": 1, "name": "Alice"}]
        cfg  = self._cfg(primary_key=["id"])
        before, after = _snap(rows), _snap(rows)
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)
        assert report.changes == []

    def test_detects_insert_with_pk(self) -> None:
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}, {"id": 2}])
        cfg    = self._cfg(primary_key=["id"])
        report = _engine().compare(before, after, cfg)
        assert db_has_changes(report)
        kinds = [c.kind for c in report.changes]
        assert DbChangeKind.INSERTED in kinds

    def test_detects_delete_with_pk(self) -> None:
        before = _snap([{"id": 1}, {"id": 2}])
        after  = _snap([{"id": 1}])
        cfg    = self._cfg(primary_key=["id"])
        report = _engine().compare(before, after, cfg)
        assert db_has_changes(report)
        assert any(c.kind == DbChangeKind.DELETED for c in report.changes)

    def test_detects_update_with_pk(self) -> None:
        before = _snap([{"id": 1, "name": "Alice"}])
        after  = _snap([{"id": 1, "name": "Bob"}])
        cfg    = self._cfg(primary_key=["id"])
        report = _engine().compare(before, after, cfg)
        assert db_has_changes(report)
        assert any(c.kind == DbChangeKind.UPDATED for c in report.changes)
        updated = next(c for c in report.changes if c.kind == DbChangeKind.UPDATED)
        assert updated.modifications
        mod = updated.modifications[0]
        assert mod.column == "name"
        assert mod.before == "Alice"
        assert mod.after  == "Bob"

    def test_alert_on_insert_false(self) -> None:
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}, {"id": 2}])
        cfg    = self._cfg(primary_key=["id"], alert_on_insert=False)
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)

    def test_alert_on_delete_false(self) -> None:
        before = _snap([{"id": 1}, {"id": 2}])
        after  = _snap([{"id": 1}])
        cfg    = self._cfg(primary_key=["id"], alert_on_delete=False)
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)

    def test_alert_on_update_false(self) -> None:
        before = _snap([{"id": 1, "name": "Alice"}])
        after  = _snap([{"id": 1, "name": "Bob"}])
        cfg    = self._cfg(primary_key=["id"], alert_on_update=False)
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)

    def test_no_pk_insert(self) -> None:
        before = _snap([{"name": "Alice"}])
        after  = _snap([{"name": "Alice"}, {"name": "Bob"}])
        cfg    = self._cfg()
        report = _engine().compare(before, after, cfg)
        assert any(c.kind == DbChangeKind.INSERTED for c in report.changes)

    def test_ignore_columns(self) -> None:
        before = _snap([{"id": 1, "updated_at": "2024-01-01"}])
        after  = _snap([{"id": 1, "updated_at": "2024-06-01"}])
        cfg    = self._cfg(primary_key=["id"], ignore_columns=["updated_at"])
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)

    def test_empty_before_and_after(self) -> None:
        before = _snap([])
        after  = _snap([])
        cfg    = self._cfg(primary_key=["id"])
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)


# ---------------------------------------------------------------------------
# DbDiffEngine — schema mode
# ---------------------------------------------------------------------------

class TestDiffEngineSchema:
    def _cfg(self) -> DbWatchConfig:
        return _make_config(diff_mode="schema")

    def _col(self, name: str, type_: str = "TEXT", nullable: bool = True) -> ColumnDef:
        return ColumnDef(name=name, type=type_, nullable=nullable, primary_key=False, default_value=None)

    def test_no_schema_change(self) -> None:
        cols   = [self._col("id", "INTEGER"), self._col("name")]
        before = _snap([], cols)
        after  = _snap([], cols)
        report = _engine().compare(before, after, self._cfg())
        assert not db_has_changes(report)

    def test_column_added(self) -> None:
        before = _snap([], [self._col("id")])
        after  = _snap([], [self._col("id"), self._col("email")])
        report = _engine().compare(before, after, self._cfg())
        assert db_has_changes(report)
        assert any(c.kind == DbChangeKind.SCHEMA_CHANGED and c.context == "column added"
                   for c in report.changes)

    def test_column_removed(self) -> None:
        before = _snap([], [self._col("id"), self._col("email")])
        after  = _snap([], [self._col("id")])
        report = _engine().compare(before, after, self._cfg())
        assert any(c.kind == DbChangeKind.SCHEMA_CHANGED and c.context == "column removed"
                   for c in report.changes)

    def test_type_changed(self) -> None:
        before = _snap([], [self._col("age", "INTEGER")])
        after  = _snap([], [self._col("age", "TEXT")])
        report = _engine().compare(before, after, self._cfg())
        assert any(c.kind == DbChangeKind.SCHEMA_CHANGED and c.context == "type changed"
                   for c in report.changes)

    def test_nullability_changed(self) -> None:
        before = _snap([], [ColumnDef("id", "INTEGER", True, False, None)])
        after  = _snap([], [ColumnDef("id", "INTEGER", False, False, None)])
        report = _engine().compare(before, after, self._cfg())
        assert any(c.kind == DbChangeKind.SCHEMA_CHANGED and c.context == "nullability changed"
                   for c in report.changes)


# ---------------------------------------------------------------------------
# DbDiffEngine — aggregate mode
# ---------------------------------------------------------------------------

class TestDiffEngineAggregate:
    def _cfg(self, threshold: float = 0.0) -> DbWatchConfig:
        return _make_config(diff_mode="aggregate", threshold=threshold)

    def test_no_change(self) -> None:
        before = _snap([{"count": 100}])
        after  = _snap([{"count": 100}])
        report = _engine().compare(before, after, self._cfg())
        assert not db_has_changes(report)

    def test_change_above_threshold(self) -> None:
        before = _snap([{"count": 100}])
        after  = _snap([{"count": 120}])
        report = _engine().compare(before, after, self._cfg(threshold=10.0))
        assert db_has_changes(report)
        assert any(c.kind == DbChangeKind.THRESHOLD_EXCEEDED for c in report.changes)

    def test_change_below_threshold(self) -> None:
        before = _snap([{"count": 100}])
        after  = _snap([{"count": 105}])
        report = _engine().compare(before, after, self._cfg(threshold=10.0))
        assert not db_has_changes(report)

    def test_zero_threshold_any_change(self) -> None:
        before = _snap([{"count": 100}])
        after  = _snap([{"count": 101}])
        report = _engine().compare(before, after, self._cfg(threshold=0.0))
        assert db_has_changes(report)

    def test_from_zero(self) -> None:
        before = _snap([{"count": 0}])
        after  = _snap([{"count": 5}])
        report = _engine().compare(before, after, self._cfg(threshold=0.0))
        assert db_has_changes(report)

    def test_empty_rows(self) -> None:
        before = _snap([])
        after  = _snap([{"count": 5}])
        report = _engine().compare(before, after, self._cfg())
        assert not db_has_changes(report)


# ---------------------------------------------------------------------------
# DbDiffEngine — value mode
# ---------------------------------------------------------------------------

class TestDiffEngineValue:
    def _cfg(self) -> DbWatchConfig:
        return _make_config(diff_mode="value")

    def test_no_change(self) -> None:
        before = _snap([{"setting": "dark"}])
        after  = _snap([{"setting": "dark"}])
        report = _engine().compare(before, after, self._cfg())
        assert not db_has_changes(report)

    def test_value_changed(self) -> None:
        before = _snap([{"setting": "dark"}])
        after  = _snap([{"setting": "light"}])
        report = _engine().compare(before, after, self._cfg())
        assert db_has_changes(report)
        assert any(c.kind == DbChangeKind.VALUE_CHANGED for c in report.changes)
        vc = next(c for c in report.changes if c.kind == DbChangeKind.VALUE_CHANGED)
        assert vc.before == "dark"
        assert vc.after  == "light"

    def test_numeric_value_changed(self) -> None:
        before = _snap([{"version": 1}])
        after  = _snap([{"version": 2}])
        report = _engine().compare(before, after, self._cfg())
        assert db_has_changes(report)


# ---------------------------------------------------------------------------
# db_has_changes / db_report_summary
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_has_changes_false(self) -> None:
        cfg    = _make_config(primary_key=["id"])
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}])
        report = _engine().compare(before, after, cfg)
        assert not db_has_changes(report)

    def test_has_changes_true(self) -> None:
        cfg    = _make_config(primary_key=["id"])
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}, {"id": 2}])
        report = _engine().compare(before, after, cfg)
        assert db_has_changes(report)

    def test_report_summary_no_changes(self) -> None:
        cfg    = _make_config()
        before = _snap([])
        after  = _snap([])
        report = _engine().compare(before, after, cfg)
        summary = db_report_summary(report)
        assert isinstance(summary, str)
        assert "no changes" in summary.lower()

    def test_report_summary_with_changes(self) -> None:
        cfg    = _make_config(primary_key=["id"])
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}, {"id": 2}])
        report = _engine().compare(before, after, cfg)
        summary = db_report_summary(report)
        assert "1" in summary

    def test_diff_report_as_dict(self) -> None:
        cfg    = _make_config(primary_key=["id"])
        before = _snap([{"id": 1}])
        after  = _snap([{"id": 1}, {"id": 2}])
        report = _engine().compare(before, after, cfg)
        d = report.as_dict()
        assert "table" in d
        assert "changes" in d
        assert isinstance(d["changes"], list)


# ---------------------------------------------------------------------------
# DbFetcher — SQLite (stdlib, no extra dep)
# ---------------------------------------------------------------------------

class TestDbFetcherSqlite:
    def _db(self, tmp_path: Path) -> str:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99)")
        conn.execute("INSERT INTO products VALUES (2, 'Gadget', 19.99)")
        conn.commit()
        conn.close()
        return f"sqlite://{db_path}"

    def test_fetch_rows(self, tmp_path: Path) -> None:
        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "products")
        result   = DbFetcher().fetch(cfg)
        assert len(result.rows) == 2
        assert result.rows[0]["name"] == "Widget"

    def test_fetch_schema(self, tmp_path: Path) -> None:
        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "products", diff_mode="schema")
        result   = DbFetcher().fetch(cfg)
        assert result.schema is not None
        names = [c.name for c in result.schema]
        assert "id" in names
        assert "name" in names
        assert "price" in names

    def test_fetch_custom_query(self, tmp_path: Path) -> None:
        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "products",
                                        query="SELECT id FROM products WHERE id = 1")
        result   = DbFetcher().fetch(cfg)
        assert len(result.rows) == 1
        assert result.rows[0]["id"] == 1

    def test_fetch_empty_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        conn    = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER)")
        conn.commit()
        conn.close()
        cfg    = make_db_watch_config(f"sqlite://{db_path}", "items")
        result = DbFetcher().fetch(cfg)
        assert result.rows == []

    @pytest.mark.asyncio
    async def test_fetch_async(self, tmp_path: Path) -> None:
        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "products")
        result   = await DbFetcher().fetch_async(cfg)
        assert len(result.rows) == 2


# ---------------------------------------------------------------------------
# DbSyncScheduler — basic integration (SQLite, mocked store)
# ---------------------------------------------------------------------------

class TestDbSyncScheduler:
    def _db(self, tmp_path: Path) -> str:
        db_path = tmp_path / "sched.db"
        conn    = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, msg TEXT)")
        conn.execute("INSERT INTO logs VALUES (1, 'hello')")
        conn.commit()
        conn.close()
        return f"sqlite://{db_path}"

    def test_first_run_saves_snapshot(self, tmp_path: Path) -> None:
        from watchdiff.db_scheduler import DbSyncScheduler

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "logs", interval=9999)

        store        = MagicMock()
        store.load_latest.return_value = None

        scheduler = DbSyncScheduler(store)
        scheduler.start([cfg], block=False)
        time.sleep(0.3)
        scheduler.stop()

        store.save_snapshot.assert_called_once()

    def test_change_fires_callback(self, tmp_path: Path) -> None:
        from watchdiff.models import Snapshot
        from watchdiff.db_models import DbSnapshot
        from watchdiff.db_scheduler import DbSyncScheduler, _serialize

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "logs", interval=9999, primary_key=["id"])

        key      = db_snapshot_key(conn_str, "logs")
        old_snap = DbSnapshot.create(conn_str, "logs", [], None)
        stored   = _serialize(old_snap, key)

        store = MagicMock()
        store.load_latest.return_value = stored

        received: list[Any] = []
        cfg = make_db_watch_config(
            conn_str, "logs",
            interval=9999,
            primary_key=["id"],
            on_change=received.append,
        )

        scheduler = DbSyncScheduler(store)
        scheduler.start([cfg], block=False)
        time.sleep(0.3)
        scheduler.stop()

        assert len(received) == 1
        assert db_has_changes(received[0])

    def test_pause_and_resume(self, tmp_path: Path) -> None:
        from watchdiff.db_scheduler import DbSyncScheduler

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "logs", interval=9999)
        key      = db_snapshot_key(conn_str, "logs")

        store = MagicMock()
        store.load_latest.return_value = None

        scheduler = DbSyncScheduler(store)
        scheduler.start([cfg], block=False)
        time.sleep(0.2)
        scheduler.pause(key)
        call_count = store.save_snapshot.call_count

        time.sleep(0.1)
        assert store.save_snapshot.call_count == call_count

        scheduler.resume(key)
        scheduler.stop()

    def test_get_statuses(self, tmp_path: Path) -> None:
        from watchdiff.db_scheduler import DbSyncScheduler

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "logs", interval=9999)

        store = MagicMock()
        store.load_latest.return_value = None

        scheduler = DbSyncScheduler(store)
        scheduler.start([cfg], block=False)
        time.sleep(0.3)
        scheduler.stop()

        statuses = scheduler.get_statuses()
        assert len(statuses) == 1
        s = statuses[0]
        assert s.table == "logs"
        assert s.checks_count >= 1


# ---------------------------------------------------------------------------
# DbAsyncScheduler
# ---------------------------------------------------------------------------

class TestDbAsyncScheduler:
    def _db(self, tmp_path: Path) -> str:
        db_path = tmp_path / "async.db"
        conn    = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO events VALUES (1, 'boot')")
        conn.commit()
        conn.close()
        return f"sqlite://{db_path}"

    @pytest.mark.asyncio
    async def test_first_run_saves_snapshot(self, tmp_path: Path) -> None:
        import asyncio
        from watchdiff.db_scheduler import DbAsyncScheduler

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "events", interval=9999)

        store = MagicMock()
        store.load_latest.return_value = None

        scheduler = DbAsyncScheduler(store)
        task      = asyncio.create_task(scheduler.start([cfg]))
        await asyncio.sleep(0.3)
        scheduler.stop()
        await asyncio.sleep(0.1)
        task.cancel()

        store.save_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_statuses(self, tmp_path: Path) -> None:
        import asyncio
        from watchdiff.db_scheduler import DbAsyncScheduler

        conn_str = self._db(tmp_path)
        cfg      = make_db_watch_config(conn_str, "events", interval=9999)

        store = MagicMock()
        store.load_latest.return_value = None

        scheduler = DbAsyncScheduler(store)
        task      = asyncio.create_task(scheduler.start([cfg]))
        await asyncio.sleep(0.3)
        statuses = scheduler.get_statuses()
        scheduler.stop()
        task.cancel()

        assert len(statuses) == 1
        assert statuses[0].table == "events"


# ---------------------------------------------------------------------------
# WatchDiff.watch_db integration
# ---------------------------------------------------------------------------

class TestWatchDiffWatchDb:
    def test_watch_db_chainable(self, tmp_path: Path) -> None:
        from watchdiff.core import WatchDiff
        conn_str = f"sqlite://{tmp_path / 'x.db'}"
        wd = WatchDiff(storage_dir=str(tmp_path / "store"))
        result = wd.watch_db(conn_str, "t")
        assert result is wd

    def test_watch_db_appends_config(self, tmp_path: Path) -> None:
        from watchdiff.core import WatchDiff
        conn_str = f"sqlite://{tmp_path / 'x.db'}"
        wd = WatchDiff(storage_dir=str(tmp_path / "store"))
        wd.watch_db(conn_str, "t1")
        wd.watch_db(conn_str, "t2")
        assert len(wd._db_configs) == 2

    def test_db_status_before_start(self, tmp_path: Path) -> None:
        from watchdiff.core import WatchDiff
        conn_str = f"sqlite://{tmp_path / 'x.db'}"
        wd = WatchDiff(storage_dir=str(tmp_path / "store"))
        wd.watch_db(conn_str, "t")
        assert wd.db_status() == []
