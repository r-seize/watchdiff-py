from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    result: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if base == "*":
                rng = range(lo, hi + 1, step)
            elif "-" in base:
                a, b = base.split("-", 1)
                rng = range(int(a), int(b) + 1, step)
            else:
                rng = range(int(base), hi + 1, step)
            result.update(rng)
        elif "-" in part:
            a, b = part.split("-", 1)
            result.update(range(int(a), int(b) + 1))
        elif part == "*":
            result.update(range(lo, hi + 1))
        else:
            result.add(int(part))
    return result


def next_cron_run(expr: str, from_dt: datetime | None = None) -> datetime:
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got: {expr!r}")

    minutes   = _parse_field(fields[0], 0, 59)
    hours     = _parse_field(fields[1], 0, 23)
    doms      = _parse_field(fields[2], 1, 31)
    months    = _parse_field(fields[3], 1, 12)
    dows      = _parse_field(fields[4], 0, 6)

    base = from_dt if from_dt is not None else datetime.now(timezone.utc)
    candidate = base.replace(second=0, microsecond=0) + timedelta(minutes=1)

    limit = base + timedelta(days=366)
    while candidate <= limit:
        if candidate.month not in months:
            candidate = candidate.replace(day=1, hour=0, minute=0) + timedelta(
                days=_days_to_next_month(candidate, months)
            )
            continue
        if candidate.day not in doms or candidate.weekday() not in _iso_to_cron_dows(dows):
            candidate = candidate.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if candidate.hour not in hours:
            candidate = candidate.replace(minute=0) + timedelta(hours=1)
            continue
        if candidate.minute not in minutes:
            candidate += timedelta(minutes=1)
            continue
        return candidate

    raise ValueError(f"No valid next run found within 1 year for expression: {expr!r}")


def _days_to_next_month(dt: datetime, months: set[int]) -> int:
    year, month = dt.year, dt.month
    for _ in range(12):
        month += 1
        if month > 12:
            month = 1
            year += 1
        if month in months:
            first_of_target = datetime(year, month, 1, tzinfo=dt.tzinfo)
            return (first_of_target - dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).days
    return 366


def _iso_to_cron_dows(dows: set[int]) -> set[int]:
    result: set[int] = set()
    for d in dows:
        if d == 0 or d == 7:
            result.add(6)
        else:
            result.add(d - 1)
    return result
