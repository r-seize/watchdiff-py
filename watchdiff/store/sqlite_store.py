"""
SqliteStore - SQLite-backed snapshot and report store.

Uses Python's built-in sqlite3 module - no extra dependencies required.

Usage:
    from watchdiff import WatchDiff
    from watchdiff.store import SqliteStore

    wd = WatchDiff(store=SqliteStore(".watchdiff.db"))
    wd.watch("https://example.com").start()
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from watchdiff.models import DiffReport, Snapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url_key     TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    target      TEXT,
    content     TEXT    NOT NULL,
    raw_html    TEXT    NOT NULL,
    captured_at TEXT    NOT NULL,
    checksum    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url_key     TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    compared_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_key ON snapshots (url_key);
CREATE INDEX IF NOT EXISTS idx_rep_key  ON reports  (url_key);
"""


class SqliteStore:
    """
    SQLite-backed store with the same interface as Store.

    Thread-safe (check_same_thread=False + WAL mode).
    """

    def __init__(self, path: str | Path = ".watchdiff.db") -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: Snapshot) -> None:
        """Persist a new snapshot."""
        key = self._key(snapshot.url, snapshot.target)
        self._conn.execute(
            "INSERT INTO snapshots (url_key, url, target, content, raw_html, captured_at, checksum)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                snapshot.url,
                snapshot.target,
                snapshot.content,
                snapshot.raw_html,
                snapshot.captured_at.isoformat(),
                snapshot.checksum,
            ),
        )
        self._conn.commit()

    def load_latest(self, url: str, target: str | None) -> Snapshot | None:
        """Return the most recent snapshot, or None if no history exists."""
        key = self._key(url, target)
        row = self._conn.execute(
            "SELECT url, target, content, raw_html, captured_at, checksum"
            " FROM snapshots WHERE url_key = ? ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        return _row_to_snapshot(row) if row else None

    def load_history(
        self,
        url: str,
        target: str | None,
        limit: int = 50,
    ) -> list[Snapshot]:
        """Return up to `limit` most recent snapshots (newest last)."""
        key  = self._key(url, target)
        rows = self._conn.execute(
            "SELECT url, target, content, raw_html, captured_at, checksum"
            " FROM snapshots WHERE url_key = ? ORDER BY id DESC LIMIT ?",
            (key, limit),
        ).fetchall()
        return [_row_to_snapshot(r) for r in reversed(rows)]

    def clear_history(self, url: str, target: str | None) -> None:
        """Delete all snapshots and reports for a URL + target combo."""
        key = self._key(url, target)
        self._conn.execute("DELETE FROM snapshots WHERE url_key = ?", (key,))
        self._conn.execute("DELETE FROM reports   WHERE url_key = ?", (key,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def save_report(self, report: DiffReport) -> None:
        """Persist a DiffReport for audit purposes."""
        key = self._key(report.url, report.target)
        self._conn.execute(
            "INSERT INTO reports (url_key, data, compared_at) VALUES (?, ?, ?)",
            (key, json.dumps(report.as_dict()), report.compared_at.isoformat()),
        )
        self._conn.commit()

    def load_reports(
        self,
        url: str,
        target: str | None,
        limit: int = 50,
    ) -> list[dict]:
        """Return raw report dicts (newest last)."""
        key  = self._key(url, target)
        rows = self._conn.execute(
            "SELECT data FROM reports WHERE url_key = ? ORDER BY id DESC LIMIT ?",
            (key, limit),
        ).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _key(self, url: str, target: str | None) -> str:
        raw = f"{url}::{target or ''}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _row_to_snapshot(row: tuple) -> Snapshot:
    snap             = Snapshot(
        url      = row[0],
        target   = row[1],
        content  = row[2],
        raw_html = row[3],
    )
    snap.captured_at = datetime.fromisoformat(row[4])
    snap.checksum    = row[5]
    return snap
