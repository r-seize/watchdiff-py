"""
Notifier - dispatches alerts when a DiffReport has changes.

Supported channels:
  - Python callbacks (synchronous)
  - Webhooks (Discord, Slack, custom - via httpx POST)

Adding a new channel is as simple as adding a method and calling it
inside `notify()`.
"""

from __future__ import annotations

import logging

import httpx

from watchdiff.models import AlertConfig, DiffReport

logger = logging.getLogger(__name__)


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

        # 1. Python callbacks
        for callback in alert.on_change:
            try:
                callback(report)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert callback raised an error: %s", exc)

        # 2. Webhooks
        for url in alert.webhooks:
            self._send_webhook(url, report)

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def _send_webhook(self, url: str, report: DiffReport) -> None:
        """POST a JSON payload to a webhook URL.

        Automatically adapts payload format for Discord vs Slack vs generic.
        """
        payload = self._build_payload(url, report)
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                if not resp.is_success:
                    logger.warning(
                        "Webhook %s returned %d", url, resp.status_code
                    )
        except httpx.RequestError as exc:
            logger.warning("Webhook request error (%s): %s", url, exc)

    def _build_payload(self, url: str, report: DiffReport) -> dict:
        """Build a webhook payload adapted to the target service."""
        summary         = report.summary()
        change_lines    = "\n".join(c.human() for c in report.changes[:20])
        text            = f"{summary}\n\n{change_lines}"

        if "discord.com" in url:
            return {"content": text[:2000]}  # Discord 2000-char limit

        if "hooks.slack.com" in url:
            return {"text": text[:3000]}

        # Generic JSON
        return report.as_dict()