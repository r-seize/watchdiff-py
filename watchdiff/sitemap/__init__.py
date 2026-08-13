from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SitemapEntry:
    url: str
    last_modified: str | None = None
    change_freq: str | None = None
    priority: str | None = None


@dataclass
class SitemapSnapshot:
    sitemap_url: str
    entries: list[SitemapEntry]
    captured_at: datetime
    entry_count: int


@dataclass
class SitemapDiffReport:
    sitemap_url: str
    label: str
    added: list[SitemapEntry]
    removed: list[SitemapEntry]
    compared_at: datetime


@dataclass
class SitemapWatchConfig:
    url: str
    interval: int = 3600
    label: str = ""
    timeout: int = 15
    on_added: Callable | None = None
    on_removed: Callable | None = None
    on_change: Callable | None = None
    webhooks: list[str] = field(default_factory=list)


@dataclass
class SitemapWatcherStatus:
    url: str
    label: str
    interval: int
    paused: bool
    last_check_at: datetime | None
    next_check_at: datetime | None
    last_change_at: datetime | None
    checks_count: int
    changes_count: int
    errors_count: int
    entry_count: int | None


class SitemapFetcher:
    def fetch(self, url: str, timeout: int = 15) -> list[SitemapEntry]:
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch sitemap {url}: {exc}") from exc

        xml = resp.text
        return self._parse(url, xml, timeout)

    def _parse(self, source_url: str, xml: str, timeout: int) -> list[SitemapEntry]:
        if "<sitemapindex" in xml:
            child_urls = re.findall(r"<sitemap>\s*<loc>\s*(.*?)\s*</loc>", xml, re.DOTALL)
            entries: list[SitemapEntry] = []
            for child_url in child_urls:
                try:
                    resp = httpx.get(child_url.strip(), timeout=timeout, follow_redirects=True)
                    resp.raise_for_status()
                    entries.extend(self._parse_urlset(resp.text))
                except Exception as exc:
                    logger.warning("Failed to fetch child sitemap %s: %s", child_url, exc)
            return entries
        return self._parse_urlset(xml)

    def _parse_urlset(self, xml: str) -> list[SitemapEntry]:
        entries: list[SitemapEntry] = []
        for block in re.findall(r"<url>(.*?)</url>", xml, re.DOTALL):
            loc = _extract_tag(block, "loc")
            if not loc:
                continue
            entries.append(SitemapEntry(
                url           = loc,
                last_modified = _extract_tag(block, "lastmod"),
                change_freq   = _extract_tag(block, "changefreq"),
                priority      = _extract_tag(block, "priority"),
            ))
        return entries


def _extract_tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", xml, re.DOTALL)
    return m.group(1).strip() if m else None


