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
    WORD     = "word"      # word-by-word diff, coalescence removed+added -> modified
    JSON     = "json"      # recursive key-path diff, fallback line if not valid JSON
    RSS      = "rss"       # item-level diff for RSS 2.0 / Atom feeds (by guid/id)


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
    target: str | None               = None     # CSS selector or XPath - None means full page
    interval: int                    = 300       # seconds between checks
    label: str | None                = None      # human-readable name for this watch
    headers: dict[str, str]          = field(default_factory=dict)
    timeout: int                     = 15        # HTTP timeout in seconds
    ignore_selectors: list[str]      = field(default_factory=list)
    ignore_patterns: list[str]       = field(default_factory=list)
    alert: AlertConfig | None        = None
    # --- new in 0.1.4 ---
    diff_mode: str                   = "line"   # "line" | "semantic" | "word" | "json"
    browser: bool                    = False
    browser_options: BrowserOptions | None = None
    proxies: list[str]               = field(default_factory=list)
    user_agents: list[str]           = field(default_factory=list)
    cooldown: int                    = 0        # min seconds between two alerts (0 = disabled)
    retries: int                     = 0        # HTTP retry attempts on transient errors
    retry_delay: float               = 1.0      # base delay in seconds for exponential backoff
    jitter: float                    = 0.0      # fraction 0-1: interval ± interval*jitter*rand
    dry_run: bool                    = False    # fetch+diff without persisting or alerting
    max_snapshots: int | None        = None     # prune history to this many entries after each save
    change_threshold: float | None   = None     # min changed/total ratio to trigger alert
    ignore_numbers: bool             = False    # strip all numbers before diffing
    alert_if_no_change_after: int | None = None # fire on_silence if no change for N seconds
    on_error: Callable[[Exception, WatchConfig], None] | None = None
    on_silence: Callable[[SilenceInfo], None] | None = None
    # --- new in 0.1.5 ---
    archive_html: bool                     = False    # save full HTML to disk on every change
    screenshot_on_change: bool             = False    # save PNG screenshot on change (browser=True required)
    change_spike_window: int | None        = None     # spike detection window in seconds
    change_spike_threshold: int | None     = None     # alert when this many changes in window
    on_spike: Callable[[SpikeInfo], None] | None = None
    # --- new in 0.1.6 ---
    alert_on_status_change: bool                         = False
    on_status_change: Callable[[StatusChangeInfo], None] | None = None

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.url


@dataclass
class AlertConfig:
    """Alert configuration attached to a WatchConfig."""

    on_change: list[Callable[[DiffReport], Any]] = field(default_factory=list)
    webhooks: list[str]    = field(default_factory=list)
    min_changes: int       = 1
    webhook_retries: int   = 3  # retry attempts for failed webhook deliveries (0 = no retry)


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
    before: str | None     = None
    after: str | None      = None
    context: str | None    = None

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


# ---------------------------------------------------------------------------
# Status / silence
# ---------------------------------------------------------------------------

@dataclass
class WatcherStatus:
    """Live status snapshot for a single watcher."""

    url: str
    label: str
    target: str | None
    interval: int
    paused: bool
    last_check_at: datetime | None
    next_check_at: datetime | None
    last_change_at: datetime | None
    checks_count: int
    changes_count: int
    errors_count: int       = 0
    last_status_code: int   = 0   # 0 = unknown, 200 = ok

    def as_dict(self) -> dict:
        def _iso(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        return {
            "url":              self.url,
            "label":            self.label,
            "target":           self.target,
            "interval":         self.interval,
            "paused":           self.paused,
            "last_check_at":    _iso(self.last_check_at),
            "next_check_at":    _iso(self.next_check_at),
            "last_change_at":   _iso(self.last_change_at),
            "checks_count":     self.checks_count,
            "changes_count":    self.changes_count,
            "errors_count":     self.errors_count,
            "last_status_code": self.last_status_code,
        }


@dataclass
class SilenceInfo:
    """Payload passed to the on_silence callback."""

    url: str
    label: str
    seconds_since_last_change: float


@dataclass
class SpikeInfo:
    """Payload passed to the on_spike callback."""

    url: str
    label: str
    changes_in_window: int
    window_seconds: int


@dataclass
class StatusChangeInfo:
    """Payload passed to the on_status_change callback."""

    url:             str
    label:           str
    previous_status: int
    current_status:  int
