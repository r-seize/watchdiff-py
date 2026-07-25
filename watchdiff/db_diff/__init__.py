from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from watchdiff.db_models import (
    ColumnDef,
    DbChange,
    DbChangeKind,
    DbDiffMode,
    DbDiffReport,
    DbSnapshot,
    DbWatchConfig,
    Row,
    RowModification,
)


class DbDiffEngine:
    def compare(self, before: DbSnapshot, after: DbSnapshot, config: DbWatchConfig) -> DbDiffReport:
        changes = self._compute_changes(before, after, config)
        return DbDiffReport(
            connection_string=config.connection_string,
            table=config.table,
            label=config.label,
            before=before,
            after=after,
            changes=changes,
            diff_mode=config.diff_mode,
            compared_at=datetime.now(timezone.utc),
        )

    def _compute_changes(
        self, before: DbSnapshot, after: DbSnapshot, config: DbWatchConfig
    ) -> list[DbChange]:
        if config.diff_mode == DbDiffMode.ROW:
            return self._diff_rows(before.rows, after.rows, config)
        if config.diff_mode == DbDiffMode.SCHEMA:
            return self._diff_schema(before.schema or [], after.schema or [])
        if config.diff_mode == DbDiffMode.AGGREGATE:
            return self._diff_aggregate(before.rows, after.rows, config)
        if config.diff_mode == DbDiffMode.VALUE:
            return self._diff_value(before.rows, after.rows, config)
        return self._diff_rows(before.rows, after.rows, config)

    # ------------------------------------------------------------------
    # row mode
    # ------------------------------------------------------------------

    def _diff_rows(self, before: list[Row], after: list[Row], config: DbWatchConfig) -> list[DbChange]:
        pk     = config.primary_key or []
        ignore = set(config.ignore_columns or [])
        changes: list[DbChange] = []

        if not pk:
            before_keys = {self._ser(self._filter(r, ignore)): r for r in before}
            after_keys: set[str] = set()
            for row in after:
                key = self._ser(self._filter(row, ignore))
                after_keys.add(key)
                if key not in before_keys and config.alert_on_insert:
                    changes.append(DbChange(kind=DbChangeKind.INSERTED, row=row, row_key=key))
            for key, row in before_keys.items():
                if key not in after_keys and config.alert_on_delete:
                    changes.append(DbChange(kind=DbChangeKind.DELETED, row=row, row_key=key))
            return changes

        before_map = {self._row_key(r, pk): r for r in before}
        after_map  = {self._row_key(r, pk): r for r in after}

        for key, row in after_map.items():
            if key not in before_map and config.alert_on_insert:
                changes.append(DbChange(kind=DbChangeKind.INSERTED, row_key=key, row=row))

        for key, row in before_map.items():
            if key not in after_map and config.alert_on_delete:
                changes.append(DbChange(kind=DbChangeKind.DELETED, row_key=key, row=row))

        if config.alert_on_update:
            for key, after_row in after_map.items():
                before_row = before_map.get(key)
                if before_row is None:
                    continue
                mods = self._diff_single_row(before_row, after_row, ignore)
                if mods:
                    changes.append(DbChange(kind=DbChangeKind.UPDATED, row_key=key, modifications=mods))

        return changes

    def _row_key(self, row: Row, pk: list[str]) -> str:
        return json.dumps([row.get(k) for k in pk], default=str)

    def _filter(self, row: Row, ignore: set[str]) -> Row:
        return {k: v for k, v in row.items() if k not in ignore}

    def _ser(self, row: Row) -> str:
        return json.dumps(row, default=str, sort_keys=True)

    def _diff_single_row(self, before: Row, after: Row, ignore: set[str]) -> list[RowModification]:
        mods: list[RowModification] = []
        for col in set(before) | set(after):
            if col in ignore:
                continue
            b, a = before.get(col), after.get(col)
            if json.dumps(b, default=str) != json.dumps(a, default=str):
                mods.append(RowModification(column=col, before=b, after=a))
        return mods

    # ------------------------------------------------------------------
    # schema mode
    # ------------------------------------------------------------------

    def _diff_schema(self, before: list[ColumnDef], after: list[ColumnDef]) -> list[DbChange]:
        changes: list[DbChange] = []
        before_map = {c.name: c for c in before}
        after_map  = {c.name: c for c in after}

        for name, col in after_map.items():
            if name not in before_map:
                changes.append(DbChange(kind=DbChangeKind.SCHEMA_CHANGED, column=name, before=None, after=col, context="column added"))

        for name, col in before_map.items():
            if name not in after_map:
                changes.append(DbChange(kind=DbChangeKind.SCHEMA_CHANGED, column=name, before=col, after=None, context="column removed"))

        for name, ac in after_map.items():
            bc = before_map.get(name)
            if not bc:
                continue
            if bc.type != ac.type:
                changes.append(DbChange(kind=DbChangeKind.SCHEMA_CHANGED, column=name, before=bc.type, after=ac.type, context="type changed"))
            if bc.nullable != ac.nullable:
                changes.append(DbChange(kind=DbChangeKind.SCHEMA_CHANGED, column=name, before=bc.nullable, after=ac.nullable, context="nullability changed"))

        return changes

    # ------------------------------------------------------------------
    # aggregate mode
    # ------------------------------------------------------------------

    def _diff_aggregate(self, before: list[Row], after: list[Row], config: DbWatchConfig) -> list[DbChange]:
        b_val = self._scalar(before)
        a_val = self._scalar(after)
        if b_val is None or a_val is None or b_val == a_val:
            return []

        pct       = abs((a_val - b_val) / b_val) * 100 if b_val != 0 else 100.0
        threshold = config.threshold or 0.0

        if pct < threshold:
            return []

        return [DbChange(
            kind=DbChangeKind.THRESHOLD_EXCEEDED,
            before=b_val,
            after=a_val,
            context=f"{pct:.2f}% change (threshold: {threshold}%)",
        )]

    def _scalar(self, rows: list[Row]) -> float | None:
        if not rows:
            return None
        val = next(iter(rows[0].values()), None)
        try:
            return float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # value mode
    # ------------------------------------------------------------------

    def _diff_value(self, before: list[Row], after: list[Row], config: DbWatchConfig) -> list[DbChange]:
        b_val = next(iter(before[0].values()), None) if before else None
        a_val = next(iter(after[0].values()),  None) if after  else None
        if json.dumps(b_val, default=str) == json.dumps(a_val, default=str):
            return []
        return [DbChange(kind=DbChangeKind.VALUE_CHANGED, before=b_val, after=a_val, context=config.table)]
