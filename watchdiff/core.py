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
    SpikeInfo,
    StatusChangeInfo,
    WatchConfig,
    WatcherStatus,
)
from watchdiff.scheduler import AsyncScheduler, SyncScheduler
from watchdiff.store import Store

logger = logging.getLogger(__name__)

_UNSET = object()


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
        self._store: Any                                           = store if store is not None else Store(storage_dir)
        self._configs: list[WatchConfig]                           = []
        self._db_configs: list[Any]                                = []
        self._cert_configs: list[Any]                              = []
        self._global_callbacks: list[Callable[[DiffReport], None]] = []
        self._scheduler: SyncScheduler | None                      = None
        self._async_scheduler: AsyncScheduler | None               = None
        self._db_scheduler: Any | None                             = None
        self._async_db_scheduler: Any | None                       = None
        self._cert_scheduler: Any | None                           = None
        self._status_server: Any | None                            = None

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
        webhook_retries: int                                                                  = 3,
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
        archive_html: bool                                                                     = False,
        screenshot_on_change: bool                                                             = False,
        change_spike_window: int | None                                                        = None,
        change_spike_threshold: int | None                                                     = None,
        on_spike: Callable[[SpikeInfo], None] | None                                          = None,
        alert_on_status_change: bool                                                           = False,
        on_status_change: Callable[[StatusChangeInfo], None] | None                           = None,
        alert_if: Callable[[DiffReport], bool] | None                                         = None,
        ai_summary: bool                                                                       = False,
        ai_provider: Any | None                                                                = None,
        is_file: bool                                                                          = False,
        expected_status: int | None                                                            = None,
        track_response_time: bool                                                              = False,
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
            diff_mode:                "line" | "semantic" | "word" | "json" | "rss".
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
            on_change       = callbacks,
            webhooks        = webhooks or [],
            min_changes     = min_changes,
            webhook_retries = webhook_retries,
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
            archive_html             = archive_html,
            screenshot_on_change     = screenshot_on_change,
            change_spike_window      = change_spike_window,
            change_spike_threshold   = change_spike_threshold,
            on_spike                 = on_spike,
            alert_on_status_change   = alert_on_status_change,
            on_status_change         = on_status_change,
            alert_if                 = alert_if,
            ai_summary               = ai_summary,
            ai_provider              = ai_provider,
            is_file                  = is_file,
            expected_status          = expected_status,
            track_response_time      = track_response_time,
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

    def watch_db(
        self,
        connection_string: str,
        table: str,
        *,
        diff_mode: str                                    = "row",
        interval: int                                     = 60,
        label: str | None                                 = None,
        query: str | None                                 = None,
        primary_key: list[str] | None                     = None,
        ignore_columns: list[str] | None                  = None,
        alert_on_insert: bool                             = True,
        alert_on_delete: bool                             = True,
        alert_on_update: bool                             = True,
        threshold: float | None                           = None,
        cooldown: float                                   = 0.0,
        dry_run: bool                                     = False,
        max_snapshots: int | None                         = None,
        webhooks: list[str] | None                        = None,
        webhook_retries: int                              = 3,
        on_change: Callable[[Any], None] | None           = None,
        on_schema_change: Callable[[Any], None] | None    = None,
        on_threshold: Callable[[Any], None] | None        = None,
        on_error: Callable[[Exception, Any], None] | None = None,
        ai_summary: bool                                  = False,
        ai_provider: Any | None                           = None,
    ) -> WatchDiff:
        """
        Register a database table to monitor.

        Args:
            connection_string: DB URL: ``sqlite:///app.db``, ``postgresql://user:pass@host/db``,
                               or ``mysql://user:pass@host/db``.
            table:             Table name to watch (also used in ``query`` placeholder).
            diff_mode:         ``"row"`` | ``"schema"`` | ``"aggregate"`` | ``"value"``.
            interval:          Seconds between checks (default 60).
            label:             Human-readable name shown in logs and reports.
            query:             Custom SQL query; overrides the default ``SELECT * FROM <table>``.
            primary_key:       Column(s) used as row identity in ``row`` mode.
            ignore_columns:    Columns to exclude from row comparison.
            alert_on_insert:   Fire alert when rows are inserted (default True).
            alert_on_delete:   Fire alert when rows are deleted (default True).
            alert_on_update:   Fire alert when rows are updated (default True).
            threshold:         Minimum % change to alert in ``aggregate`` mode (0 = any change).
            cooldown:          Min seconds between two alerts (0 = disabled).
            dry_run:           Fetch+diff without saving or dispatching alerts.
            max_snapshots:     Prune history to this many entries after each save.
            webhooks:          Webhook URLs to POST on change.
            webhook_retries:   Number of retry attempts per webhook.
            on_change:         Callback receiving a ``DbDiffReport`` on each change.
            on_schema_change:  Callback receiving a ``SchemaChangeInfo`` on schema change.
            on_threshold:      Callback receiving a ``ThresholdInfo`` when threshold exceeded.
            on_error:          Callback receiving ``(exc, config)`` on fetch/diff error.

        Returns:
            self (chainable)
        """
        from watchdiff.db_models import make_db_watch_config  # noqa: PLC0415
        config = make_db_watch_config(
            connection_string,
            table,
            diff_mode       = diff_mode,
            interval        = interval,
            label           = label,
            query           = query,
            primary_key     = primary_key,
            ignore_columns  = ignore_columns,
            alert_on_insert = alert_on_insert,
            alert_on_delete = alert_on_delete,
            alert_on_update = alert_on_update,
            threshold       = threshold,
            cooldown        = cooldown,
            dry_run         = dry_run,
            max_snapshots   = max_snapshots,
            webhooks        = webhooks or [],
            webhook_retries = webhook_retries,
            on_change        = on_change,
            on_schema_change = on_schema_change,
            on_threshold     = on_threshold,
            on_error         = on_error,
            ai_summary       = ai_summary,
            ai_provider      = ai_provider,
        )
        self._db_configs.append(config)
        return self

    def watch_file(
        self,
        path: str,
        *,
        interval: int                                                                          = 60,
        label: str | None                                                                      = None,
        diff_mode: str                                                                         = "line",
        ignore_patterns: list[str] | None                                                      = None,
        cooldown: int                                                                          = 0,
        dry_run: bool                                                                          = False,
        max_snapshots: int | None                                                              = None,
        change_threshold: float | None                                                         = None,
        ignore_numbers: bool                                                                   = False,
        on_change: Callable[[DiffReport], None] | list[Callable[[DiffReport], None]] | None   = None,
        webhooks: list[str] | None                                                             = None,
        webhook_retries: int                                                                   = 3,
        alert_if: Callable[[DiffReport], bool] | None                                         = None,
        ai_summary: bool                                                                       = False,
        ai_provider: Any | None                                                                = None,
        on_error: Callable[[Exception, WatchConfig], None] | None                             = None,
    ) -> WatchDiff:
        """
        Register a local file to monitor for changes.

        Args:
            path: Absolute or relative path to the file.
        """
        url = f"file://{path}"
        return self.watch(
            url,
            interval         = interval,
            label            = label or path,
            diff_mode        = diff_mode,
            ignore_patterns  = ignore_patterns or [],
            cooldown         = cooldown,
            dry_run          = dry_run,
            max_snapshots    = max_snapshots,
            change_threshold = change_threshold,
            ignore_numbers   = ignore_numbers,
            on_change        = on_change,
            webhooks         = webhooks,
            webhook_retries  = webhook_retries,
            alert_if         = alert_if,
            ai_summary       = ai_summary,
            ai_provider      = ai_provider,
            on_error         = on_error,
            is_file          = True,
        )

    def watch_api(
        self,
        url: str,
        *,
        interval: int                                                                          = 300,
        label: str | None                                                                      = None,
        headers: dict[str, str] | None                                                        = None,
        timeout: int                                                                           = 15,
        diff_mode: str                                                                         = "json",
        expected_status: int | None                                                            = None,
        track_response_time: bool                                                              = True,
        cooldown: int                                                                          = 0,
        dry_run: bool                                                                          = False,
        max_snapshots: int | None                                                              = None,
        on_change: Callable[[DiffReport], None] | list[Callable[[DiffReport], None]] | None   = None,
        webhooks: list[str] | None                                                             = None,
        webhook_retries: int                                                                   = 3,
        alert_if: Callable[[DiffReport], bool] | None                                         = None,
        ai_summary: bool                                                                       = False,
        ai_provider: Any | None                                                                = None,
        on_error: Callable[[Exception, WatchConfig], None] | None                             = None,
    ) -> WatchDiff:
        """
        Register a REST API endpoint to monitor.

        Args:
            url:                 API URL to watch.
            expected_status:     Alert when HTTP status differs from this value.
            track_response_time: Record response_time_ms on every DiffReport.
        """
        return self.watch(
            url,
            interval             = interval,
            label                = label,
            headers              = headers,
            timeout              = timeout,
            diff_mode            = diff_mode,
            expected_status      = expected_status,
            track_response_time  = track_response_time,
            cooldown             = cooldown,
            dry_run              = dry_run,
            max_snapshots        = max_snapshots,
            on_change            = on_change,
            webhooks             = webhooks,
            webhook_retries      = webhook_retries,
            alert_if             = alert_if,
            ai_summary           = ai_summary,
            ai_provider          = ai_provider,
            on_error             = on_error,
        )

    def watch_cert(
        self,
        hostname: str,
        *,
        port: int                                                                         = 443,
        interval: int                                                                     = 86400,
        label: str | None                                                                 = None,
        warn_days_before_expiry: int                                                      = 30,
        alert_on_change: bool                                                             = True,
        alert_on_expiry: bool                                                             = True,
        cooldown: int                                                                     = 0,
        dry_run: bool                                                                     = False,
        webhooks: list[str] | None                                                        = None,
        webhook_retries: int                                                              = 3,
        on_change: Callable[[Any], None] | None                                           = None,
        on_expiry: Callable[[Any], None] | None                                           = None,
        on_error: Callable[[Exception, Any], None] | None                                 = None,
    ) -> WatchDiff:
        """
        Register an SSL certificate to monitor.

        Args:
            hostname:               Domain to check (e.g. "example.com").
            port:                   TCP port (default 443).
            warn_days_before_expiry: Alert when cert expires within this many days.
        """
        from watchdiff.cert_models import make_cert_watch_config  # noqa: PLC0415
        config = make_cert_watch_config(
            hostname,
            port                    = port,
            interval                = interval,
            label                   = label or f"{hostname}:{port}",
            warn_days_before_expiry = warn_days_before_expiry,
            alert_on_change         = alert_on_change,
            alert_on_expiry         = alert_on_expiry,
            cooldown                = cooldown,
            dry_run                 = dry_run,
            webhooks                = webhooks or [],
            webhook_retries         = webhook_retries,
            on_change               = on_change,
            on_expiry               = on_expiry,
            on_error                = on_error,
        )
        self._cert_configs.append(config)
        return self

    def get_cert_statuses(self) -> list[Any]:
        """Return live status for all registered SSL certificate watchers."""
        if self._cert_scheduler is None:
            return []
        return self._cert_scheduler.get_statuses()

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
        import time  # noqa: PLC0415

        has_urls = bool(self._configs)
        has_db   = bool(self._db_configs)
        has_cert = bool(self._cert_configs)

        if not has_urls and not has_db and not has_cert:
            logger.warning("Nothing registered. Call .watch(), .watch_db(), or .watch_cert() first.")
            return

        if has_urls:
            scheduler = SyncScheduler(self._store)
            self._scheduler = scheduler
            for cb in self._global_callbacks:
                scheduler.add_global_callback(cb)
            scheduler.start(self._configs, block=False)

        if has_db:
            from watchdiff.db_scheduler import DbSyncScheduler  # noqa: PLC0415
            db_scheduler = DbSyncScheduler(self._store)
            self._db_scheduler = db_scheduler
            db_scheduler.start(self._db_configs, block=False)

        if has_cert:
            from watchdiff.cert_scheduler import CertScheduler  # noqa: PLC0415
            cert_scheduler = CertScheduler()
            self._cert_scheduler = cert_scheduler
            cert_scheduler.start(self._cert_configs, block=False)

        if block:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    async def start_async(self) -> None:
        """
        Start the async scheduler.

        Use with ``asyncio.run(wd.start_async())`` or inside an existing event loop.
        """
        has_urls = bool(self._configs)
        has_db   = bool(self._db_configs)

        if not has_urls and not has_db:
            logger.warning("Nothing registered. Call .watch() or .watch_db() first.")
            return

        coros = []

        if has_urls:
            scheduler = AsyncScheduler(self._store)
            self._async_scheduler = scheduler
            for cb in self._global_callbacks:
                scheduler.add_global_callback(cb)
            coros.append(scheduler.start(self._configs))

        if has_db:
            from watchdiff.db_scheduler import DbAsyncScheduler  # noqa: PLC0415
            db_scheduler = DbAsyncScheduler(self._store)
            self._async_db_scheduler = db_scheduler
            coros.append(db_scheduler.start(self._db_configs))

        if len(coros) == 1:
            await coros[0]
        else:
            import asyncio  # noqa: PLC0415
            await asyncio.gather(*coros, return_exceptions=True)

    def stop(self) -> None:
        """Stop all running schedulers."""
        if self._scheduler:
            self._scheduler.stop()
        if self._db_scheduler:
            self._db_scheduler.stop()
        if self._async_db_scheduler:
            self._async_db_scheduler.stop()
        if self._cert_scheduler:
            self._cert_scheduler.stop()

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

    def db_status(self) -> list[Any]:
        """
        Return live status for all registered DB watchers as ``DbWatcherStatus`` objects.

        Returns an empty list if the DB scheduler has not been started.
        """
        if self._db_scheduler is None:
            return []
        return self._db_scheduler.get_statuses()

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
    # Status server
    # ------------------------------------------------------------------

    def start_status_server(self, port: int = 9090, host: str = "0.0.0.0") -> None:
        """
        Start the embedded HTTP status server.

        Endpoints: GET /health · GET /status · GET /metrics (Prometheus).

        Args:
            port: TCP port to bind (default 9090).
            host: Bind address (default "0.0.0.0").
        """
        from watchdiff.status_server import StatusServer  # noqa: PLC0415

        def _get_statuses() -> list[WatcherStatus]:
            return self.status()

        server = StatusServer(get_statuses=_get_statuses, host=host, port=port)
        server.start()
        self._status_server = server

    def stop_status_server(self) -> None:
        """Stop the embedded HTTP status server."""
        if self._status_server:
            self._status_server.stop()
            self._status_server = None

    # ------------------------------------------------------------------
    # URL comparison
    # ------------------------------------------------------------------

    def compare_urls(
        self,
        url_a: str,
        url_b: str,
        *,
        target: str | None              = None,
        diff_mode: str                  = "line",
        browser: bool                   = False,
        timeout: int                    = 15,
        headers: dict | None            = None,
        ignore_selectors: list[str] | None = None,
        ignore_patterns: list[str] | None  = None,
        proxies: list[str] | None          = None,
        user_agents: list[str] | None      = None,
    ) -> DiffReport:
        """
        Fetch two different URLs and compare their content immediately.

        Args:
            url_a:            First URL (treated as "before").
            url_b:            Second URL (treated as "after").
            target:           CSS selector or XPath to narrow comparison.
            diff_mode:        "line" | "semantic" | "word" | "json" | "rss".
            browser:          Use headless browser (Playwright).
            timeout:          HTTP request timeout in seconds.
            headers:          Extra HTTP headers.
            ignore_selectors: CSS selectors to strip before diffing.
            ignore_patterns:  Regex patterns to strip from text before diffing.
            proxies:          Proxy URLs - one picked randomly per request.
            user_agents:      User-Agent strings - one picked randomly per request.

        Returns:
            DiffReport comparing the two pages.
        """
        from watchdiff.cleaner import Cleaner  # noqa: PLC0415
        from watchdiff.diff import DiffEngine  # noqa: PLC0415
        from watchdiff.fetcher import Fetcher  # noqa: PLC0415
        from watchdiff.parser import Parser    # noqa: PLC0415

        shared = dict(
            target           = target,
            diff_mode        = diff_mode,
            browser          = browser,
            timeout          = timeout,
            headers          = headers or {},
            ignore_selectors = ignore_selectors or [],
            ignore_patterns  = ignore_patterns or [],
            proxies          = proxies or [],
            user_agents      = user_agents or [],
        )
        cfg_a = WatchConfig(url=url_a, **shared)
        cfg_b = WatchConfig(url=url_b, **shared)

        if browser:
            from watchdiff.fetcher.browser import BrowserFetcher  # noqa: PLC0415
            fetcher_fn = BrowserFetcher().fetch
        else:
            _fetcher = Fetcher()
            fetcher_fn = _fetcher.fetch

        cleaner = Cleaner()
        parser  = Parser()
        engine  = DiffEngine()

        html_a   = fetcher_fn(cfg_a)
        soup_a   = cleaner.clean(html_a)
        snap_a   = parser.extract(soup_a, cfg_a)

        html_b   = fetcher_fn(cfg_b)
        soup_b   = cleaner.clean(html_b)
        snap_b   = parser.extract(soup_b, cfg_b)

        cfg_cmp  = WatchConfig(url=url_a, target=target, diff_mode=diff_mode,
                               label=f"{url_a} vs {url_b}")
        return engine.compare(snap_a, snap_b, cfg_cmp)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_config(self, url: str) -> WatchConfig:
        for config in self._configs:
            if config.url == url:
                return config
        raise ValueError(f"URL not registered: {url!r}. Call .watch() first.")