class SitemapScheduler:
    def __init__(self) -> None:
        self._configs: list[SitemapWatchConfig]            = []
        self._snapshots: dict[str, list[SitemapEntry]]     = {}
        self._paused: set[str]                             = set()
        self._threads: list[threading.Thread]              = []
        self._stop_events: list[threading.Event]           = []
        self._last_check_at: dict[str, float]              = {}
        self._next_check_at: dict[str, float]              = {}
        self._last_change_at: dict[str, float]             = {}
        self._checks_count: dict[str, int]                 = {}
        self._changes_count: dict[str, int]                = {}
        self._errors_count: dict[str, int]                 = {}
        self._entry_count: dict[str, int | None]           = {}
        self._fetcher                                      = SitemapFetcher()

    def start(self, configs: list[SitemapWatchConfig]) -> None:
        self._configs = list(configs)
        for config in configs:
            stop_event = threading.Event()
            self._stop_events.append(stop_event)
            thread = threading.Thread(
                target = self._run_loop,
                args   = (config, stop_event),
                daemon = True,
                name   = f"watchdiff-sitemap-{config.label or config.url}",
            )
            self._threads.append(thread)
            thread.start()
            logger.info("Started sitemap watcher for %s", config.url)

    def stop(self) -> None:
        for event in self._stop_events:
            event.set()

    def get_statuses(self) -> list[SitemapWatcherStatus]:
        result = []
        for config in self._configs:
            key = config.url
            last_check  = self._last_check_at.get(key)
            next_check  = self._next_check_at.get(key)
            last_change = self._last_change_at.get(key)
            result.append(SitemapWatcherStatus(
                url            = config.url,
                label          = config.label,
                interval       = config.interval,
                paused         = config.url in self._paused,
                last_check_at  = datetime.fromtimestamp(last_check, tz=timezone.utc) if last_check else None,
                next_check_at  = datetime.fromtimestamp(next_check, tz=timezone.utc) if next_check else None,
                last_change_at = datetime.fromtimestamp(last_change, tz=timezone.utc) if last_change else None,
                checks_count   = self._checks_count.get(key, 0),
                changes_count  = self._changes_count.get(key, 0),
                errors_count   = self._errors_count.get(key, 0),
                entry_count    = self._entry_count.get(key),
            ))
        return result

    def _run_loop(self, config: SitemapWatchConfig, stop_event: threading.Event) -> None:
        key = config.url
        self._checks_count[key]  = 0
        self._changes_count[key] = 0
        self._errors_count[key]  = 0
        self._entry_count[key]   = None

        while not stop_event.is_set():
            if config.url not in self._paused:
                self._check(config)
            self._next_check_at[key] = time.time() + config.interval
            stop_event.wait(timeout=config.interval)

    def _check(self, config: SitemapWatchConfig) -> None:
        key = config.url
        self._checks_count[key] = self._checks_count.get(key, 0) + 1
        self._last_check_at[key] = time.time()

        try:
            entries = self._fetcher.fetch(config.url, config.timeout)
        except Exception as exc:
            self._errors_count[key] = self._errors_count.get(key, 0) + 1
            logger.error("[sitemap:%s] Fetch failed: %s", config.label or config.url, exc)
            return

        self._entry_count[key] = len(entries)
        previous = self._snapshots.get(key)

        if previous is None:
            self._snapshots[key] = entries
            logger.info("[sitemap:%s] First snapshot: %d entries", config.label or config.url, len(entries))
            return

        prev_urls    = {e.url for e in previous}
        current_urls = {e.url: e for e in entries}

        added   = [current_urls[u] for u in current_urls if u not in prev_urls]
        removed = [e for e in previous if e.url not in current_urls]

        if added or removed:
            self._snapshots[key] = entries
            self._changes_count[key] = self._changes_count.get(key, 0) + 1
            self._last_change_at[key] = time.time()

            report = SitemapDiffReport(
                sitemap_url  = config.url,
                label        = config.label,
                added        = added,
                removed      = removed,
                compared_at  = datetime.now(timezone.utc),
            )

            logger.info(
                "[sitemap:%s] %d added, %d removed",
                config.label or config.url, len(added), len(removed),
            )

            if added and config.on_added:
                try:
                    config.on_added(report)
                except Exception as exc:
                    logger.warning("[sitemap:%s] on_added error: %s", config.label or config.url, exc)

            if removed and config.on_removed:
                try:
                    config.on_removed(report)
                except Exception as exc:
                    logger.warning("[sitemap:%s] on_removed error: %s", config.label or config.url, exc)

            if config.on_change:
                try:
                    config.on_change(report)
                except Exception as exc:
                    logger.warning("[sitemap:%s] on_change error: %s", config.label or config.url, exc)

            for webhook_url in config.webhooks:
                self._send_webhook(webhook_url, report)

    def _send_webhook(self, url: str, report: SitemapDiffReport) -> None:
        payload = {
            "sitemap_url": report.sitemap_url,
            "label":       report.label,
            "compared_at": report.compared_at.isoformat(),
            "added":       [e.url for e in report.added],
            "removed":     [e.url for e in report.removed],
        }
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                if not resp.is_success:
                    logger.warning("Sitemap webhook %s returned %d", url, resp.status_code)
        except Exception as exc:
            logger.warning("Sitemap webhook %s failed: %s", url, exc)
