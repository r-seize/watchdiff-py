"""
FileFetcher - reads local files instead of fetching URLs.

Used when WatchConfig.is_file is True (set automatically by WatchDiff.watch_file()).
The URL must have a "file://" prefix; file_path_from_url() strips it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def file_path_from_url(url: str) -> str:
    if url.startswith("file://"):
        return url[len("file://"):]
    return url


class FileFetcher:
    def fetch(self, config: Any) -> str:
        path = Path(file_path_from_url(config.url))
        return path.read_text(encoding="utf-8", errors="replace")


__all__ = ["FileFetcher", "file_path_from_url"]
