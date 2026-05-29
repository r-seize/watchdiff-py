"""
WatchDiff - high-level public facade.

Usage:
    from watchdiff import WatchDiff

    # Default JSON store
    wd = WatchDiff()
    wd.watch("https://example.com/product", target=".price", interval=300)
    wd.on_change(lambda report: print(report.summary()))
    wd.start()

    # SQLite store
    from watchdiff.store import SqliteStore
    wd = WatchDiff(store=SqliteStore(".watchdiff.db"))

    # Browser (JS-rendered pages)
    from watchdiff.models import BrowserOptions
    wd.watch("https://spa.example.com", browser=True,
             browser_options=BrowserOptions(wait_for="networkidle"))

    # Pause / resume / status
    wd.start(block=False)
    wd.pause("https://example.com/product")
    wd.resume("https://example.com/product")
    print(wd.status())

    # Export
    wd.export_reports_csv("https://example.com", dest="out.csv")
    wd.export_reports_xlsx("https://example.com", dest="out.xlsx")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from watchdiff.models import (
    AlertConfig,
    BrowserOptions,
    DiffReport,
    SilenceInfo,
    WatchConfig,
    WatcherStatus,
)
from watchdiff.scheduler import AsyncScheduler, SyncScheduler
from watchdiff.store import Store

logger = logging.getLogger(__name__)


class WatchDiff:
    """
    Main entry point for WatchDiff.

    All configuration methods are chainable.
    """

    def __init__(
        self,
        storage_dir: str | Path = ".watchdiff",
        store: Any | None = None,
    ) -> None:
        """
        Args:
            storage_dir: Directory for the default JSON store (ignored when store is given).
            store:       Custom store instance - Store, SqliteStore, or any compatible object.
                         When provided, storage_dir is ignored.
        """
        self._store: Any                                          = store if store is not None else Store(storage_dir)
        self._configs: list[WatchConfig]                          = []
        self._global_callbacks: list[Callable[[DiffReport], None]] = []
        self._scheduler: SyncScheduler | None                     = None
        self._async_scheduler: AsyncScheduler | None              = None

    # ------------------------------------------------------------------
    # Configuration API
    # ------------------------------------------------------------------

    def watch(
        self,
        url: str,
        *,
        target: str | None                                                                    = None,
        interval: int                                                                         = 300,
        label: str | None                                                                     = None,
        headers: dict[str, str] | None                                                        = None,
        timeout: int                                                                          = 15,
        ignore_selectors: list[str] | None                                                    = None,
        ignore_patterns: list[str] | None                                                     = None,
        on_change: Callable[[DiffReport], None] | list[Callable[[DiffReport], None]] | None  = None,
        webhooks: list[str] | None                                                            = None,
        min_changes: int                                                                      = 1,
        diff_mode: str                                                                        = "line",
        browser: bool                                                                         = False,
        browser_options: BrowserOptions | None                                                = None,
        proxies: list[str] | None                                                             = None,
        user_agents: list[str] | None                                                         = None,
        cooldown: int                                                                         = 0,
        retries: int                                                                          = 0,
        retry_delay: float                                                                    = 1.0,
        jitter: float                                                                         = 0.0,
        dry_run: bool                                                                         = False,
        max_snapshots: int | None                                                             = None,
        change_threshold: float | None                                                        = None,
        ignore_numbers: bool                                                                  = False,
        alert_if_no_change_after: int | None                                                  = None,
        on_error: Callable[[Exception, WatchConfig], None] | None                             = None,
        on_silence: Callable[[SilenceInfo], None] | None                                      = None,
    ) -> WatchDiff:
        """
        Register a URL to monitor.

        Args:
            url:                      URL to watch.
            target:                   CSS selector or XPath to narrow monitoring.
                                      None means full page.
            interval:                 Seconds between checks (default 300).
            label:                    Human-readable name shown in logs and reports.
            headers:                  Extra HTTP headers for this URL.
            timeout:                  HTTP request timeout in seconds.
            ignore_selectors:         CSS selectors to strip before diffing.
            ignore_patterns:          Regex patterns to strip from text before diffing.
            on_change:                Callback(s) called with a DiffReport on each change.
            webhooks:                 Webhook URLs (Discord/Slack/Telegram/etc.) to POST on change.
            min_changes:              Alert only if at least N changes are detected.
            diff_mode:                "line" | "semantic" | "word" | "json".
            browser:                  Use Playwright headless browser instead of httpx.
                                      Requires: pip install "watchdiff-core[browser]"
            browser_options:          BrowserOptions for fine-tuning Playwright behaviour.
            proxies:                  Proxy URLs - one picked randomly per request.
            user_agents:              User-Agent strings - one picked randomly per request.
            cooldown:                 Min seconds between two alerts for this URL (0 = disabled).
            retries:                  HTTP retry attempts on transient errors (429, 5xx).
            retry_delay:              Base delay in seconds for exponential backoff.
            jitter:                   Fraction 0-1: interval ± interval*jitter*rand (min 1s).
            dry_run:                  Fetch+diff without saving or sending webhooks.
                                      on_change callbacks still fire.
            max_snapshots:            Prune history to this many entries after each save.
            change_threshold:         Min changed/total ratio to trigger alert (0 = disabled).
            ignore_numbers:           Strip all digit tokens before diffing.
            alert_if_no_change_after: Fire on_silence if no change detected for N seconds.
            on_error:                 Callback invoked with (exc, config) when a fetch fails.
            on_silence:               Callback invoked with a SilenceInfo when silence threshold
                                      is exceeded.

        Returns:
            self (chainable)
        """
        callbacks: list[Callable[[DiffReport], None]] = []
        if on_change:
            callbacks = on_change if isinstance(on_change, list) else [on_change]

        alert = AlertConfig(
            on_change   = callbacks,
            webhooks    = webhooks or [],
            min_changes = min_changes,
        ) if (callbacks or webhooks) else None

        config = WatchConfig(
            url                      = url,
            target                   = target,
            interval                 = interval,
            label                    = label,
            headers                  = headers or {},
            timeout                  = timeout,
            ignore_selectors         = ignore_selectors or [],
            ignore_patterns          = ignore_patterns or [],
            alert                    = alert,
            diff_mode                = diff_mode,
            browser                  = browser,
            browser_options          = browser_options,
            proxies                  = proxies or [],
            user_agents              = user_agents or [],
            cooldown                 = cooldown,
            retries                  = retries,
            retry_delay              = retry_delay,
            jitter                   = jitter,
            dry_run                  = dry_run,
            max_snapshots            = max_snapshots,
            change_threshold         = change_threshold,
            ignore_numbers           = ignore_numbers,
            alert_if_no_change_after = alert_if_no_change_after,
            on_error                 = on_error,
            on_silence               = on_silence,
        )
        self._configs.append(config)
        return self

    def on_change(self, callback: Callable[[DiffReport], None]) -> WatchDiff:
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
        self._scheduler = scheduler
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
        self._async_scheduler = scheduler
        for cb in self._global_callbacks:
            scheduler.add_global_callback(cb)

        await scheduler.start(self._configs)

    def check_once(self, url: str) -> DiffReport | None:
        """
        Run a single immediate check for a registered URL.

        Args:
            url: URL to check (must have been registered via .watch()).

        Returns:
            DiffReport or None if it is the first check.

        Raises:
            ValueError: if the URL is not registered.
        """
        config    = self._find_config(url)
        scheduler = SyncScheduler(self._store)
        for cb in self._global_callbacks:
            scheduler.add_global_callback(cb)
        return scheduler.check_once(config)

    # ------------------------------------------------------------------
    # Pause / resume / status API
    # ------------------------------------------------------------------

    def pause(self, url: str) -> None:
        """
        Pause the watcher for a URL.

        Checks are skipped until resume() is called. Changes are not stored
        while paused.

        Args:
            url: URL previously registered via .watch().

        Raises:
            RuntimeError: if the scheduler is not running.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not running. Call .start(block=False) first.")
        self._scheduler.pause(url)

    def resume(self, url: str) -> None:
        """
        Resume a paused watcher.

        Args:
            url: URL previously registered via .watch().

        Raises:
            RuntimeError: if the scheduler is not running.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not running. Call .start(block=False) first.")
        self._scheduler.resume(url)

    def status(self) -> list[WatcherStatus]:
        """
        Return live status for all registered watchers.

        Returns an empty list if the scheduler has not been started.
        """
        if self._scheduler is None:
            return []
        return self._scheduler.status()

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
    # Export API
    # ------------------------------------------------------------------

    def export_snapshots_csv(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path | None = None,
    ) -> str:
        """
        Export snapshots to CSV.

        Args:
            url:    URL (must have been registered via .watch() or have stored data).
            target: CSS selector / XPath filter (None for full page).
            limit:  Maximum rows to include.
            dest:   File path to write CSV to (also returns the string).

        Returns:
            CSV string.
        """
        from watchdiff.exporter import Exporter  # noqa: PLC0415
        return Exporter(self._store).snapshots_csv(url, target, limit=limit, dest=dest)

    def export_reports_csv(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path | None = None,
    ) -> str:
        """
        Export diff reports to CSV.

        Returns:
            CSV string.
        """
        from watchdiff.exporter import Exporter  # noqa: PLC0415
        return Exporter(self._store).reports_csv(url, target, limit=limit, dest=dest)

    def export_snapshots_xlsx(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path = "snapshots.xlsx",
    ) -> Path:
        """
        Export snapshots to XLSX (requires openpyxl).

        Returns:
            Path to the written file.
        """
        from watchdiff.exporter import Exporter  # noqa: PLC0415
        return Exporter(self._store).snapshots_xlsx(url, target, limit=limit, dest=dest)

    def export_reports_xlsx(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path = "reports.xlsx",
    ) -> Path:
        """
        Export diff reports to XLSX (requires openpyxl).

        Returns:
            Path to the written file.
        """
        from watchdiff.exporter import Exporter  # noqa: PLC0415
        return Exporter(self._store).reports_xlsx(url, target, limit=limit, dest=dest)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_config(self, url: str) -> WatchConfig:
        for config in self._configs:
            if config.url == url:
                return config
        raise ValueError(f"URL not registered: {url!r}. Call .watch() first.")
