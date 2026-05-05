"""
WatchDiff models - shared data structures used across all modules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ChangeType(str, Enum):
    ADDED               = "added"
    REMOVED             = "removed"
    MODIFIED            = "modified"
    UNCHANGED           = "unchanged"


class DiffMode(str, Enum):
    """Strategy used by DiffEngine to compare snapshots."""
    LINE     = "line"      # default - line-by-line diff
    SEMANTIC = "semantic"  # block-level diff on <p>, <h1-h6>, <li>, <td>, <th>, <blockquote>


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BrowserOptions:
    """Options for Playwright-based fetching (requires watchdiff-core[browser])."""

    wait_for:          str        = "load"  # load | domcontentloaded | networkidle
    wait_for_selector: str | None = None    # CSS selector to wait for before capturing
    timeout:           int        = 30000   # ms - Playwright page.goto timeout


@dataclass
class WatchConfig:
    """Configuration for a single watched URL."""

    url: str
    target: str | None            = None          # CSS selector or XPath - None means full page
    interval: int                 = 300                # seconds between checks
    label: str | None             = None           # human-readable name for this watch
    headers: dict[str, str]       = field(default_factory=dict)
    timeout: int                  = 15                  # HTTP timeout in seconds
    ignore_selectors: list[str]   = field(default_factory=list)  # CSS to strip
    ignore_patterns: list[str]    = field(default_factory=list)   # regex patterns to strip
    alert: AlertConfig | None     = None
    # --- new in 0.1.3 ---
    diff_mode: str                = "line"         # "line" | "semantic"
    browser: bool                 = False          # use Playwright headless browser
    browser_options: BrowserOptions | None = None
    proxies: list[str]            = field(default_factory=list)   # rotated randomly per request
    user_agents: list[str]        = field(default_factory=list)   # rotated randomly per request
    cooldown: int                 = 0              # min seconds between two alerts (0 = disabled)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.url


@dataclass
class AlertConfig:
    """Alert configuration attached to a WatchConfig."""

    on_change: list[Callable[[DiffReport], Any]] = field(default_factory=list)
    webhooks: list[str]    = field(default_factory=list)   # Discord / Slack / custom URLs
    min_changes: int       = 1               # trigger only if >= N changes


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    """A single captured version of a watched page/selector."""

    url: str
    target: str | None
    content: str                       # cleaned text content
    raw_html: str                      # original HTML of the extracted zone
    captured_at: datetime  = field(default_factory=lambda: datetime.now(timezone.utc))
    checksum: str          = ""

    def __post_init__(self) -> None:
        self.checksum = hashlib.sha256(self.content.encode()).hexdigest()

    def is_identical_to(self, other: Snapshot) -> bool:
        return self.checksum == other.checksum


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@dataclass
class Change:
    """A single atomic change between two snapshots."""

    kind: ChangeType
    before: str | None     = None          # old value / text
    after: str | None      = None           # new value / text
    context: str | None    = None         # surrounding text hint

    def human(self) -> str:
        """Return a human-readable one-liner."""
        if self.kind == ChangeType.ADDED:
            return f"[+] Added: {self.after!r}"
        if self.kind == ChangeType.REMOVED:
            return f"[-] Removed: {self.before!r}"
        if self.kind == ChangeType.MODIFIED:
            return f"[~] Changed: {self.before!r} - {self.after!r}"
        return "[=] Unchanged"

    def __str__(self) -> str:
        return self.human()


@dataclass
class DiffReport:
    """Result of comparing two snapshots."""

    url: str
    target: str | None
    label: str
    before: Snapshot
    after: Snapshot
    changes: list[Change]  = field(default_factory=list)
    compared_at: datetime  = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    @property
    def added(self) -> list[Change]:
        return [c for c in self.changes if c.kind == ChangeType.ADDED]

    @property
    def removed(self) -> list[Change]:
        return [c for c in self.changes if c.kind == ChangeType.REMOVED]

    @property
    def modified(self) -> list[Change]:
        return [c for c in self.changes if c.kind == ChangeType.MODIFIED]

    def summary(self) -> str:
        if not self.has_changes:
            return f"[{self.label}] No changes detected."
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if self.modified:
            parts.append(f"{len(self.modified)} modified")
        return f"[{self.label}] {', '.join(parts)} - {self.compared_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"

    def as_dict(self) -> dict:
        return {
            "url":          self.url,
            "target":       self.target,
            "label":        self.label,
            "compared_at":  self.compared_at.isoformat(),
            "changes": [
                {
                    "kind":    c.kind.value,
                    "before":  c.before,
                    "after":   c.after,
                    "context": c.context,
                }
                for c in self.changes
            ],
        }
