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

from watchdiff.ai_summarizer import AiError, generate_ai_summary, get_provider
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

    def __init__(self, store: Any, concurrency: int | None = None) -> None:
        self._store                                                  = store
        self._fetcher                                                = Fetcher()
        self._browser_fetcher: Any                                   = None  # lazy-init on first browser use
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._semaphore: threading.Semaphore | None                  = threading.Semaphore(concurrency) if concurrency else None
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
        self._ai_disabled: set[str]                                  = set()
        self._consecutive_failures: dict[str, int]                   = {}
        self._consecutive_successes: dict[str, int]                  = {}
        self._in_failure_mode: dict[str, bool]                       = {}
        self._retry_after_delay: dict[str, float]                    = {}

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

    def pause(self, id_or_url: str) -> None:
        """Suspend a watcher by its id (if set) or URL."""
        self._paused.add(id_or_url)
        logger.info("Paused watcher %s", id_or_url)

    def resume(self, id_or_url: str) -> None:
        """Resume a paused watcher by its id (if set) or URL."""
        self._paused.discard(id_or_url)
        logger.info("Resumed watcher %s", id_or_url)

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
                paused         = _watcher_key(config) in self._paused,
                last_check_at  = datetime.fromtimestamp(last_check, tz=timezone.utc) if last_check else None,
                next_check_at  = datetime.fromtimestamp(next_check, tz=timezone.utc) if next_check else None,
                last_change_at = datetime.fromtimestamp(last_change, tz=timezone.utc) if last_change else None,
                checks_count      = self._checks_count.get(key, 0),
                changes_count     = self._changes_count.get(key, 0),
                errors_count      = self._errors_count.get(key, 0),
                last_status_code  = self._last_status_code.get(key, 0),
                id             = getattr(config, "id", None),
                in_maintenance = _in_maintenance(config),
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
            if _watcher_key(config) not in self._paused:
                if _in_maintenance(config):
                    logger.debug("[%s] Skipping check — in maintenance window.", config.label)
                elif not _in_active_hours(config):
                    logger.debug("[%s] Skipping check — outside active hours.", config.label)
                elif self._semaphore is not None:
                    with self._semaphore:
                        self._check(config)
                else:
                    self._check(config)

            retry_after = self._retry_after_delay.pop(key, None)
            if getattr(config, "schedule", None):
                from watchdiff.cron_parser import next_cron_run  # noqa: PLC0415
                from datetime import datetime, timezone  # noqa: PLC0415
                next_dt  = next_cron_run(config.schedule)
                delay    = max(1.0, (next_dt - datetime.now(timezone.utc)).total_seconds())
                if retry_after:
                    delay = max(delay, retry_after)
                self._next_check_at[key] = time.time() + delay
                stop_event.wait(timeout=delay)
            else:
                effective = float(config.interval)
                if config.jitter > 0:
                    delta     = config.interval * config.jitter * random.uniform(-1, 1)
                    effective = max(1.0, effective + delta)
                if retry_after:
                    effective = max(effective, retry_after)
                self._next_check_at[key] = time.time() + effective
                stop_event.wait(timeout=effective)

    def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to FileFetcher, BrowserFetcher, or Fetcher."""
        if getattr(config, "is_file", False):
            from watchdiff.file_fetcher import FileFetcher  # noqa: PLC0415
            return FileFetcher().fetch(config)
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

        policy = getattr(config, "failure_policy", None)
        t0 = time.monotonic() if getattr(config, "track_response_time", False) else None
        try:
            html = self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            consec = self._consecutive_failures.get(key, 0) + 1
            self._consecutive_failures[key] = consec
            self._consecutive_successes[key] = 0
            if policy:
                if policy.respect_retry_after:
                    ra = getattr(exc, "retry_after", None)
                    if ra:
                        self._retry_after_delay[key] = float(ra)
                if consec < policy.consecutive_failures:
                    logger.debug("[%s] Failure %d/%d — suppressed by failure_policy", config.label, consec, policy.consecutive_failures)
                    return None
                if consec > policy.consecutive_failures and self._in_failure_mode.get(key, False):
                    logger.debug("[%s] In failure mode (%d consecutive) — alert suppressed", config.label, consec)
                    return None
                self._in_failure_mode[key] = True
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

        # Successful fetch — handle recovery if in failure mode
        if self._in_failure_mode.get(key, False):
            self._consecutive_failures[key] = 0
            consec_ok = self._consecutive_successes.get(key, 0) + 1
            self._consecutive_successes[key] = consec_ok
            if policy and consec_ok < policy.recovery_checks:
                logger.debug("[%s] Recovery check %d/%d", config.label, consec_ok, policy.recovery_checks)
                return None
            self._in_failure_mode[key] = False
            self._consecutive_successes[key] = 0
            logger.info("[%s] Recovered after %d check(s)", config.label, consec_ok)
        else:
            self._consecutive_failures[key] = 0

        response_time_ms = (time.monotonic() - t0) * 1000 if t0 is not None else None

        expected_status = getattr(config, "expected_status", None)
        if expected_status is not None and expected_status != 200:
            err = Exception(f"Expected HTTP {expected_status}, got 200")
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            if config.on_error:
                try:
                    config.on_error(err, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[%s] on_error callback error: %s", config.label, cb_exc)

        self._handle_status_change(key, 200, config)

        json_path = getattr(config, "json_path", None)
        if json_path:
            from watchdiff.json_path import extract_json_path  # noqa: PLC0415
            try:
                html = extract_json_path(html, json_path)
            except ValueError as exc:
                self._errors_count[key] = self._errors_count.get(key, 0) + 1
                logger.error("[%s] json_path extraction failed: %s", config.label, exc)
                return None

        if getattr(config, "is_file", False) or json_path:
            from watchdiff.models import Snapshot  # noqa: PLC0415
            snapshot = Snapshot(url=config.url, target=config.target, content=html, raw_html=html)
        else:
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
        if response_time_ms is not None:
            report.response_time_ms = response_time_ms

        if not config.dry_run:
            self._store.save_snapshot(snapshot)
            if config.max_snapshots and hasattr(self._store, "prune_snapshots"):
                self._store.prune_snapshots(config.url, config.target, config.max_snapshots)

        if report.has_changes:
            confirm_after = getattr(config, "confirm_after", None)
            if confirm_after is not None:
                logger.debug(
                    "[%s] Change detected, waiting %ds to confirm.", config.label, confirm_after
                )
                time.sleep(confirm_after)
                try:
                    recheck_html = self._fetch(config)
                    _json_path = getattr(config, "json_path", None)
                    if _json_path:
                        from watchdiff.json_path import extract_json_path  # noqa: PLC0415
                        recheck_html = extract_json_path(recheck_html, _json_path)
                    if getattr(config, "is_file", False) or _json_path:
                        from watchdiff.models import Snapshot as _Snapshot  # noqa: PLC0415
                        recheck_snap = _Snapshot(
                            url=config.url, target=config.target,
                            content=recheck_html, raw_html=recheck_html,
                        )
                    else:
                        _cleaner = Cleaner(
                            extra_selectors=config.ignore_selectors,
                            extra_patterns=extra_patterns,
                        )
                        _soup = _cleaner.clean(recheck_html)
                        recheck_snap = self._parser.extract(_soup, config)
                    recheck_report = self._engine.compare(previous, recheck_snap, config)
                    if not recheck_report.has_changes:
                        logger.info(
                            "[%s] Transient change suppressed after confirm_after.", config.label
                        )
                        return report
                    report = recheck_report
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] confirm_after recheck failed: %s", config.label, exc)

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

            # alert_if - custom condition gate
            alert_if = getattr(config, "alert_if", None)
            if alert_if is not None:
                try:
                    if not alert_if(report):
                        logger.debug("[%s] alert_if returned False - alert suppressed.", config.label)
                        return report
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] alert_if callback error: %s", config.label, exc)

            if not config.dry_run:
                self._store.save_report(report)

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = time.time()
            self._silence_fired[key]  = False
            logger.info("[%s] %s", config.label, report.summary())

            # AI summary
            if getattr(config, "ai_summary", False) and key not in self._ai_disabled:
                provider = get_provider(config)
                if provider:
                    try:
                        report.ai_summary = generate_ai_summary(report, provider, getattr(config, "ai_prompt", None))
                        if report.ai_summary:
                            logger.debug("[%s] AI summary: %s", config.label, report.ai_summary)
                    except AiError as exc:
                        if exc.is_permanent:
                            self._ai_disabled.add(key)
                            logger.warning("[%s] AI summaries disabled - %s: %s", config.label, exc.kind, exc)
                        elif exc.kind.value == "quota_exceeded":
                            logger.warning("[%s] AI quota exceeded - skipping this check.", config.label)
                        else:
                            logger.warning("[%s] AI summary skipped (%s): %s", config.label, exc.kind, exc)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[%s] AI summary error: %s", config.label, exc)

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

    def __init__(self, store: Any, concurrency: int | None = None) -> None:
        self._store                                                  = store
        self._fetcher                                                = AsyncFetcher()
        self._browser_fetcher: Any                                   = None  # lazy-init on first browser use
        self._parser                                                 = Parser()
        self._engine                                                 = DiffEngine()
        self._notifier                                               = Notifier()
        self._semaphore: asyncio.Semaphore | None                    = asyncio.Semaphore(concurrency) if concurrency else None
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
        self._ai_disabled: set[str]                                  = set()
        self._consecutive_failures: dict[str, int]                   = {}
        self._consecutive_successes: dict[str, int]                  = {}
        self._in_failure_mode: dict[str, bool]                       = {}
        self._retry_after_delay: dict[str, float]                    = {}

    def add_global_callback(self, callback: Callable[[DiffReport], None]) -> None:
        self._on_diff_callbacks.append(callback)

    async def start(self, configs: list[WatchConfig]) -> None:
        """Start all watchers as concurrent asyncio tasks."""
        self._configs = list(configs)
        tasks = [asyncio.create_task(self._run_loop(cfg)) for cfg in configs]
        await asyncio.gather(*tasks)

    def pause(self, id_or_url: str) -> None:
        """Suspend a watcher by its id (if set) or URL."""
        self._paused.add(id_or_url)
        logger.info("Paused watcher %s", id_or_url)

    def resume(self, id_or_url: str) -> None:
        """Resume a paused watcher by its id (if set) or URL."""
        self._paused.discard(id_or_url)
        logger.info("Resumed watcher %s", id_or_url)

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
                paused         = _watcher_key(config) in self._paused,
                last_check_at  = datetime.fromtimestamp(last_check, tz=timezone.utc) if last_check else None,
                next_check_at  = datetime.fromtimestamp(next_check, tz=timezone.utc) if next_check else None,
                last_change_at = datetime.fromtimestamp(last_change, tz=timezone.utc) if last_change else None,
                checks_count      = self._checks_count.get(key, 0),
                changes_count     = self._changes_count.get(key, 0),
                errors_count      = self._errors_count.get(key, 0),
                last_status_code  = self._last_status_code.get(key, 0),
                id             = getattr(config, "id", None),
                in_maintenance = _in_maintenance(config),
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
            if _watcher_key(config) not in self._paused:
                if _in_maintenance(config):
                    logger.debug("[%s] Skipping check — in maintenance window.", config.label)
                elif not _in_active_hours(config):
                    logger.debug("[%s] Skipping check — outside active hours.", config.label)
                elif self._semaphore is not None:
                    async with self._semaphore:
                        await self._check(config)
                else:
                    await self._check(config)

            retry_after = self._retry_after_delay.pop(key, None)
            if getattr(config, "schedule", None):
                from watchdiff.cron_parser import next_cron_run  # noqa: PLC0415
                next_dt  = next_cron_run(config.schedule)
                delay    = max(1.0, (next_dt - datetime.now(timezone.utc)).total_seconds())
                if retry_after:
                    delay = max(delay, retry_after)
                self._next_check_at[key] = time.time() + delay
                await asyncio.sleep(delay)
            else:
                effective = float(config.interval)
                if config.jitter > 0:
                    delta     = config.interval * config.jitter * random.uniform(-1, 1)
                    effective = max(1.0, effective + delta)
                if retry_after:
                    effective = max(effective, retry_after)
                self._next_check_at[key] = time.time() + effective
                await asyncio.sleep(effective)

    async def _fetch(self, config: WatchConfig) -> str:
        """Dispatch to FileFetcher, AsyncBrowserFetcher, or AsyncFetcher."""
        if getattr(config, "is_file", False):
            from watchdiff.file_fetcher import FileFetcher  # noqa: PLC0415
            return FileFetcher().fetch(config)
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

        policy = getattr(config, "failure_policy", None)
        t0 = time.monotonic() if getattr(config, "track_response_time", False) else None
        try:
            html = await self._fetch(config)
        except Exception as exc:  # noqa: BLE001
            consec = self._consecutive_failures.get(key, 0) + 1
            self._consecutive_failures[key] = consec
            self._consecutive_successes[key] = 0
            if policy:
                if policy.respect_retry_after:
                    ra = getattr(exc, "retry_after", None)
                    if ra:
                        self._retry_after_delay[key] = float(ra)
                if consec < policy.consecutive_failures:
                    logger.debug("[%s] Failure %d/%d — suppressed by failure_policy", config.label, consec, policy.consecutive_failures)
                    return None
                if consec > policy.consecutive_failures and self._in_failure_mode.get(key, False):
                    logger.debug("[%s] In failure mode (%d consecutive) — alert suppressed", config.label, consec)
                    return None
                self._in_failure_mode[key] = True
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

        # Successful fetch — handle recovery if in failure mode
        if self._in_failure_mode.get(key, False):
            self._consecutive_failures[key] = 0
            consec_ok = self._consecutive_successes.get(key, 0) + 1
            self._consecutive_successes[key] = consec_ok
            if policy and consec_ok < policy.recovery_checks:
                logger.debug("[%s] Recovery check %d/%d", config.label, consec_ok, policy.recovery_checks)
                return None
            self._in_failure_mode[key] = False
            self._consecutive_successes[key] = 0
            logger.info("[%s] Recovered after %d check(s)", config.label, consec_ok)
        else:
            self._consecutive_failures[key] = 0

        response_time_ms = (time.monotonic() - t0) * 1000 if t0 is not None else None

        expected_status = getattr(config, "expected_status", None)
        if expected_status is not None and expected_status != 200:
            err = Exception(f"Expected HTTP {expected_status}, got 200")
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            if config.on_error:
                try:
                    config.on_error(err, config)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("[%s] on_error callback error: %s", config.label, cb_exc)

        await self._handle_status_change(key, 200, config)

        json_path = getattr(config, "json_path", None)
        if json_path:
            from watchdiff.json_path import extract_json_path  # noqa: PLC0415
            try:
                html = extract_json_path(html, json_path)
            except ValueError as exc:
                self._errors_count[key] = self._errors_count.get(key, 0) + 1
                logger.error("[%s] json_path extraction failed: %s", config.label, exc)
                return None

        if getattr(config, "is_file", False) or json_path:
            from watchdiff.models import Snapshot  # noqa: PLC0415
            snapshot = Snapshot(url=config.url, target=config.target, content=html, raw_html=html)
        else:
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
        if response_time_ms is not None:
            report.response_time_ms = response_time_ms

        if not config.dry_run:
            self._store.save_snapshot(snapshot)
            if config.max_snapshots and hasattr(self._store, "prune_snapshots"):
                self._store.prune_snapshots(config.url, config.target, config.max_snapshots)

        if report.has_changes:
            confirm_after = getattr(config, "confirm_after", None)
            if confirm_after is not None:
                logger.debug(
                    "[%s] Change detected, waiting %ds to confirm.", config.label, confirm_after
                )
                await asyncio.sleep(confirm_after)
                try:
                    recheck_html = await self._fetch(config)
                    _json_path = getattr(config, "json_path", None)
                    if _json_path:
                        from watchdiff.json_path import extract_json_path  # noqa: PLC0415
                        recheck_html = extract_json_path(recheck_html, _json_path)
                    if getattr(config, "is_file", False) or _json_path:
                        from watchdiff.models import Snapshot as _Snapshot  # noqa: PLC0415
                        recheck_snap = _Snapshot(
                            url=config.url, target=config.target,
                            content=recheck_html, raw_html=recheck_html,
                        )
                    else:
                        _cleaner = Cleaner(
                            extra_selectors=config.ignore_selectors,
                            extra_patterns=extra_patterns,
                        )
                        _soup = _cleaner.clean(recheck_html)
                        recheck_snap = self._parser.extract(_soup, config)
                    recheck_report = self._engine.compare(previous, recheck_snap, config)
                    if not recheck_report.has_changes:
                        logger.info(
                            "[%s] Transient change suppressed after confirm_after.", config.label
                        )
                        return report
                    report = recheck_report
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] confirm_after recheck failed: %s", config.label, exc)

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

            # alert_if - custom condition gate
            alert_if = getattr(config, "alert_if", None)
            if alert_if is not None:
                try:
                    if not alert_if(report):
                        logger.debug("[%s] alert_if returned False - alert suppressed.", config.label)
                        return report
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] alert_if callback error: %s", config.label, exc)

            if not config.dry_run:
                self._store.save_report(report)

            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = time.time()
            self._silence_fired[key]  = False
            logger.info("[%s] %s", config.label, report.summary())

            # AI summary
            if getattr(config, "ai_summary", False) and key not in self._ai_disabled:
                provider = get_provider(config)
                if provider:
                    try:
                        report.ai_summary = generate_ai_summary(report, provider, getattr(config, "ai_prompt", None))
                        if report.ai_summary:
                            logger.debug("[%s] AI summary: %s", config.label, report.ai_summary)
                    except AiError as exc:
                        if exc.is_permanent:
                            self._ai_disabled.add(key)
                            logger.warning("[%s] AI summaries disabled - %s: %s", config.label, exc.kind, exc)
                        elif exc.kind.value == "quota_exceeded":
                            logger.warning("[%s] AI quota exceeded - skipping this check.", config.label)
                        else:
                            logger.warning("[%s] AI summary skipped (%s): %s", config.label, exc.kind, exc)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[%s] AI summary error: %s", config.label, exc)

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


def _watcher_key(config: WatchConfig) -> str:
    """Stable identity key used for pause/resume — prefers config.id over URL."""
    return getattr(config, "id", None) or config.url


def _in_maintenance(config: WatchConfig) -> bool:
    """Return True if now falls inside any maintenance window."""
    windows = getattr(config, "maintenance_windows", None)
    if not windows:
        return False
    now = datetime.now(timezone.utc)
    for w in windows:
        if w.from_ <= now <= w.to:  # type: ignore[operator]
            return True
    return False


def _in_active_hours(config: WatchConfig) -> bool:
    """Return True if now is within the configured active_between window."""
    ab = getattr(config, "active_between", None)
    if ab is None:
        return True
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        tz = ZoneInfo(ab.timezone) if ab.timezone else timezone.utc
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    now_local = datetime.now(tz)
    from_h, from_m = map(int, ab.from_.split(":"))
    to_h, to_m     = map(int, ab.to.split(":"))
    current_min    = now_local.hour * 60 + now_local.minute
    from_min       = from_h * 60 + from_m
    to_min         = to_h   * 60 + to_m
    if to_min <= from_min:
        in_window = current_min >= from_min or current_min < to_min
    else:
        in_window = from_min <= current_min < to_min
    if not in_window:
        return False
    if ab.days is not None and now_local.weekday() not in ab.days:
        return False
    return True
