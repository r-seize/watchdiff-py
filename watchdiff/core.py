"""
WatchDiff - high-level public facade.

This is what 99% of users will interact with.

Usage:
    from watchdiff import WatchDiff

    wd = WatchDiff()
    wd.watch("https://example.com/product", target=".price", interval=300)
    wd.on_change(lambda report: print(report.summary()))
    wd.start()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from watchdiff.models import AlertConfig, DiffReport, WatchConfig
from watchdiff.scheduler import AsyncScheduler, SyncScheduler
from watchdiff.store import Store

logger = logging.getLogger(__name__)


class WatchDiff:
    """
    Main entry point for WatchDiff.

    All methods are chainable.
    """

    def __init__(self, storage_dir: str | Path = ".watchdiff") -> None:
        self._store = Store(storage_dir)
        self._configs: list[WatchConfig] = []
        self._global_callbacks: list[Callable[[DiffReport], None]] = []

    # ------------------------------------------------------------------
    # Configuration API
    # ------------------------------------------------------------------

    def watch(
        self,
        url: str,
        *,
        target: str | None                                                                  = None,
        interval: int                                                                       = 300,
        label: str | None                                                                   = None,
        headers: dict[str, str] | None                                                      = None,
        timeout: int                                                                        = 15,
        ignore_selectors: list[str] | None                                                  = None,
        ignore_patterns: list[str] | None                                                   = None,
        on_change: Callable[[DiffReport], None] | list[Callable[[DiffReport], None]] | None = None,
        webhooks: list[str] | None                                                          = None,
        min_changes: int                                                                    = 1,
    ) -> "WatchDiff":
        """
        Register a URL to monitor.

        Args:
            url:              URL to watch.
            target:           CSS selector to narrow monitoring (e.g. ".price").
                              If None, the full page body is monitored.
            interval:         Seconds between checks (default 300 = 5 min).
            label:            Human-readable name shown in logs and reports.
            headers:          Extra HTTP headers for this URL.
            timeout:          HTTP request timeout in seconds.
            ignore_selectors: CSS selectors to strip before diffing.
            ignore_patterns:  Regex patterns to strip from text before diffing.
            on_change:        Callback(s) called with a DiffReport on each change.
            webhooks:         Webhook URLs (Discord/Slack/custom) to POST on change.
            min_changes:      Alert only if at least N changes are detected.

        Returns:
            self (chainable)
        """
        callbacks = []
        if on_change:
            callbacks = on_change if isinstance(on_change, list) else [on_change]

        alert = AlertConfig(
            on_change           = callbacks,
            webhooks            = webhooks or [],
            min_changes         = min_changes,
        ) if (callbacks or webhooks) else None

        config = WatchConfig(
            url                 = url,
            target              = target,
            interval            = interval,
            label               = label,
            headers             = headers or {},
            timeout             = timeout,
            ignore_selectors    = ignore_selectors or [],
            ignore_patterns     = ignore_patterns or [],
            alert               = alert,
        )
        self._configs.append(config)
        return self

    def on_change(self, callback: Callable[[DiffReport], None]) -> "WatchDiff":
        """
        Register a global callback called whenever ANY watched URL changes.

        Args:
            callback: Function receiving a DiffReport.

        Returns:
            self (chainable)
        """
        self._global_callbacks.append(callback)
        return self

    # ------------------------------------------------------------------
    # Run API
    # ------------------------------------------------------------------

    def start(self, block: bool = True) -> None:
        """
        Start the synchronous scheduler.

        Args:
            block: If True (default), blocks until Ctrl+C.
                   If False, returns immediately (threads run as daemons).
        """
        if not self._configs:
            logger.warning("No URLs registered. Call .watch() first.")
            return

        scheduler = SyncScheduler(self._store)
        for cb in self._global_callbacks:
            scheduler.add_global_callback(cb)

        scheduler.start(self._configs, block=block)

    async def start_async(self) -> None:
        """
        Start the async scheduler.

        Use with `asyncio.run(wd.start_async())` or inside an existing event loop.
        """
        if not self._configs:
            logger.warning("No URLs registered. Call .watch() first.")
            return

        scheduler = AsyncScheduler(self._store)
        for cb in self._global_callbacks:
            scheduler.add_global_callback(cb)

        await scheduler.start(self._configs)

    def check_once(self, url: str) -> DiffReport | None:
        """
        Run a single immediate check for a registered URL.

        Useful for testing or on-demand checks without the scheduler loop.

        Args:
            url: URL to check (must have been registered via .watch()).

        Returns:
            DiffReport or None if it's the first check.

        Raises:
            ValueError: if the URL is not registered.
        """
        config      = self._find_config(url)
        scheduler   = SyncScheduler(self._store)
        for cb in self._global_callbacks:
            scheduler.add_global_callback(cb)
        return scheduler.check_once(config)

    # ------------------------------------------------------------------
    # History / audit API
    # ------------------------------------------------------------------

    def history(self, url: str, limit: int = 20) -> list:
        """Return stored snapshots for a URL."""
        config = self._find_config(url)
        return self._store.load_history(config.url, config.target, limit=limit)

    def reports(self, url: str, limit: int = 20) -> list[dict]:
        """Return stored diff reports for a URL."""
        config = self._find_config(url)
        return self._store.load_reports(config.url, config.target, limit=limit)

    def clear(self, url: str) -> None:
        """Delete all stored snapshots and reports for a URL."""
        config = self._find_config(url)
        self._store.clear_history(config.url, config.target)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_config(self, url: str) -> WatchConfig:
        for config in self._configs:
            if config.url == url:
                return config
        raise ValueError(f"URL not registered: {url!r}. Call .watch() first.")