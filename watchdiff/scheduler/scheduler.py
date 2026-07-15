"""
Scheduler - drives the periodic check loop.

Two implementations:
  - SyncScheduler:  blocking loop using threading, suitable for scripts.
  - AsyncScheduler: asyncio-based loop for async applications.

Both call the same internal pipeline:
  Fetcher (or BrowserFetcher) - Cleaner - Parser - DiffEngine - Store - Notifier

New features (v0.1.4):
  - Jitter: randomise interval by ± interval*jitter*rand (min 1s).
  - Dry-run: fetch+diff without persisting; on_change callbacks still fire.
  - max_snapshots: prune history after each save.
  - change_threshold: skip alert if changed/total ratio is below threshold.
  - ignore_numbers: strip digit tokens from text before diffing.
  - alert_if_no_change_after + on_silence: fire once when N seconds pass with no change.
  - on_error: callback invoked when a fetch fails.
  - pause(url) / resume(url): suspend/resume individual watchers.
  - status(): live per-watcher state snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from pathlib import Path

from watchdiff.cleaner import Cleaner
from watchdiff.diff import DiffEngine
from watchdiff.fetcher import AsyncFetcher, Fetcher
from watchdiff.models import DiffReport, SilenceInfo, SpikeInfo, StatusChangeInfo, WatchConfig, WatcherStatus
from watchdiff.notifier import Notifier
from watchdiff.parser import Parser, ParserError

_NEVER = 0.0  # sentinel - "never alerted before"

logger = logging.getLogger(__name__)


class SyncScheduler:
    """
    Blocking multi-threaded scheduler.

    Each WatchConfig runs in its own daemon thread with an independent
    sleep interval, so different URLs can have different cadences.
    """

    def __init__(self, store: Any) -> None:
        self._store                                                  = store
        self._fetcher                                                = Fetcher()
        self._browser_fetcher: Any                                   = None  # lazy-init on first browser use
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []
        self._threads: list[threading.Thread]                        = []
        self._stop_events: list[threading.Event]                     = []
        self._configs: list[WatchConfig]                             = []
        self._paused: set[str]                                       = set()
        self._last_alerted: dict[str, float]                         = {}
        self._last_check_at: dict[str, float]                        = {}
        self._next_check_at: dict[str, float]                        = {}
        self._last_change_at: dict[str, float]                       = {}
        self._watcher_start: dict[str, float]                        = {}
        self._checks_count: dict[str, int]                           = {}
        self._changes_count: dict[str, int]                          = {}
        self._errors_count: dict[str, int]                           = {}
        self._silence_fired: dict[str, bool]                         = {}
        self._recent_change_times: dict[str, list[float]]            = {}
        self._last_spike_at: dict[str, float]                        = {}
        self._last_status_code: dict[str, int]                       = {}

    def add_global_callback(self, callback: Callable[[DiffReport], None]) -> None:
        """Register a callback called for every DiffReport (regardless of config)."""
        self._on_diff_callbacks.append(callback)

    def start(self, configs: list[WatchConfig], block: bool = True) -> None:
        """
        Start monitoring all configs.

        Args:
            configs: list of WatchConfig objects.
            block:   If True, blocks until KeyboardInterrupt. If False,
                     returns immediately (threads run as daemons).
        """
        self._configs = list(configs)
        for config in configs:
            stop_event = threading.Event()
            self._stop_events.append(stop_event)
            thread = threading.Thread(
                target = self._run_loop,
                args   = (config, stop_event),
                daemon = True,
                name   = f"watchdiff-{config.label}",
            )
            self._threads.append(thread)
            thread.start()
            logger.info("Started watcher for %s (interval=%ds)", config.label, config.interval)

        if block:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        """Signal all watcher threads to stop."""
        for event in self._stop_events:
            event.set()
        logger.info("Stopping all watchers.")

    def pause(self, url: str) -> None:
        """Suspend the watcher for a URL (checks are skipped until resume)."""
        self._paused.add(url)
        logger.info("Paused watcher for %s", url)

    def resume(self, url: str) -> None:
        """Resume a paused watcher."""
        self._paused.discard(url)
        logger.info("Resumed watcher for %s", url)

    def status(self) -> list[WatcherStatus]:
        """Return a live status snapshot for all registered watchers."""
        result = []
        for config in self._configs:
            key         = _cooldown_key(config)
            last_check  = self._last_check_at.get(key)
            next_check  = self._next_check_at.get(key)
            last_change = self._last_change_at.get(key)
            result.append(WatcherStatus(
                url            = config.url,
                label          = config.label or config.url,
                target         = config.target,
                interval       = config.interval,
                paused         = config.url in self._paused,
                last_check_at  = datetime.fromtimestamp(last_check, tz=timezone.utc) if last_check else None,
                next_check_at  = datetime.fromtimestamp(next_check, tz=timezone.utc) if next_check else None,
                last_change_at = datetime.fromtimestamp(last_change, tz=timezone.utc) if last_change else None,
                checks_count      = self._checks_count.get(key, 0),
                changes_count     = self._changes_count.get(key, 0),
                errors_count      = self._errors_count.get(key, 0),
                last_status_code  = self._last_status_code.get(key, 0),
            ))
        return result

    def check_once(self, config: WatchConfig) -> DiffReport | None:
        """Run a single check for a config and return the DiffReport."""
        return self._check(config)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self, config: WatchConfig, stop_event: threading.Event) -> None:
        """Thread target: check, sleep, repeat."""
        key = _cooldown_key(config)
        self._watcher_start[key] = time.time()
        self._checks_count[key]        = 0
        self._changes_count[key]       = 0
        self._errors_count[key]        = 0
        self._silence_fired[key]       = False
        self._recent_change_times[key] = []
        self._last_spike_at[key]       = 0.0
        self._last_status_code[key]    = 0

        while not stop_event.is_set():
            if config.url not in self._paused:
                self._check(config)

            effective = float(config.interval)
            if config.jitter > 0:
                delta     = config.interval * config.jitter * random.uniform(-1, 1)
                effective = max(1.0, effective + delta)

            self._next_check_at[key] = time.time() + effective
            stop_event.wait(timeout=effective)

    def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to BrowserFetcher or Fetcher based on config.browser."""
        if config.browser:
            if self._browser_fetcher is None:
                from watchdiff.fetcher.browser import BrowserFetcher  # noqa: PLC0415
                self._browser_fetcher = BrowserFetcher()
            return self._browser_fetcher.fetch(config)
        return self._fetcher.fetch(config)

    def _check(self, config: WatchConfig) -> DiffReport | None:
        key = _cooldown_key(config)
        self._checks_count[key]  = self._checks_count.get(key, 0) + 1
        self._last_check_at[key] = time.time()

        extra_patterns = list(config.ignore_patterns)
        if config.ignore_numbers:
            extra_patterns.append(r"\b\d+(\.\d+)?\b")

        try:
            html = self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            current_status = getattr(exc, "status_code", 0)
            self._handle_status_change(key, current_status, config)
            if config.on_error:
                try:
                    config.on_error(exc, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[%s] on_error callback error: %s", config.label, cb_exc)
            return None

        self._handle_status_change(key, 200, config)

        cleaner = Cleaner(
            extra_selectors = config.ignore_selectors,
            extra_patterns  = extra_patterns,
        )
        soup = cleaner.clean(html)

        try:
            snapshot = self._parser.extract(soup, config)
        except ParserError as exc:
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            logger.error("[%s] Parse failed: %s", config.label, exc)
            return None

        previous = self._store.load_latest(config.url, config.target)

        if previous is None:
            if not config.dry_run:
                self._store.save_snapshot(snapshot)
            logger.info("[%s] First snapshot captured.", config.label)
            return None

        report = self._engine.compare(previous, snapshot, config)

        if not config.dry_run:
            self._store.save_snapshot(snapshot)
            if config.max_snapshots and hasattr(self._store, "prune_snapshots"):
                self._store.prune_snapshots(config.url, config.target, config.max_snapshots)

        if report.has_changes:
            if config.change_threshold is not None:
                before_len = max(len(previous.content), 1)
                changed    = sum(
                    max(len(c.before or ""), len(c.after or ""))
                    for c in report.changes
                )
                if (changed / before_len) < config.change_threshold:
                    logger.debug(
                        "[%s] Change ratio %.3f below threshold %.3f - skipped.",
                        config.label, changed / before_len, config.change_threshold,
                    )
                    return report

            if not config.dry_run:
                self._store.save_report(report)

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = time.time()
            self._silence_fired[key]  = False
            logger.info("[%s] %s", config.label, report.summary())

            # Spike detection
            if config.change_spike_window and config.change_spike_threshold:
                now_ts = time.time()
                times  = self._recent_change_times.get(key, [])
                times  = [t for t in times if now_ts - t < config.change_spike_window]
                times.append(now_ts)
                self._recent_change_times[key] = times
                last_spike = self._last_spike_at.get(key, 0.0)
                if (
                    len(times) >= config.change_spike_threshold
                    and now_ts - last_spike > config.change_spike_window
                ):
                    self._last_spike_at[key] = now_ts
                    logger.warning(
                        "[%s] Change spike: %d changes in %ds",
                        config.label, len(times), config.change_spike_window,
                    )
                    if config.on_spike:
                        try:
                            config.on_spike(SpikeInfo(
                                url               = config.url,
                                label             = config.label or config.url,
                                changes_in_window = len(times),
                                window_seconds    = config.change_spike_window,
                            ))
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("[%s] on_spike callback error: %s", config.label, exc)

            # HTML archiving
            if config.archive_html and not config.dry_run:
                try:
                    store_dir   = getattr(self._store, "get_directory", lambda: Path(".watchdiff"))()
                    archive_dir = Path(store_dir) / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    import hashlib  # noqa: PLC0415
                    url_hash = hashlib.md5(config.url.encode()).hexdigest()[:8]
                    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    dest     = archive_dir / f"{url_hash}_{ts}.html"
                    dest.write_text(snapshot.raw_html or html, encoding="utf-8")
                    logger.debug("[%s] HTML archived: %s", config.label, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] HTML archive failed: %s", config.label, exc)

            # Screenshot on change
            if config.screenshot_on_change and config.browser and not config.dry_run:
                try:
                    if self._browser_fetcher is None:
                        from watchdiff.fetcher.browser import BrowserFetcher  # noqa: PLC0415
                        self._browser_fetcher = BrowserFetcher()
                    store_dir   = getattr(self._store, "get_directory", lambda: Path(".watchdiff"))()
                    archive_dir = Path(store_dir) / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    import hashlib  # noqa: PLC0415
                    url_hash = hashlib.md5(config.url.encode()).hexdigest()[:8]
                    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    dest     = archive_dir / f"{url_hash}_{ts}.png"
                    buf      = self._browser_fetcher.screenshot(config)
                    dest.write_bytes(buf)
                    logger.debug("[%s] Screenshot saved: %s", config.label, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] Screenshot failed: %s", config.label, exc)

            if self._cooldown_ok(config):
                for cb in self._on_diff_callbacks:
                    try:
                        cb(report)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Global callback error: %s", exc)

                if config.alert:
                    if not config.dry_run:
                        self._notifier.notify(report, config.alert)
                    else:
                        for cb in config.alert.on_change:
                            try:
                                cb(report)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("Alert callback error: %s", exc)

                self._last_alerted[key] = time.time()
            else:
                logger.debug(
                    "[%s] Change detected but cooldown active - alert suppressed.", config.label
                )
        else:
            logger.debug("[%s] No changes.", config.label)
            self._check_silence(config)

        return report

    def _check_silence(self, config: WatchConfig) -> None:
        if not config.alert_if_no_change_after or not config.on_silence:
            return
        key     = _cooldown_key(config)
        ref     = self._last_change_at.get(key) or self._watcher_start.get(key, time.time())
        elapsed = time.time() - ref
        if elapsed >= config.alert_if_no_change_after and not self._silence_fired.get(key, False):
            self._silence_fired[key] = True
            try:
                config.on_silence(SilenceInfo(
                    url                       = config.url,
                    label                     = config.label or config.url,
                    seconds_since_last_change = elapsed,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] on_silence callback error: %s", config.label, exc)

    def _handle_status_change(self, key: str, current_status: int, config: WatchConfig) -> None:
        prev = self._last_status_code.get(key, 0)
        self._last_status_code[key] = current_status

        if not config.alert_on_status_change or prev == 0 or prev == current_status:
            return

        label = (
            f"recovered ({prev} → 200)"
            if current_status == 200
            else f"{prev} → {current_status or 'unreachable'}"
        )
        logger.warning("[%s] HTTP status changed: %s", config.label, label)

        info = StatusChangeInfo(
            url             = config.url,
            label           = config.label or config.url,
            previous_status = prev,
            current_status  = current_status,
        )

        if config.on_status_change:
            try:
                config.on_status_change(info)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] on_status_change callback error: %s", config.label, exc)

        if not config.dry_run and config.alert:
            from watchdiff.models import Change, ChangeType, Snapshot  # noqa: PLC0415
            from datetime import datetime, timezone  # noqa: PLC0415
            now      = datetime.now(timezone.utc)
            empty    = Snapshot(url=config.url, target=config.target, content="", raw_html="")
            fake_report = DiffReport(
                url         = config.url,
                target      = config.target,
                label       = config.label or config.url,
                before      = empty,
                after       = empty,
                changes     = [Change(
                    kind    = ChangeType.MODIFIED,
                    before  = str(prev),
                    after   = str(current_status) if current_status else "unreachable",
                    context = "http_status",
                )],
                compared_at = now,
            )
            try:
                self._notifier.notify(fake_report, config.alert)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] Status change webhook error: %s", config.label, exc)

    def _cooldown_ok(self, config: WatchConfig) -> bool:
        if config.cooldown <= 0:
            return True
        elapsed = time.time() - self._last_alerted.get(_cooldown_key(config), _NEVER)
        return elapsed >= config.cooldown


