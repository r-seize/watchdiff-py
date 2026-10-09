"""
Notifier - dispatches alerts when a DiffReport has changes.

Supported channels:
  - Python callbacks (synchronous)
  - Discord (discord.com)
  - Slack (hooks.slack.com)
  - Telegram (api.telegram.org) - chat_id extracted from URL query param
  - Microsoft Teams (outlook.office.com / webhook.office.com / logic.azure.com)
  - ntfy.sh (ntfy.sh or ntfy.) - title/priority via headers
  - Generic JSON webhook (anything else)
"""

from __future__ import annotations

import logging
import time
from urllib.parse import parse_qs, urlparse

import httpx

from watchdiff.models import AlertConfig, DiffReport, WatchConfig

logger = logging.getLogger(__name__)

_TEAMS_DOMAINS       = ("outlook.office.com", "webhook.office.com", "logic.azure.com")
_RETRY_BASE_DELAY_S  = 0.5


class Notifier:
    """Sends alerts for a DiffReport based on an AlertConfig."""

    def notify(
        self,
        report: DiffReport,
        alert: AlertConfig,
        config: WatchConfig | None = None,
    ) -> None:
        """
        Dispatch all configured alert channels.

        Silently logs errors - a broken webhook must not crash the watcher.
        """
        if not report.has_changes:
            return
        if len(report.changes) < alert.min_changes:
            return

        for callback in alert.on_change:
            try:
                callback(report)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert callback raised an error: %s", exc)

        extra_headers = getattr(config, "webhook_headers", {}) if config else {}
        for url in alert.webhooks:
            self._send_webhook_with_retry(url, report, alert.webhook_retries, extra_headers)

        if alert.email is not None:
            from watchdiff.mailer import send_email  # noqa: PLC0415
            try:
                send_email(alert.email, report)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Email alert failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_webhook_with_retry(
        self,
        url: str,
        report: DiffReport,
        max_retries: int,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        max_attempts = max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                self._send_webhook(url, report, extra_headers or {})
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))

        logger.warning(
            "Webhook failed after %d attempt(s) (%s): %s",
            max_attempts, url, last_exc,
        )

    def _send_webhook(
        self, url: str, report: DiffReport, extra_headers: dict[str, str] | None = None
    ) -> None:
        payload, service_headers = self._build_payload(url, report)
        headers = {**service_headers, **(extra_headers or {})}
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload, headers=headers)
            if not resp.is_success:
                raise Exception(f"Webhook {url} returned {resp.status_code}")  # noqa: TRY002

    def _build_payload(self, url: str, report: DiffReport) -> tuple[dict, dict]:
        """Return (json_payload, service_headers) adapted to the target service."""
        summary      = report.summary()
        change_lines = "\n".join(c.human() for c in report.changes[:20])
        text         = f"{summary}\n\n{change_lines}"

        if "discord.com" in url:
            return {"content": text[:2000]}, {}

        if "hooks.slack.com" in url:
            return _slack_blocks(report, text), {}

        if "api.telegram.org" in url:
            parsed  = urlparse(url)
            chat_id = parse_qs(parsed.query).get("chat_id", [""])[0]
            return {
                "chat_id":    chat_id,
                "text":       text[:4096],
                "parse_mode": "HTML",
            }, {}

        if any(d in url for d in _TEAMS_DOMAINS):
            return _teams_card(report, text), {}

        if "ntfy." in url or "ntfy.sh" in url:
            return {"message": text[:4096]}, {
                "Title":    report.label,
                "Priority": "default",
                "Tags":     "rotating_light",
            }

        return report.as_dict(), {}


# ---------------------------------------------------------------------------
# Slack Block Kit helper
# ---------------------------------------------------------------------------

def _slack_blocks(report: DiffReport, text: str) -> dict:
    added    = sum(1 for c in report.changes if c.kind.value == "added")
    removed  = sum(1 for c in report.changes if c.kind.value == "removed")
    modified = sum(1 for c in report.changes if c.kind.value == "modified")
    parts = []
    if added:
        parts.append(f"*{added} added*")
    if removed:
        parts.append(f"*{removed} removed*")
    if modified:
        parts.append(f"*{modified} modified*")
    section_text = ", ".join(parts) or text[:2900]
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"WatchDiff — {report.label[:150]}", "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": section_text[:2900]},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*URL:* {report.url}"},
                    {"type": "mrkdwn", "text": f"*At:* {report.compared_at.strftime('%Y-%m-%d %H:%M UTC')}"},
                ],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Teams MessageCard helper
# ---------------------------------------------------------------------------

def _teams_card(report: DiffReport, text: str) -> dict:
    change_lines = "\n".join(c.human() for c in report.changes[:20])
    return {
        "@type":      "MessageCard",
        "@context":   "http://schema.org/extensions",
        "themeColor": "FF6600",
        "title":      f"WatchDiff — {report.label}",
        "text":       f"<pre>{change_lines[:4000]}</pre>",
    }
