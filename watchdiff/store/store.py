"""
Store - persists snapshots and diff reports to disk.

Format: one JSON file per watched URL, stored in a configurable directory.
Each file contains an ordered list of Snapshot dicts (newest last).

Why JSON and not SQLite?
  - Zero external dependencies for storage.
  - Easy to inspect, back up, or pipe to other tools.
  - Fine for typical monitoring workloads (< thousands of entries).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from watchdiff.models import DiffReport, Snapshot


class Store:
    """Filesystem-based snapshot store."""

    def __init__(self, directory: str | Path = ".watchdiff") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> None:
        """Append a snapshot to the history for its URL + target combo."""
        path    = self._snapshot_path(snapshot.url, snapshot.target)
        history = self._load_raw(path)
        history.append(_snapshot_to_dict(snapshot))
        self._save_raw(path, history)

    def load_latest(self, url: str, target: str | None) -> Snapshot | None:
        """Return the most recent snapshot, or None if no history exists."""
        path = self._snapshot_path(url, target)
        if not path.exists():
            return None
        history = self._load_raw(path)
        if not history:
            return None
        return _dict_to_snapshot(history[-1])

    def load_history(
        self,
        url: str,
        target: str | None,
        limit: int = 50,
    ) -> list[Snapshot]:
        """Return up to `limit` most recent snapshots (newest last)."""
        path = self._snapshot_path(url, target)
        if not path.exists():
            return []
        history = self._load_raw(path)
        return [_dict_to_snapshot(d) for d in history[-limit:]]

    def clear_history(self, url: str, target: str | None) -> None:
        """Delete all stored snapshots for a URL + target combo."""
        path = self._snapshot_path(url, target)
        if path.exists():
            path.unlink()
        report_path = self._report_path(url, target)
        if report_path.exists():
            report_path.unlink()

    # ------------------------------------------------------------------
    # Diff reports
    # ------------------------------------------------------------------

    def save_report(self, report: DiffReport) -> None:
        """Persist a DiffReport for audit purposes."""
        path    = self._report_path(report.url, report.target)
        reports = self._load_raw(path)
        reports.append(report.as_dict())
        self._save_raw(path, reports)

    def load_reports(
        self,
        url: str,
        target: str | None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw report dicts (newest last)."""
        path = self._report_path(url, target)
        if not path.exists():
            return []
        return self._load_raw(path)[-limit:]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _key(self, url: str, target: str | None) -> str:
        """Stable short key derived from URL + target."""
        raw = f"{url}::{target or ''}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _snapshot_path(self, url: str, target: str | None) -> Path:
        return self.directory / f"snap_{self._key(url, target)}.json"

    def _report_path(self, url: str, target: str | None) -> Path:
        return self.directory / f"report_{self._key(url, target)}.json"

    def _load_raw(self, path: Path) -> list:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_raw(self, path: Path, data: list) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _snapshot_to_dict(s: Snapshot) -> dict:
    return {
        "url":          s.url,
        "target":       s.target,
        "content":      s.content,
        "raw_html":     s.raw_html,
        "captured_at":  s.captured_at.isoformat(),
        "checksum":     s.checksum,
    }


def _dict_to_snapshot(d: dict) -> Snapshot:
    snap             = Snapshot(
        url      = d["url"],
        target   = d.get("target"),
        content  = d["content"],
        raw_html = d.get("raw_html", ""),
    )
    snap.captured_at = datetime.fromisoformat(d["captured_at"])
    snap.checksum    = d["checksum"]
    return snap