class AsyncScheduler:
    """
    Asyncio-based scheduler.

    Use this inside async applications (FastAPI, aiohttp, etc.).
    """

    def __init__(self, store: Any) -> None:
        self._store                                                  = store
        self._fetcher                                                = AsyncFetcher()
        self._browser_fetcher: Any                                   = None  # lazy-init on first browser use
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []
        self._configs: list[WatchConfig]                             = []
        self._paused: set[str]                                       = set()
        self._last_alerted: dict[str, float]                         = {}
        self._last_check_at: dict[str, float]                        = {}
        self._next_check_at: dict[str, float]                        = {}
        self._last_change_at: dict[str, float]                       = {}
        self._watcher_start: dict[str, float]                        = {}
        self._checks_count: dict[str, int]                           = {}
        self._changes_count: dict[str, int]                          = {}
        self._errors_count: dict[str, int]                           = {}
        self._silence_fired: dict[str, bool]                         = {}
        self._recent_change_times: dict[str, list[float]]            = {}
        self._last_spike_at: dict[str, float]                        = {}
        self._last_status_code: dict[str, int]                       = {}

    def add_global_callback(self, callback: Callable[[DiffReport], None]) -> None:
        self._on_diff_callbacks.append(callback)

    async def start(self, configs: list[WatchConfig]) -> None:
        """Start all watchers as concurrent asyncio tasks."""
        self._configs = list(configs)
        tasks = [asyncio.create_task(self._run_loop(cfg)) for cfg in configs]
        await asyncio.gather(*tasks)

    def pause(self, url: str) -> None:
        """Suspend the watcher for a URL."""
        self._paused.add(url)
        logger.info("Paused watcher for %s", url)

    def resume(self, url: str) -> None:
        """Resume a paused watcher."""
        self._paused.discard(url)
        logger.info("Resumed watcher for %s", url)

    def status(self) -> list[WatcherStatus]:
        """Return a live status snapshot for all registered watchers."""
        result = []
        for config in self._configs:
            key         = _cooldown_key(config)
            last_check  = self._last_check_at.get(key)
            next_check  = self._next_check_at.get(key)
            last_change = self._last_change_at.get(key)
            result.append(WatcherStatus(
                url            = config.url,
                label          = config.label or config.url,
                target         = config.target,
                interval       = config.interval,
                paused         = config.url in self._paused,
                last_check_at  = datetime.fromtimestamp(last_check, tz=timezone.utc) if last_check else None,
                next_check_at  = datetime.fromtimestamp(next_check, tz=timezone.utc) if next_check else None,
                last_change_at = datetime.fromtimestamp(last_change, tz=timezone.utc) if last_change else None,
                checks_count      = self._checks_count.get(key, 0),
                changes_count     = self._changes_count.get(key, 0),
                errors_count      = self._errors_count.get(key, 0),
                last_status_code  = self._last_status_code.get(key, 0),
            ))
        return result

    async def check_once(self, config: WatchConfig) -> DiffReport | None:
        """Single async check."""
        return await self._check(config)

    async def _run_loop(self, config: WatchConfig) -> None:
        key = _cooldown_key(config)
        self._watcher_start[key]       = time.time()
        self._checks_count[key]        = 0
        self._changes_count[key]       = 0
        self._errors_count[key]        = 0
        self._silence_fired[key]       = False
        self._recent_change_times[key] = []
        self._last_spike_at[key]       = 0.0
        self._last_status_code[key]    = 0

        while True:
            if config.url not in self._paused:
                await self._check(config)

            effective = float(config.interval)
            if config.jitter > 0:
                delta     = config.interval * config.jitter * random.uniform(-1, 1)
                effective = max(1.0, effective + delta)

            self._next_check_at[key] = time.time() + effective
            await asyncio.sleep(effective)

    async def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to AsyncBrowserFetcher or AsyncFetcher based on config.browser."""
        if config.browser:
            if self._browser_fetcher is None:
                from watchdiff.fetcher.browser import AsyncBrowserFetcher  # noqa: PLC0415
                self._browser_fetcher = AsyncBrowserFetcher()
            return await self._browser_fetcher.fetch(config)
        return await self._fetcher.fetch(config)

    async def _check(self, config: WatchConfig) -> DiffReport | None:
        key = _cooldown_key(config)
        self._checks_count[key]  = self._checks_count.get(key, 0) + 1
        self._last_check_at[key] = time.time()

        extra_patterns = list(config.ignore_patterns)
        if config.ignore_numbers:
            extra_patterns.append(r"\b\d+(\.\d+)?\b")

        try:
            html = await self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            current_status = getattr(exc, "status_code", 0)
            await self._handle_status_change(key, current_status, config)
            if config.on_error:
                try:
                    config.on_error(exc, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[%s] on_error callback error: %s", config.label, cb_exc)
            return None

        await self._handle_status_change(key, 200, config)

        cleaner = Cleaner(
            extra_selectors = config.ignore_selectors,
            extra_patterns  = extra_patterns,
        )
        soup = cleaner.clean(html)

        try:
            snapshot = self._parser.extract(soup, config)
        except ParserError as exc:
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            logger.error("[%s] Parse failed: %s", config.label, exc)
            return None

        previous = self._store.load_latest(config.url, config.target)

        if previous is None:
            if not config.dry_run:
                self._store.save_snapshot(snapshot)
            logger.info("[%s] First snapshot captured.", config.label)
            return None

        report = self._engine.compare(previous, snapshot, config)

        if not config.dry_run:
            self._store.save_snapshot(snapshot)
            if config.max_snapshots and hasattr(self._store, "prune_snapshots"):
                self._store.prune_snapshots(config.url, config.target, config.max_snapshots)

        if report.has_changes:
            if config.change_threshold is not None:
                before_len = max(len(previous.content), 1)
                changed    = sum(
                    max(len(c.before or ""), len(c.after or ""))
                    for c in report.changes
                )
                if (changed / before_len) < config.change_threshold:
                    logger.debug(
                        "[%s] Change ratio %.3f below threshold %.3f - skipped.",
                        config.label, changed / before_len, config.change_threshold,
                    )
                    return report

            if not config.dry_run:
                self._store.save_report(report)

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = time.time()
            self._silence_fired[key]  = False
            logger.info("[%s] %s", config.label, report.summary())

            # Spike detection
            if config.change_spike_window and config.change_spike_threshold:
                now_ts = time.time()
                times  = self._recent_change_times.get(key, [])
                times  = [t for t in times if now_ts - t < config.change_spike_window]
                times.append(now_ts)
                self._recent_change_times[key] = times
                last_spike = self._last_spike_at.get(key, 0.0)
                if (
                    len(times) >= config.change_spike_threshold
                    and now_ts - last_spike > config.change_spike_window
                ):
                    self._last_spike_at[key] = now_ts
                    logger.warning(
                        "[%s] Change spike: %d changes in %ds",
                        config.label, len(times), config.change_spike_window,
                    )
                    if config.on_spike:
                        try:
                            config.on_spike(SpikeInfo(
                                url               = config.url,
                                label             = config.label or config.url,
                                changes_in_window = len(times),
                                window_seconds    = config.change_spike_window,
                            ))
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("[%s] on_spike callback error: %s", config.label, exc)

            # HTML archiving
            if config.archive_html and not config.dry_run:
                try:
                    import hashlib  # noqa: PLC0415
                    store_dir   = getattr(self._store, "get_directory", lambda: Path(".watchdiff"))()
                    archive_dir = Path(store_dir) / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    url_hash = hashlib.md5(config.url.encode()).hexdigest()[:8]
                    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    dest     = archive_dir / f"{url_hash}_{ts}.html"
                    dest.write_text(snapshot.raw_html or html, encoding="utf-8")
                    logger.debug("[%s] HTML archived: %s", config.label, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] HTML archive failed: %s", config.label, exc)

            # Screenshot on change
            if config.screenshot_on_change and config.browser and not config.dry_run:
                try:
                    import hashlib  # noqa: PLC0415
                    if self._browser_fetcher is None:
                        from watchdiff.fetcher.browser import AsyncBrowserFetcher  # noqa: PLC0415
                        self._browser_fetcher = AsyncBrowserFetcher()
                    store_dir   = getattr(self._store, "get_directory", lambda: Path(".watchdiff"))()
                    archive_dir = Path(store_dir) / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    url_hash = hashlib.md5(config.url.encode()).hexdigest()[:8]
                    ts       = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    dest     = archive_dir / f"{url_hash}_{ts}.png"
                    buf      = await self._browser_fetcher.screenshot(config)
                    dest.write_bytes(buf)
                    logger.debug("[%s] Screenshot saved: %s", config.label, dest)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] Screenshot failed: %s", config.label, exc)

            if self._cooldown_ok(config):
                for cb in self._on_diff_callbacks:
                    try:
                        cb(report)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Global callback error: %s", exc)

                if config.alert:
                    if not config.dry_run:
                        self._notifier.notify(report, config.alert)
                    else:
                        for cb in config.alert.on_change:
                            try:
                                cb(report)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("Alert callback error: %s", exc)

                self._last_alerted[key] = time.time()
            else:
                logger.debug(
                    "[%s] Change detected but cooldown active - alert suppressed.", config.label
                )
        else:
            logger.debug("[%s] No changes.", config.label)
            self._check_silence(config)

        return report

    def _check_silence(self, config: WatchConfig) -> None:
        if not config.alert_if_no_change_after or not config.on_silence:
            return
        key     = _cooldown_key(config)
        ref     = self._last_change_at.get(key) or self._watcher_start.get(key, time.time())
        elapsed = time.time() - ref
        if elapsed >= config.alert_if_no_change_after and not self._silence_fired.get(key, False):
            self._silence_fired[key] = True
            try:
                config.on_silence(SilenceInfo(
                    url                       = config.url,
                    label                     = config.label or config.url,
                    seconds_since_last_change = elapsed,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] on_silence callback error: %s", config.label, exc)

    async def _handle_status_change(self, key: str, current_status: int, config: WatchConfig) -> None:
        prev = self._last_status_code.get(key, 0)
        self._last_status_code[key] = current_status

        if not config.alert_on_status_change or prev == 0 or prev == current_status:
            return

        label = (
            f"recovered ({prev} → 200)"
            if current_status == 200
            else f"{prev} → {current_status or 'unreachable'}"
        )
        logger.warning("[%s] HTTP status changed: %s", config.label, label)

        info = StatusChangeInfo(
            url             = config.url,
            label           = config.label or config.url,
            previous_status = prev,
            current_status  = current_status,
        )

        if config.on_status_change:
            try:
                config.on_status_change(info)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] on_status_change callback error: %s", config.label, exc)

        if not config.dry_run and config.alert:
            from watchdiff.models import Change, ChangeType, Snapshot  # noqa: PLC0415
            from datetime import datetime, timezone  # noqa: PLC0415
            now      = datetime.now(timezone.utc)
            empty    = Snapshot(url=config.url, target=config.target, content="", raw_html="")
            fake_report = DiffReport(
                url         = config.url,
                target      = config.target,
                label       = config.label or config.url,
                before      = empty,
                after       = empty,
                changes     = [Change(
                    kind    = ChangeType.MODIFIED,
                    before  = str(prev),
                    after   = str(current_status) if current_status else "unreachable",
                    context = "http_status",
                )],
                compared_at = now,
            )
            try:
                self._notifier.notify(fake_report, config.alert)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] Status change webhook error: %s", config.label, exc)

    def _cooldown_ok(self, config: WatchConfig) -> bool:
        if config.cooldown <= 0:
            return True
        elapsed = time.time() - self._last_alerted.get(_cooldown_key(config), _NEVER)
        return elapsed >= config.cooldown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cooldown_key(config: WatchConfig) -> str:
    return f"{config.url}::{config.target or ''}"
