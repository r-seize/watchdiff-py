from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Enums / primitives
# ---------------------------------------------------------------------------

Row = dict[str, Any]


class DbDiffMode(str, Enum):
    ROW       = "row"
    SCHEMA    = "schema"
    AGGREGATE = "aggregate"
    VALUE     = "value"


class DbDriver(str, Enum):
    SQLITE   = "sqlite"
    POSTGRES = "postgres"
    MYSQL    = "mysql"


class DbChangeKind(str, Enum):
    INSERTED           = "inserted"
    DELETED            = "deleted"
    UPDATED            = "updated"
    SCHEMA_CHANGED     = "schema_changed"
    THRESHOLD_EXCEEDED = "threshold_exceeded"
    VALUE_CHANGED      = "value_changed"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class ColumnDef:
    name:          str
    type:          str
    nullable:      bool
    primary_key:   bool
    default_value: str | None = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DbWatchConfig:
    connection_string: str
    driver:            DbDriver
    table:             str
    query:             str | None                                          = None
    primary_key:       list[str]                                           = field(default_factory=list)
    ignore_columns:    list[str]                                           = field(default_factory=list)
    diff_mode:         DbDiffMode                                          = DbDiffMode.ROW
    interval:          int                                                 = 300
    label:             str                                                 = ""
    dry_run:           bool                                                = False
    cooldown:          int | None                                          = None
    max_snapshots:     int | None                                          = None
    alert_on_insert:   bool                                                = True
    alert_on_delete:   bool                                                = True
    alert_on_update:   bool                                                = True
    threshold:         float | None                                        = None
    webhooks:          list[str]                                           = field(default_factory=list)
    webhook_retries:   int                                                 = 3
    on_change:         Callable[[DbDiffReport], Any] | None               = None
    on_error:          Callable[[Exception, DbWatchConfig], None] | None  = None
    on_schema_change:  Callable[[SchemaChangeInfo], None] | None          = None
    on_threshold:      Callable[[ThresholdInfo], None] | None             = None

    def __post_init__(self) -> None:
        if not self.label:
            hint = self.connection_string.split("@")[-1] if "@" in self.connection_string else self.connection_string
            self.label = f"{self.table} @ {hint}"


def make_db_watch_config(
    connection_string: str,
    table: str,
    **kwargs: Any,
) -> DbWatchConfig:
    if connection_string.startswith("sqlite://"):
        driver = DbDriver.SQLITE
    elif connection_string.startswith("postgresql://") or connection_string.startswith("postgres://"):
        driver = DbDriver.POSTGRES
    elif connection_string.startswith("mysql://"):
        driver = DbDriver.MYSQL
    else:
        driver = DbDriver.SQLITE

    return DbWatchConfig(connection_string=connection_string, driver=driver, table=table, **kwargs)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

@dataclass
class DbSnapshot:
    connection_string: str
    table:             str
    rows:              list[Row]
    captured_at:       datetime
    checksum:          str
    row_count:         int
    schema:            list[ColumnDef] | None = None

    @classmethod
    def create(
        cls,
        connection_string: str,
        table: str,
        rows: list[Row],
        schema: list[ColumnDef] | None = None,
    ) -> DbSnapshot:
        checksum = hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()
        return cls(
            connection_string=connection_string,
            table=table,
            rows=rows,
            schema=schema,
            captured_at=datetime.now(timezone.utc),
            checksum=checksum,
            row_count=len(rows),
        )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@dataclass
class RowModification:
    column: str
    before: Any
    after:  Any


@dataclass
class DbChange:
    kind:          DbChangeKind
    row_key:       str | None                   = None
    row:           Row | None                   = None
    modifications: list[RowModification] | None = None
    column:        str | None                   = None
    before:        Any                          = None
    after:         Any                          = None
    context:       str | None                   = None


@dataclass
class DbDiffReport:
    connection_string: str
    table:             str
    label:             str
    before:            DbSnapshot
    after:             DbSnapshot
    changes:           list[DbChange]
    diff_mode:         DbDiffMode
    compared_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    def summary(self) -> str:
        return db_report_summary(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_string": self.connection_string,
            "table":             self.table,
            "label":             self.label,
            "diff_mode":         self.diff_mode.value,
            "compared_at":       self.compared_at.isoformat(),
            "rows_before":       self.before.row_count,
            "rows_after":        self.after.row_count,
            "changes": [
                {
                    "kind":    c.kind.value,
                    "row_key": c.row_key,
                    "context": c.context,
                    "before":  str(c.before) if c.before is not None else None,
                    "after":   str(c.after)  if c.after  is not None else None,
                }
                for c in self.changes
            ],
        }


# ---------------------------------------------------------------------------
# Callback info types
# ---------------------------------------------------------------------------

@dataclass
class SchemaChangeInfo:
    connection_string: str
    table:             str
    label:             str
    changes:           list[DbChange]


@dataclass
class ThresholdInfo:
    connection_string: str
    table:             str
    label:             str
    previous_value:    float
    current_value:     float
    change_percent:    float
    threshold:         float


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@dataclass
class DbWatcherStatus:
    connection_string: str
    table:             str
    label:             str
    diff_mode:         str
    interval:          int
    paused:            bool
    last_check_at:     datetime | None
    next_check_at:     datetime | None
    last_change_at:    datetime | None
    checks_count:      int
    changes_count:     int
    errors_count:      int

    def as_dict(self) -> dict[str, Any]:
        def _iso(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        return {
            "connection_string": self.connection_string,
            "table":             self.table,
            "label":             self.label,
            "diff_mode":         self.diff_mode,
            "interval":          self.interval,
            "paused":            self.paused,
            "last_check_at":     _iso(self.last_check_at),
            "next_check_at":     _iso(self.next_check_at),
            "last_change_at":    _iso(self.last_change_at),
            "checks_count":      self.checks_count,
            "changes_count":     self.changes_count,
            "errors_count":      self.errors_count,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def db_snapshot_key(connection_string: str, table: str) -> str:
    h = hashlib.sha256(f"{connection_string}::{table}".encode()).hexdigest()[:12]
    return f"db::{h}::{table}"


def db_has_changes(report: DbDiffReport) -> bool:
    return bool(report.changes)


def db_report_summary(report: DbDiffReport) -> str:
    if not db_has_changes(report):
        return f"[{report.label}] No changes detected."
    inserted = sum(1 for c in report.changes if c.kind == DbChangeKind.INSERTED)
    deleted  = sum(1 for c in report.changes if c.kind == DbChangeKind.DELETED)
    updated  = sum(1 for c in report.changes if c.kind == DbChangeKind.UPDATED)
    parts: list[str] = []
    if inserted: parts.append(f"{inserted} inserted")
    if deleted:  parts.append(f"{deleted} deleted")
    if updated:  parts.append(f"{updated} updated")
    ts = report.compared_at.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{report.label}] {', '.join(parts)} — {ts} UTC"
