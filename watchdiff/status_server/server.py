"""
StatusServer - lightweight HTTP server exposing /health, /status, /metrics.

Uses only stdlib (http.server, threading, json) — zero extra dependencies.

Endpoints:
  GET /health   → 200 {"status": "ok"}
  GET /status   → 200 JSON array of WatcherStatus dicts
  GET /metrics  → 200 Prometheus text format
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

logger = logging.getLogger(__name__)


class StatusServer:
    """
    Embedded HTTP status server.

    Args:
        get_statuses: zero-arg callable returning list of WatcherStatus objects.
        host:         bind address (default "0.0.0.0").
        port:         TCP port (default 9090).
    """

    def __init__(
        self,
        get_statuses: Callable[[], list[Any]],
        host: str = "0.0.0.0",
        port: int = 9090,
    ) -> None:
        self._get_statuses = get_statuses
        self._host         = host
        self._port         = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        get_statuses = self._get_statuses

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    self._send_json(200, {"status": "ok"})
                elif self.path == "/status":
                    statuses = get_statuses()
                    data = [s.as_dict() for s in statuses]
                    self._send_json(200, data)
                elif self.path == "/metrics":
                    statuses = get_statuses()
                    body     = _prometheus_text(statuses)
                    self._send_text(200, body, "text/plain; version=0.0.4")
                else:
                    self._send_json(404, {"error": "not found"})

            def _send_json(self, code: int, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, code: int, text: str, content_type: str) -> None:
                body = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
                pass  # silence default access log

        self._server = HTTPServer((self._host, self._port), _Handler)
        self._thread = threading.Thread(
            target = self._server.serve_forever,
            daemon = True,
            name   = "watchdiff-status-server",
        )
        self._thread.start()
        logger.info("Status server started on http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        """Shut down the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        logger.info("Status server stopped.")


# ---------------------------------------------------------------------------
# Prometheus text format builder
# ---------------------------------------------------------------------------

def _prometheus_text(statuses: list[Any]) -> str:
    from datetime import datetime  # noqa: PLC0415

    lines: list[str] = []

    def _label_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def _row(name: str, labels: dict[str, str], value: float) -> str:
        label_str = ",".join(f'{k}="{_label_escape(v)}"' for k, v in labels.items())
        return f"watchdiff_{name}{{{label_str}}} {value}"

    def _metric(name: str, help_text: str, mtype: str, rows: list[str]) -> None:
        lines.append(f"# HELP watchdiff_{name} {help_text}")
        lines.append(f"# TYPE watchdiff_{name} {mtype}")
        lines.extend(rows)

    _metric(
        "checks_total", "Total number of checks performed per URL.", "counter",
        [_row("checks_total", {"url": s.as_dict()["url"], "label": s.as_dict()["label"]}, s.as_dict()["checks_count"]) for s in statuses],
    )
    _metric(
        "changes_total", "Total number of checks that produced at least one change.", "counter",
        [_row("changes_total", {"url": s.as_dict()["url"], "label": s.as_dict()["label"]}, s.as_dict()["changes_count"]) for s in statuses],
    )
    _metric(
        "errors_total", "Total number of fetch or parse errors.", "counter",
        [_row("errors_total", {"url": s.as_dict()["url"], "label": s.as_dict()["label"]}, s.as_dict().get("errors_count", 0)) for s in statuses],
    )
    _metric(
        "paused", "1 if the watcher is currently paused, 0 otherwise.", "gauge",
        [_row("paused", {"url": s.as_dict()["url"], "label": s.as_dict()["label"]}, 1 if s.as_dict()["paused"] else 0) for s in statuses],
    )
    _metric(
        "interval_seconds", "Configured check interval in seconds.", "gauge",
        [_row("interval_seconds", {"url": s.as_dict()["url"], "label": s.as_dict()["label"]}, s.as_dict()["interval"]) for s in statuses],
    )

    last_change_rows: list[str] = []
    last_check_rows:  list[str] = []
    last_status_rows: list[str] = []

    for s in statuses:
        d      = s.as_dict()
        labels = {"url": d["url"], "label": d["label"]}

        ts_change = 0
        if d.get("last_change_at"):
            try:
                ts_change = int(datetime.fromisoformat(d["last_change_at"]).timestamp())
            except ValueError:
                pass
        last_change_rows.append(_row("last_change_timestamp_seconds", labels, ts_change))

        ts_check = 0
        if d.get("last_check_at"):
            try:
                ts_check = int(datetime.fromisoformat(d["last_check_at"]).timestamp())
            except ValueError:
                pass
        last_check_rows.append(_row("last_check_timestamp_seconds", labels, ts_check))

        last_status_rows.append(_row("last_http_status", labels, d.get("last_status_code", 0)))

    _metric(
        "last_change_timestamp_seconds",
        "Unix timestamp of the last detected change (0 if never).", "gauge",
        last_change_rows,
    )
    _metric(
        "last_check_timestamp_seconds",
        "Unix timestamp of the last completed check (0 if never).", "gauge",
        last_check_rows,
    )
    _metric(
        "last_http_status",
        "Last known HTTP status code (0 = unknown / unreachable).", "gauge",
        last_status_rows,
    )

    lines.append("")
    return "\n".join(lines)
