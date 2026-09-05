"""Calendar policy: anchored month-end clamping, DST gaps forward, overlap fold=0."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from dateutil.tz import resolve_imaginary

from app.schemas.deadline_tracker import TrackerRecurrence


def utc(value: datetime) -> datetime:
    # Legacy datetime.utcnow rows and SQLite tests can return naive UTC values.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def occurrence_due(anchor: datetime, rule: dict | TrackerRecurrence | None, sequence: int) -> datetime | None:
    if sequence < 1:
        raise ValueError("Sequence starts at 1")
    if rule is None:
        return utc(anchor) if sequence == 1 else None
    rule = rule if isinstance(rule, TrackerRecurrence) else TrackerRecurrence.model_validate(rule)
    if rule.end_type == "count" and sequence > rule.count:
        return None
    local = utc(anchor).astimezone(ZoneInfo(rule.timezone))
    amount = (sequence - 1) * rule.interval
    unit = {"day": "days", "week": "weeks", "month": "months", "year": "years"}[rule.frequency]
    try:
        # Always offset the anchor, never the previous clamped/shifted occurrence.
        candidate = local if sequence == 1 else resolve_imaginary((local + relativedelta(**{unit: amount})).replace(fold=0))
    except (ValueError, OverflowError):
        return None
    candidate = utc(candidate)
    if rule.until is not None and candidate > utc(rule.until):
        return None
    return candidate


def effective_due(tracker) -> datetime:
    if tracker.recurrence or tracker.personal_task_id or tracker.linked_task_id:
        return utc(tracker.due_at)
    seconds = max(0, tracker.paused_seconds or 0)
    days = (seconds + 86399) // 86400
    return utc(tracker.due_at) + timedelta(days=days)


def first_occurrence_after(anchor, rule, after):
    """Find the first future sequence without replaying years of elapsed dates."""
    rule = rule if isinstance(rule, TrackerRecurrence) else TrackerRecurrence.model_validate(rule)
    after = utc(after)
    low, high = 1, 1
    while True:
        due = occurrence_due(anchor, rule, high)
        if due is None or due > after:
            break
        low, high = high + 1, high * 2
    # Dates (and the exhausted tail) are monotonic; calendar math stays in dateutil.
    while low < high:
        middle = (low + high) // 2
        due = occurrence_due(anchor, rule, middle)
        if due is None or due > after:
            high = middle
        else:
            low = middle + 1
    return low, occurrence_due(anchor, rule, low)
