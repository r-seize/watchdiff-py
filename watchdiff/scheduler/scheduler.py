"""
Scheduler - drives the periodic check loop.

Two implementations:
  - SyncScheduler:  blocking loop using threading, suitable for scripts.
  - AsyncScheduler: asyncio-based loop for async applications.

Both call the same internal pipeline:
  Fetcher (or BrowserFetcher) - Cleaner - Parser - DiffEngine - Store - Notifier
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable

from watchdiff.cleaner import Cleaner
from watchdiff.diff import DiffEngine
from watchdiff.fetcher import AsyncFetcher, Fetcher
from watchdiff.models import DiffReport, WatchConfig
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
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []
        self._threads: list[threading.Thread]                        = []
        self._stop_events: list[threading.Event]                     = []
        self._last_alerted: dict[str, float]                         = {}  # cooldown tracking

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

    def check_once(self, config: WatchConfig) -> DiffReport | None:
        """Run a single check for a config and return the DiffReport."""
        return self._check(config)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self, config: WatchConfig, stop_event: threading.Event) -> None:
        """Thread target: check, sleep, repeat."""
        while not stop_event.is_set():
            self._check(config)
            stop_event.wait(timeout=config.interval)

    def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to BrowserFetcher or Fetcher based on config.browser."""
        if config.browser:
            from watchdiff.fetcher.browser import BrowserFetcher  # noqa: PLC0415
            return BrowserFetcher().fetch(config)
        return self._fetcher.fetch(config)

    def _check(self, config: WatchConfig) -> DiffReport | None:
        try:
            html = self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            return None

        cleaner = Cleaner(
            extra_selectors = config.ignore_selectors,
            extra_patterns  = config.ignore_patterns,
        )
        soup = cleaner.clean(html)

        try:
            snapshot = self._parser.extract(soup, config)
        except ParserError as exc:
            logger.error("[%s] Parse failed: %s", config.label, exc)
            return None

        previous = self._store.load_latest(config.url, config.target)

        if previous is None:
            # First run - just save and return
            self._store.save_snapshot(snapshot)
            logger.info("[%s] First snapshot captured.", config.label)
            return None

        report = self._engine.compare(previous, snapshot, config)
        self._store.save_snapshot(snapshot)

        if report.has_changes:
            self._store.save_report(report)
            logger.info("[%s] %s", config.label, report.summary())

            if self._cooldown_ok(config):
                for cb in self._on_diff_callbacks:
                    try:
                        cb(report)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Global callback error: %s", exc)

                if config.alert:
                    self._notifier.notify(report, config.alert)

                self._last_alerted[_cooldown_key(config)] = time.time()
            else:
                logger.debug("[%s] Change detected but cooldown active - alert suppressed.", config.label)
        else:
            logger.debug("[%s] No changes.", config.label)

        return report

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
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []
        self._last_alerted: dict[str, float]                         = {}  # cooldown tracking

    def add_global_callback(self, callback: Callable[[DiffReport], None]) -> None:
        self._on_diff_callbacks.append(callback)

    async def start(self, configs: list[WatchConfig]) -> None:
        """Start all watchers as concurrent asyncio tasks."""
        tasks = [asyncio.create_task(self._run_loop(cfg)) for cfg in configs]
        await asyncio.gather(*tasks)

    async def check_once(self, config: WatchConfig) -> DiffReport | None:
        """Single async check."""
        return await self._check(config)

    async def _run_loop(self, config: WatchConfig) -> None:
        while True:
            await self._check(config)
            await asyncio.sleep(config.interval)

    async def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to AsyncBrowserFetcher or AsyncFetcher based on config.browser."""
        if config.browser:
            from watchdiff.fetcher.browser import AsyncBrowserFetcher  # noqa: PLC0415
            return await AsyncBrowserFetcher().fetch(config)
        return await self._fetcher.fetch(config)

    async def _check(self, config: WatchConfig) -> DiffReport | None:
        try:
            html = await self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            return None

        cleaner = Cleaner(
            extra_selectors = config.ignore_selectors,
            extra_patterns  = config.ignore_patterns,
        )
        soup = cleaner.clean(html)

        try:
            snapshot = self._parser.extract(soup, config)
        except ParserError as exc:
            logger.error("[%s] Parse failed: %s", config.label, exc)
            return None

        previous = self._store.load_latest(config.url, config.target)

        if previous is None:
            self._store.save_snapshot(snapshot)
            logger.info("[%s] First snapshot captured.", config.label)
            return None

        report = self._engine.compare(previous, snapshot, config)
        self._store.save_snapshot(snapshot)

        if report.has_changes:
            self._store.save_report(report)

            if self._cooldown_ok(config):
                for cb in self._on_diff_callbacks:
                    try:
                        cb(report)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Global callback error: %s", exc)
                if config.alert:
                    self._notifier.notify(report, config.alert)
                self._last_alerted[_cooldown_key(config)] = time.time()
            else:
                logger.debug("[%s] Change detected but cooldown active - alert suppressed.", config.label)

        return report

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
