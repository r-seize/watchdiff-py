from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from watchdiff.ai_summarizer import AiError, call_provider, get_provider
from watchdiff.db_diff import DbDiffEngine
from watchdiff.db_fetcher import DbFetcher
from watchdiff.db_models import (
    ColumnDef,
    DbDiffReport,
    DbSnapshot,
    DbWatchConfig,
    DbWatcherStatus,
    SchemaChangeInfo,
    ThresholdInfo,
    db_has_changes,
    db_snapshot_key,
)
from watchdiff.models import Snapshot

logger = logging.getLogger(__name__)

RETRY_BASE_S = 0.5


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _serialize(snap: DbSnapshot, key: str) -> Snapshot:
    content = json.dumps(
        {
            "rows": snap.rows,
            "schema": [
                {
                    "name":          c.name,
                    "type":          c.type,
                    "nullable":      c.nullable,
                    "primary_key":   c.primary_key,
                    "default_value": c.default_value,
                }
                for c in snap.schema
            ] if snap.schema else None,
        },
        default=str,
    )
    return Snapshot(url=key, target=None, content=content, raw_html="", captured_at=snap.captured_at)


def _deserialize(content: str, config: DbWatchConfig) -> DbSnapshot:
    data   = json.loads(content)
    rows   = data.get("rows", [])
    schema: list[ColumnDef] | None = None
    if data.get("schema"):
        schema = [ColumnDef(**c) for c in data["schema"]]
    return DbSnapshot.create(config.connection_string, config.table, rows, schema)


def _build_db_prompt(report: DbDiffReport) -> str:
    lines = []
    for c in report.changes[:20]:
        if c.kind.value == "inserted":
            lines.append(f"Row inserted: {c.row_key or str(c.row)}")
        elif c.kind.value == "deleted":
            lines.append(f"Row deleted: {c.row_key or str(c.row)}")
        elif c.kind.value == "updated":
            mods = ", ".join(
                f"{m.column}: {m.before} -> {m.after}"
                for m in (c.modifications or [])
            )
            lines.append(f"Row {c.row_key} updated - {mods}")
        elif c.kind.value == "schema_changed":
            lines.append(f"Schema {c.context or 'changed'}: column \"{c.column}\"")
        elif c.kind.value == "threshold_exceeded":
            lines.append(f"Aggregate changed: {c.before} -> {c.after}")
        elif c.kind.value == "value_changed":
            lines.append(f"Value changed: {c.before} -> {c.after}")
    return (
        "You are monitoring a database table for changes. Summarize the following diff in 1-2 sentences "
        "in plain language, focusing on what is important to a human reader.\n\n"
        f"Table: {report.label} (mode: {report.diff_mode.value})\nChanges:\n"
        + "\n".join(lines)
        + "\n\nSummary:"
    )


