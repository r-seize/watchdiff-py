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

from watchdiff.models import AlertConfig, DiffReport

logger = logging.getLogger(__name__)

_TEAMS_DOMAINS       = ("outlook.office.com", "webhook.office.com", "logic.azure.com")
_RETRY_BASE_DELAY_S  = 0.5


class Notifier:
    """Sends alerts for a DiffReport based on an AlertConfig."""

    def notify(self, report: DiffReport, alert: AlertConfig) -> None:
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

        for url in alert.webhooks:
            self._send_webhook_with_retry(url, report, alert.webhook_retries)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_webhook_with_retry(
        self, url: str, report: DiffReport, max_retries: int
    ) -> None:
        max_attempts = max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                self._send_webhook(url, report)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_attempts:
                    time.sleep(_RETRY_BASE_DELAY_S * (2 ** (attempt - 1)))

        logger.warning(
            "Webhook failed after %d attempt(s) (%s): %s",
            max_attempts, url, last_exc,
        )

    def _send_webhook(self, url: str, report: DiffReport) -> None:
        payload, extra_headers = self._build_payload(url, report)
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload, headers=extra_headers)
            if not resp.is_success:
                raise Exception(f"Webhook {url} returned {resp.status_code}")  # noqa: TRY002

    def _build_payload(self, url: str, report: DiffReport) -> tuple[dict, dict]:
        """Return (json_payload, extra_headers) adapted to the target service."""
        summary      = report.summary()
        change_lines = "\n".join(c.human() for c in report.changes[:20])
        text         = f"{summary}\n\n{change_lines}"

        if "discord.com" in url:
            return {"content": text[:2000]}, {}

        if "hooks.slack.com" in url:
            return {"text": text[:3000]}, {}

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
                "Tags":     "bell",
            }

        return report.as_dict(), {}


# ---------------------------------------------------------------------------
# Teams MessageCard helper
# ---------------------------------------------------------------------------

def _teams_card(report: DiffReport, text: str) -> dict:
    return {
        "@type":       "MessageCard",
        "@context":    "http://schema.org/extensions",
        "themeColor":  "FF6600",
        "summary":     report.summary(),
        "sections": [
            {
                "activityTitle": f"WatchDiff - {report.label}",
                "activityText":  report.summary(),
                "facts": [
                    {
                        "name":  c.kind.value,
                        "value": (c.after or c.before or "")[:200],
                    }
                    for c in report.changes[:10]
                ],
            }
        ],
    }
