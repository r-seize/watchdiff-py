"""
Exporter - export snapshots and diff reports to CSV or XLSX.

CSV:  stdlib only - no extra dependencies.
XLSX: requires openpyxl (pip install "watchdiff-core[xlsx]").

Usage:
    from watchdiff import WatchDiff

    wd = WatchDiff()
    wd.watch("https://example.com")

    # CSV (always available)
    wd.export_reports_csv("https://example.com", dest="reports.csv")
    wd.export_snapshots_csv("https://example.com", dest="snaps.csv")

    # XLSX (requires openpyxl)
    wd.export_reports_xlsx("https://example.com", dest="reports.xlsx")
    wd.export_snapshots_xlsx("https://example.com", dest="snaps.xlsx")
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from watchdiff.store.store import Store

_SNAP_HEADERS = ["url", "target", "captured_at", "checksum", "content_preview"]
_REP_HEADERS  = ["url", "target", "label", "compared_at", "added", "removed", "modified", "total"]


class Exporter:
    """Generates CSV and XLSX exports from a store."""

    def __init__(self, store: Store) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public API - CSV
    # ------------------------------------------------------------------

    def snapshots_csv(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path | None = None,
    ) -> str:
        """
        Export snapshots to CSV.

        Args:
            url:    Watched URL.
            target: CSS selector or XPath (None for full page).
            limit:  Maximum number of snapshots to include.
            dest:   If provided, write CSV to this file path.

        Returns:
            CSV string.
        """
        rows = self._snap_rows(url, target, limit)
        return self._write_csv(_SNAP_HEADERS, rows, dest)

    def reports_csv(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path | None = None,
    ) -> str:
        """
        Export diff reports to CSV.

        Args:
            url:    Watched URL.
            target: CSS selector or XPath (None for full page).
            limit:  Maximum number of reports to include.
            dest:   If provided, write CSV to this file path.

        Returns:
            CSV string.
        """
        rows = self._rep_rows(url, target, limit)
        return self._write_csv(_REP_HEADERS, rows, dest)

    # ------------------------------------------------------------------
    # Public API - XLSX
    # ------------------------------------------------------------------

    def snapshots_xlsx(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path = "snapshots.xlsx",
    ) -> Path:
        """
        Export snapshots to XLSX.

        Args:
            url:    Watched URL.
            target: CSS selector or XPath (None for full page).
            limit:  Maximum number of snapshots to include.
            dest:   Output file path (default: snapshots.xlsx).

        Returns:
            Path to the written XLSX file.

        Raises:
            ImportError: if openpyxl is not installed.
        """
        rows = self._snap_rows(url, target, limit)
        return self._write_xlsx(_SNAP_HEADERS, rows, dest)

    def reports_xlsx(
        self,
        url: str,
        target: str | None = None,
        limit: int = 500,
        dest: str | Path = "reports.xlsx",
    ) -> Path:
        """
        Export diff reports to XLSX.

        Args:
            url:    Watched URL.
            target: CSS selector or XPath (None for full page).
            limit:  Maximum number of reports to include.
            dest:   Output file path (default: reports.xlsx).

        Returns:
            Path to the written XLSX file.

        Raises:
            ImportError: if openpyxl is not installed.
        """
        rows = self._rep_rows(url, target, limit)
        return self._write_xlsx(_REP_HEADERS, rows, dest)

    # ------------------------------------------------------------------
    # Internal - data collection
    # ------------------------------------------------------------------

    def _snap_rows(self, url: str, target: str | None, limit: int) -> list[list]:
        snapshots = self._store.load_history(url, target, limit=limit)
        return [
            [
                s.url,
                s.target or "",
                s.captured_at.isoformat(),
                s.checksum,
                s.content[:500].replace("\n", " "),
            ]
            for s in snapshots
        ]

    def _rep_rows(self, url: str, target: str | None, limit: int) -> list[list]:
        reports = self._store.load_reports(url, target, limit=limit)
        rows = []
        for r in reports:
            changes  = r.get("changes", [])
            added    = sum(1 for c in changes if c.get("kind") == "added")
            removed  = sum(1 for c in changes if c.get("kind") == "removed")
            modified = sum(1 for c in changes if c.get("kind") == "modified")
            rows.append([
                r.get("url", ""),
                r.get("target") or "",
                r.get("label", ""),
                r.get("compared_at", ""),
                added,
                removed,
                modified,
                len(changes),
            ])
        return rows

    # ------------------------------------------------------------------
    # Internal - writers
    # ------------------------------------------------------------------

    def _write_csv(
        self,
        headers: list[str],
        rows: list[list],
        dest: str | Path | None,
    ) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        text = buf.getvalue()
        if dest is not None:
            Path(dest).write_text(text, encoding="utf-8")
        return text

    def _write_xlsx(
        self,
        headers: list[str],
        rows: list[list],
        dest: str | Path,
    ) -> Path:
        try:
            import openpyxl  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "openpyxl is required for XLSX export. "
                "Run: pip install 'watchdiff-core[xlsx]'"
            ) from exc

        wb  = openpyxl.Workbook()
        ws  = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)

        path = Path(dest)
        wb.save(str(path))
        return path