def _dispatch(report: DbDiffReport, config: DbWatchConfig, ai_disabled: set[str], key: str) -> None:
    # AI summary
    if getattr(config, "ai_summary", False) and key not in ai_disabled:
        provider = get_provider(config)
        if provider:
            try:
                report.ai_summary = call_provider(_build_db_prompt(report), provider)
                if report.ai_summary:
                    logger.debug("[%s] AI summary: %s", config.label, report.ai_summary)
            except AiError as exc:
                if exc.is_permanent:
                    ai_disabled.add(key)
                    logger.warning("[%s] AI summaries disabled - %s: %s", config.label, exc.kind, exc)
                elif exc.kind.value == "quota_exceeded":
                    logger.warning("[%s] AI quota exceeded - skipping this check.", config.label)
                else:
                    logger.warning("[%s] AI summary skipped (%s): %s", config.label, exc.kind, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] AI summary error: %s", config.label, exc)

    schema_changes = [c for c in report.changes if c.kind.value == "schema_changed"]
    if schema_changes and config.on_schema_change:
        try:
            config.on_schema_change(SchemaChangeInfo(
                connection_string=config.connection_string,
                table=config.table,
                label=config.label,
                changes=schema_changes,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[watchdiff:db] on_schema_change callback error: %s", exc)

    for tc in [c for c in report.changes if c.kind.value == "threshold_exceeded"]:
        if config.on_threshold:
            prev = float(tc.before or 0)
            curr = float(tc.after or 0)
            pct  = abs((curr - prev) / prev) * 100 if prev != 0 else 100.0
            try:
                config.on_threshold(ThresholdInfo(
                    connection_string=config.connection_string,
                    table=config.table,
                    label=config.label,
                    previous_value=prev,
                    current_value=curr,
                    change_percent=pct,
                    threshold=config.threshold or 0.0,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[watchdiff:db] on_threshold callback error: %s", exc)

    if config.on_change:
        try:
            config.on_change(report)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[watchdiff:db] on_change callback error: %s", exc)

    if config.webhooks:
        _fire_webhooks(report, config)


def _fire_webhooks(report: DbDiffReport, config: DbWatchConfig) -> None:
    try:
        import httpx
    except ImportError:
        logger.warning("[watchdiff:db] httpx is required for webhooks.")
        return

    payload = report.as_dict()
    max_attempts = config.webhook_retries + 1
    for url in config.webhooks:
        for attempt in range(max_attempts):
            try:
                resp = httpx.post(url, json=payload, timeout=10)
                if resp.is_success:
                    break
                if attempt == max_attempts - 1:
                    logger.warning("[watchdiff:db] Webhook %s failed: HTTP %s", url, resp.status_code)
            except Exception as exc:
                if attempt == max_attempts - 1:
                    logger.warning("[watchdiff:db] Webhook %s error: %s", url, exc)
                else:
                    time.sleep(RETRY_BASE_S * (2 ** attempt))


# ---------------------------------------------------------------------------
# SyncScheduler
# ---------------------------------------------------------------------------

class DbSyncScheduler:
    def __init__(self, store: Any) -> None:
        self._store:            Any                             = store
        self._fetcher:          DbFetcher                       = DbFetcher()
        self._engine:           DbDiffEngine                    = DbDiffEngine()
        self._threads:          list[threading.Thread]          = []
        self._stop_events:      list[threading.Event]           = []
        self._paused:           set[str]                        = set()
        self._last_check_at:    dict[str, datetime | None]      = {}
        self._next_check_at:    dict[str, datetime | None]      = {}
        self._last_change_at:   dict[str, datetime | None]      = {}
        self._checks_count:     dict[str, int]                  = {}
        self._changes_count:    dict[str, int]                  = {}
        self._errors_count:     dict[str, int]                  = {}
        self._last_cooldown:    dict[str, float]                = {}
        self._configs:          list[DbWatchConfig]             = []
        self._ai_disabled:      set[str]                        = set()

    def start(self, configs: list[DbWatchConfig], block: bool = True) -> None:
        self._configs = list(configs)
        for config in configs:
            key = db_snapshot_key(config.connection_string, config.table)
            self._last_check_at[key]  = None
            self._next_check_at[key]  = None
            self._last_change_at[key] = None
            self._checks_count[key]   = 0
            self._changes_count[key]  = 0
            self._errors_count[key]   = 0
            self._last_cooldown[key]  = 0.0

            stop_event = threading.Event()
            self._stop_events.append(stop_event)
            thread = threading.Thread(
                target=self._run_loop,
                args=(config, stop_event),
                daemon=True,
                name=f"watchdiff-db-{config.label}",
            )
            self._threads.append(thread)
            thread.start()
            logger.info("Started DB watcher for %s (interval=%ds)", config.label, config.interval)

        if block:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def _run_loop(self, config: DbWatchConfig, stop_event: threading.Event) -> None:
        key = db_snapshot_key(config.connection_string, config.table)
        self._check(key, config)
        while not stop_event.wait(config.interval):
            self._next_check_at[key] = datetime.now(timezone.utc)
            self._check(key, config)

    def _check(self, key: str, config: DbWatchConfig) -> None:
        if key in self._paused:
            return

        self._last_check_at[key] = datetime.now(timezone.utc)
        self._checks_count[key]  = self._checks_count.get(key, 0) + 1

        try:
            result = self._fetcher.fetch(config)
            after  = DbSnapshot.create(config.connection_string, config.table, result.rows, result.schema)

            stored = self._store.load_latest(key, None)
            before = _deserialize(stored.content, config) if stored else None

            if before is None:
                if not config.dry_run:
                    self._store.save_snapshot(_serialize(after, key))
                    if config.max_snapshots:
                        self._store.prune_snapshots(key, None, config.max_snapshots)
                self._next_check_at[key] = datetime.now(timezone.utc)
                return

            report = self._engine.compare(before, after, config)

            if not config.dry_run:
                self._store.save_snapshot(_serialize(after, key))
                if config.max_snapshots:
                    self._store.prune_snapshots(key, None, config.max_snapshots)

            if not db_has_changes(report):
                return

            if config.cooldown:
                now = time.time()
                if now - self._last_cooldown.get(key, 0.0) < config.cooldown:
                    return
                self._last_cooldown[key] = now

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = datetime.now(timezone.utc)

            _dispatch(report, config, self._ai_disabled, key)

        except Exception as exc:
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            if config.on_error:
                try:
                    config.on_error(exc, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[watchdiff:db] on_error callback error: %s", cb_exc)
            else:
                logger.error("[watchdiff:db] %s: %s", config.label, exc)
        finally:
            self._next_check_at[key] = datetime.now(timezone.utc)

    def stop(self) -> None:
        for ev in self._stop_events:
            ev.set()
        logger.info("[watchdiff:db] Stopping all DB watchers.")

    def pause(self, key: str) -> None:
        self._paused.add(key)

    def resume(self, key: str) -> None:
        self._paused.discard(key)

    def get_statuses(self) -> list[DbWatcherStatus]:
        statuses = []
        for config in self._configs:
            key = db_snapshot_key(config.connection_string, config.table)
            statuses.append(DbWatcherStatus(
                connection_string=config.connection_string,
                table=config.table,
                label=config.label,
                diff_mode=config.diff_mode.value,
                interval=config.interval,
                paused=key in self._paused,
                last_check_at=self._last_check_at.get(key),
                next_check_at=self._next_check_at.get(key),
                last_change_at=self._last_change_at.get(key),
                checks_count=self._checks_count.get(key, 0),
                changes_count=self._changes_count.get(key, 0),
                errors_count=self._errors_count.get(key, 0),
            ))
        return statuses


# ---------------------------------------------------------------------------
# AsyncScheduler
# ---------------------------------------------------------------------------

class DbAsyncScheduler:
    def __init__(self, store: Any) -> None:
        self._store:          Any                             = store
        self._fetcher:        DbFetcher                       = DbFetcher()
        self._engine:         DbDiffEngine                    = DbDiffEngine()
        self._tasks:          list[asyncio.Task[None]]        = []
        self._paused:         set[str]                        = set()
        self._last_check_at:  dict[str, datetime | None]      = {}
        self._next_check_at:  dict[str, datetime | None]      = {}
        self._last_change_at: dict[str, datetime | None]      = {}
        self._checks_count:   dict[str, int]                  = {}
        self._changes_count:  dict[str, int]                  = {}
        self._errors_count:   dict[str, int]                  = {}
        self._last_cooldown:  dict[str, float]                = {}
        self._configs:        list[DbWatchConfig]             = []
        self._stop:           bool                            = False
        self._ai_disabled:    set[str]                        = set()

    async def start(self, configs: list[DbWatchConfig]) -> None:
        self._configs = list(configs)
        for config in configs:
            key = db_snapshot_key(config.connection_string, config.table)
            self._last_check_at[key]  = None
            self._next_check_at[key]  = None
            self._last_change_at[key] = None
            self._checks_count[key]   = 0
            self._changes_count[key]  = 0
            self._errors_count[key]   = 0
            self._last_cooldown[key]  = 0.0
            task = asyncio.create_task(self._run_loop(config))
            self._tasks.append(task)

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_loop(self, config: DbWatchConfig) -> None:
        key = db_snapshot_key(config.connection_string, config.table)
        await self._check(key, config)
        while not self._stop:
            self._next_check_at[key] = datetime.now(timezone.utc)
            await asyncio.sleep(config.interval)
            if not self._stop:
                await self._check(key, config)

    async def _check(self, key: str, config: DbWatchConfig) -> None:
        if key in self._paused:
            return

        self._last_check_at[key] = datetime.now(timezone.utc)
        self._checks_count[key]  = self._checks_count.get(key, 0) + 1

        try:
            result = await self._fetcher.fetch_async(config)
            after  = DbSnapshot.create(config.connection_string, config.table, result.rows, result.schema)

            stored = self._store.load_latest(key, None)
            before = _deserialize(stored.content, config) if stored else None

            if before is None:
                if not config.dry_run:
                    self._store.save_snapshot(_serialize(after, key))
                    if config.max_snapshots:
                        self._store.prune_snapshots(key, None, config.max_snapshots)
                self._next_check_at[key] = datetime.now(timezone.utc)
                return

            report = self._engine.compare(before, after, config)

            if not config.dry_run:
                self._store.save_snapshot(_serialize(after, key))
                if config.max_snapshots:
                    self._store.prune_snapshots(key, None, config.max_snapshots)

            if not db_has_changes(report):
                return

            if config.cooldown:
                now = time.time()
                if now - self._last_cooldown.get(key, 0.0) < config.cooldown:
                    return
                self._last_cooldown[key] = now

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = datetime.now(timezone.utc)

            _dispatch(report, config, self._ai_disabled, key)

        except Exception as exc:
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            if config.on_error:
                try:
                    config.on_error(exc, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[watchdiff:db] on_error callback error: %s", cb_exc)
            else:
                logger.error("[watchdiff:db] %s: %s", config.label, exc)
        finally:
            self._next_check_at[key] = datetime.now(timezone.utc)

    def stop(self) -> None:
        self._stop = True
        for task in self._tasks:
            task.cancel()

    def pause(self, key: str) -> None:
        self._paused.add(key)

    def resume(self, key: str) -> None:
        self._paused.discard(key)

    def get_statuses(self) -> list[DbWatcherStatus]:
        statuses = []
        for config in self._configs:
            key = db_snapshot_key(config.connection_string, config.table)
            statuses.append(DbWatcherStatus(
                connection_string=config.connection_string,
                table=config.table,
                label=config.label,
                diff_mode=config.diff_mode.value,
                interval=config.interval,
                paused=key in self._paused,
                last_check_at=self._last_check_at.get(key),
                next_check_at=self._next_check_at.get(key),
                last_change_at=self._last_change_at.get(key),
                checks_count=self._checks_count.get(key, 0),
                changes_count=self._changes_count.get(key, 0),
                errors_count=self._errors_count.get(key, 0),
            ))
        return statuses
