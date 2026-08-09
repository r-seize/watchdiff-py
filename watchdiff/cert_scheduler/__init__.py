"""
CertScheduler - drives periodic SSL certificate checks.

Alerts on:
- Certificate fingerprint change (cert renewed/replaced)
- Expiry within warn_days_before_expiry days
- Already-expired certificates
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from watchdiff.cert_fetcher import fetch_cert
from watchdiff.cert_models import (
    CertChangeInfo,
    CertExpiryInfo,
    CertReport,
    CertSnapshot,
    CertWatchConfig,
    CertWatcherStatus,
)

logger = logging.getLogger(__name__)


class CertScheduler:
    def __init__(self) -> None:
        self._threads:     list[threading.Thread] = []
        self._stop_events: list[threading.Event]  = []
        self._states:      dict[str, _CertState]  = {}
        self._configs:     list[CertWatchConfig]  = []

    def start(self, configs: list[CertWatchConfig], block: bool = True) -> None:
        self._configs = list(configs)
        for config in configs:
            key = _key(config)
            self._states[key] = _CertState()
            stop_event = threading.Event()
            self._stop_events.append(stop_event)
            thread = threading.Thread(
                target=self._run_loop,
                args=(config, stop_event),
                daemon=True,
                name=f"watchdiff-cert-{config.label}",
            )
            self._threads.append(thread)
            thread.start()
            logger.info("Started cert watcher for %s (interval=%ds)", config.label, config.interval)

        if block:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        for ev in self._stop_events:
            ev.set()

    def get_statuses(self) -> list[CertWatcherStatus]:
        statuses = []
        for config in self._configs:
            s = self._states.get(_key(config), _CertState())
            statuses.append(CertWatcherStatus(
                hostname          = config.hostname,
                label             = config.label,
                port              = config.port,
                interval          = config.interval,
                paused            = s.paused,
                last_check_at     = s.last_check_at,
                next_check_at     = s.next_check_at,
                last_change_at    = s.last_change_at,
                checks_count      = s.checks_count,
                changes_count     = s.changes_count,
                errors_count      = s.errors_count,
                days_until_expiry = s.days_until_expiry,
                valid_to          = s.valid_to,
                is_expiring_soon  = (
                    s.days_until_expiry is not None
                    and s.days_until_expiry <= config.warn_days_before_expiry
                ),
            ))
        return statuses

    # ------------------------------------------------------------------

    def _run_loop(self, config: CertWatchConfig, stop_event: threading.Event) -> None:
        self._check(config)
        while not stop_event.wait(config.interval):
            key = _key(config)
            state = self._states[key]
            if not state.paused:
                self._check(config)

    def _check(self, config: CertWatchConfig) -> CertReport | None:
        key   = _key(config)
        state = self._states[key]
        now   = time.time()

        state.checks_count += 1
        state.next_check_at = datetime.fromtimestamp(now + config.interval, tz=timezone.utc)

        try:
            snapshot = fetch_cert(config)
        except Exception as exc:
            state.errors_count += 1
            state.last_check_at = datetime.now(timezone.utc)
            error = exc if isinstance(exc, Exception) else Exception(str(exc))
            if config.on_error:
                try:
                    config.on_error(error, config)
                except Exception as cb_exc:
                    logger.warning("[%s] on_error callback error: %s", config.label, cb_exc)
            else:
                logger.error("[%s] Cert fetch failed: %s", config.label, exc)
            return None

        state.last_check_at    = datetime.now(timezone.utc)
        state.days_until_expiry = snapshot.days_until_expiry
        state.valid_to          = snapshot.valid_to

        previous            = state.last_snapshot
        is_expired          = snapshot.days_until_expiry < 0
        is_expiring_soon    = not is_expired and snapshot.days_until_expiry <= config.warn_days_before_expiry
        fingerprint_changed = bool(previous and previous.fingerprint != snapshot.fingerprint)

        report = CertReport(
            hostname            = config.hostname,
            label               = config.label,
            snapshot            = snapshot,
            previous            = previous,
            days_until_expiry   = snapshot.days_until_expiry,
            is_expired          = is_expired,
            is_expiring_soon    = is_expiring_soon,
            fingerprint_changed = fingerprint_changed,
        )

        state.last_snapshot = snapshot

        if previous is None:
            logger.info(
                "[%s] Cert captured - expires in %dd (%s)",
                config.label,
                snapshot.days_until_expiry,
                snapshot.valid_to.strftime("%Y-%m-%d"),
            )
            return report

        cooldown_ok = (now - state.last_alert_at) >= config.cooldown

        if fingerprint_changed and config.alert_on_change and cooldown_ok and not config.dry_run:
            state.changes_count += 1
            state.last_change_at = datetime.now(timezone.utc)
            state.last_alert_at  = now
            info = CertChangeInfo(
                hostname             = config.hostname,
                label                = config.label,
                previous_fingerprint = previous.fingerprint,
                current_fingerprint  = snapshot.fingerprint,
                previous_valid_to    = previous.valid_to,
                current_valid_to     = snapshot.valid_to,
            )
            logger.info(
                "[%s] Certificate replaced - new expiry %s",
                config.label, snapshot.valid_to.strftime("%Y-%m-%d"),
            )
            if config.on_change:
                try:
                    config.on_change(info)
                except Exception as exc:
                    logger.warning("[%s] on_change callback error: %s", config.label, exc)
            _dispatch_webhook(
                config,
                f"Certificate replaced for {config.hostname}. New expiry: {snapshot.valid_to.strftime('%Y-%m-%d')}",
            )

        if (is_expiring_soon or is_expired) and config.alert_on_expiry and cooldown_ok and not config.dry_run:
            if not fingerprint_changed:
                state.last_alert_at = now
            info_e = CertExpiryInfo(
                hostname          = config.hostname,
                label             = config.label,
                days_until_expiry = snapshot.days_until_expiry,
                valid_to          = snapshot.valid_to,
                is_expired        = is_expired,
            )
            msg = (
                f"[{config.label}] Certificate EXPIRED ({config.hostname})"
                if is_expired
                else f"[{config.label}] Certificate expires in {snapshot.days_until_expiry} day(s) - {snapshot.valid_to.strftime('%Y-%m-%d')}"
            )
            logger.warning(msg)
            if config.on_expiry:
                try:
                    config.on_expiry(info_e)
                except Exception as exc:
                    logger.warning("[%s] on_expiry callback error: %s", config.label, exc)
            _dispatch_webhook(config, msg)

        return report


class _CertState:
    def __init__(self) -> None:
        self.last_check_at:     datetime | None  = None
        self.next_check_at:     datetime | None  = None
        self.last_change_at:    datetime | None  = None
        self.checks_count:      int              = 0
        self.changes_count:     int              = 0
        self.errors_count:      int              = 0
        self.paused:            bool             = False
        self.last_alert_at:     float            = 0.0
        self.last_snapshot:     CertSnapshot | None = None
        self.days_until_expiry: int | None       = None
        self.valid_to:          datetime | None  = None


def _key(config: CertWatchConfig) -> str:
    return f"{config.hostname}:{config.port}"


def _dispatch_webhook(config: CertWatchConfig, text: str) -> None:
    if not config.webhooks:
        return
    payload = json.dumps({
        "type":    "cert_alert",
        "label":   config.label,
        "hostname": config.hostname,
        "message": text,
    }).encode()
    max_attempts = config.webhook_retries + 1
    for url in config.webhooks:
        for attempt in range(max_attempts):
            try:
                req  = urllib.request.Request(
                    url, data=payload,
                    headers={"content-type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10):
                    break
            except Exception as exc:
                if attempt == max_attempts - 1:
                    logger.warning("[%s] Webhook %s failed: %s", config.label, url, exc)
                else:
                    time.sleep(0.5 * (2 ** attempt))


__all__ = ["CertScheduler"]
