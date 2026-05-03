"""
Scheduler - drives the periodic check loop.

Two implementations:
  - SyncScheduler: blocking loop using threading.Timer, suitable for scripts.
  - AsyncScheduler: asyncio-based loop for async applications.

Both call the same internal pipeline:
  Fetcher → Cleaner → Parser → DiffEngine → Store → Notifier
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable

from watchdiff.cleaner import Cleaner
from watchdiff.diff import DiffEngine
from watchdiff.fetcher import AsyncFetcher, FetchError, Fetcher
from watchdiff.models import DiffReport, WatchConfig
from watchdiff.notifier import Notifier
from watchdiff.parser import Parser, ParserError
from watchdiff.store import Store

logger = logging.getLogger(__name__)


class SyncScheduler:
    """
    Blocking multi-threaded scheduler.

    Each WatchConfig runs in its own daemon thread with an independent
    sleep interval, so different URLs can have different cadences.
    """

    def __init__(self, store: Store) -> None:
        self._store                                                 = store
        self._fetcher                                               = Fetcher()
        self._parser                                                = Parser()
        self._engine                                                = DiffEngine()
        self._notifier                                              = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []
        self._threads: list[threading.Thread]                       = []
        self._stop_events: list[threading.Event]                    = []

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
                target      = self._run_loop,
                args        = (config, stop_event),
                daemon      = True,
                name        = f"watchdiff-{config.label}",
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
        logger.info("Stopping all watchers…")

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

    def _check(self, config: WatchConfig) -> DiffReport | None:
        try:
            html = self._fetcher.fetch(config)
        except FetchError as exc:
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            return None

        cleaner = Cleaner(
            extra_selectors=config.ignore_selectors,
            extra_patterns=config.ignore_patterns,
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

            # Global callbacks
            for cb in self._on_diff_callbacks:
                try:
                    cb(report)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Global callback error: %s", exc)

            # Per-config alert
            if config.alert:
                self._notifier.notify(report, config.alert)
        else:
            logger.debug("[%s] No changes.", config.label)

        return report


class AsyncScheduler:
    """
    Asyncio-based scheduler.

    Use this inside async applications (FastAPI, aiohttp, etc.).
    """

    def __init__(self, store: Store) -> None:
        self._store                                                 = store
        self._fetcher                                               = AsyncFetcher()
        self._parser                                                = Parser()
        self._engine                                                = DiffEngine()
        self._notifier                                              = Notifier()
        self._on_diff_callbacks: list[Callable[[DiffReport], None]] = []

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

    async def _check(self, config: WatchConfig) -> DiffReport | None:
        try:
            html = await self._fetcher.fetch(config)
        except FetchError as exc:
            logger.error("[%s] Fetch failed: %s", config.label, exc)
            return None

        cleaner = Cleaner(
            extra_selectors=config.ignore_selectors,
            extra_patterns=config.ignore_patterns,
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
            for cb in self._on_diff_callbacks:
                try:
                    cb(report)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Global callback error: %s", exc)
            if config.alert:
                self._notifier.notify(report, config.alert)

        return report