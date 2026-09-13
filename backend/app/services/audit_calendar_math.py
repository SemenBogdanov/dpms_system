"""Pure V5 calendar arithmetic; no clock, persistence, identity mapping or ACLs.

The caller supplies scoped records, complete historical norms, baseline and today
in the contour's calendar. Never filter historical group norms by current active,
retired or legacy status. Dates are 2000-2100; selected periods are at most 366
days. Cumulative accounting may span the entire supported history and is computed
by effective-date segments, not by expanding that history into daily records.

TargetChange.value is an integer: team meetings per weekday, or group meetings
per TEN weekdays. All arithmetic uses integer tenths; public totals are Decimal.
There are no implicit initial norms or legacy group quotas. Absences never enter
target arithmetic. Availability windows have no persistence IDs: split residuals
are values for the caller to persist atomically with its own ownership checks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal


MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)
MAX_PERIOD_DAYS = 366
MAX_FACT_RECORDS = 100_000


def validate_date(value: date) -> date:
    """Accept a calendar date, deliberately rejecting datetime and ISO strings."""
    if type(value) is not date or not MIN_DATE <= value <= MAX_DATE:
        raise ValueError("Expected a date in 2000-01-01 through 2100-12-31")
    return value


def _integer(value: int, minimum: int, maximum: int, name: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Identity must be a nonempty string")


def _group_id(value: str | None) -> None:
    if value is not None:
        _identity(value)


def _period(start: date, end: date) -> tuple[int, int]:
    first, last = validate_date(start).toordinal(), validate_date(end).toordinal()
    if not 1 <= last - first + 1 <= MAX_PERIOD_DAYS:
        raise ValueError("An inclusive period must contain 1..366 days")
    return first, last


def day_range(start: date, end: date) -> tuple[date, ...]:
    """Return a validated inclusive period, without stepping beyond MAX_DATE."""
    first, last = _period(start, end)
    return tuple(date.fromordinal(day) for day in range(first, last + 1))


def date_window(start: date, days: int = 14) -> tuple[date, ...]:
    """Keep start as the first day; truncate a requested window at MAX_DATE."""
    validate_date(start)
    _integer(days, 1, MAX_PERIOD_DAYS, "days")
    end = date.fromordinal(min(start.toordinal() + days - 1, MAX_DATE.toordinal()))
    return day_range(start, end)


def _weekdays(first: int, last: int) -> int:
    if last < first:
        return 0
    weeks, remainder = divmod(last - first + 1, 7)
    weekday = (first - 1) % 7
    return weeks * 5 + sum((weekday + offset) % 7 < 5 for offset in range(remainder))


def weekday_count(start: date, end: date) -> int:
    """Count Monday-Friday in a selected period; holidays are not applied."""
    return _weekdays(*_period(start, end))


def _decimal(tenths: int) -> Decimal:
    # Construction from text is exact even under a caller's low Decimal precision.
    whole, fraction = divmod(abs(tenths), 10)
    return Decimal(f"{'-' if tenths < 0 else ''}{whole}.{fraction}")


@dataclass(frozen=True)
class TargetChange:
    """An inclusive effective date and V5 integer norm (0..1000).

    group_id=None: value meetings per weekday. Otherwise: value meetings per
    ten weekdays, so TargetChange(day, 3, "G1") means 0.3 per weekday.
    Eligibility for NEW changes is validated by the caller, not inferred here.
    Historical changes must remain even after a group is archived or retired.
    """

    effective_from: date
    value: int
    group_id: str | None = None

    def __post_init__(self) -> None:
        validate_date(self.effective_from)
        _integer(self.value, 0, 1000, "target")
        _group_id(self.group_id)


@dataclass(frozen=True)
class TargetSchedule:
    baseline: date
    changes: tuple[TargetChange, ...]

    def __post_init__(self) -> None:
        validate_date(self.baseline)
        changes = tuple(self.changes)
        seen = set()
        daily_count = 0
        for change in changes:
            if not isinstance(change, TargetChange):
                raise ValueError("Expected TargetChange entries")
            if change.effective_from < self.baseline:
                raise ValueError("A target cannot predate the baseline")
            identity = (change.group_id, change.effective_from)
            if identity in seen:
                raise ValueError("Duplicate group/effective-date target")
            seen.add(identity)
            daily_count += change.group_id is None
        if (None, self.baseline) not in seen:
            raise ValueError("An explicit team target is required at baseline")
        if daily_count > 1024 or len(changes) - daily_count > 10_000:
            raise ValueError("Too many target changes")
        object.__setattr__(self, "changes", tuple(sorted(
            changes, key=lambda change: (change.group_id or "", change.effective_from),
        )))


def set_target(
    schedule: TargetSchedule, change: TargetChange, *, today: date,
) -> TargetSchedule:
    """Insert/replace only this scope/date, preserving past and later versions."""
    validate_date(today)
    if change.effective_from < today:
        raise ValueError("A target edit cannot take effect before today")
    retained = tuple(
        entry for entry in schedule.changes
        if (entry.group_id, entry.effective_from) != (change.group_id, change.effective_from)
    )
    return TargetSchedule(schedule.baseline, (*retained, change))


def _target_tenths(
    schedule: TargetSchedule, start: date, end: date, group_id: str | None,
) -> int:
    cursor = max(start, schedule.baseline).toordinal()
    last = end.toordinal()
    if cursor > last:
        return 0
    rate = total = 0
    for change in schedule.changes:
        if change.group_id != group_id:
            continue
        effective = change.effective_from.toordinal()
        if effective > last:
            break
        if effective > cursor:
            total += _weekdays(cursor, effective - 1) * rate
            cursor = effective
        rate = change.value * 10 if group_id is None else change.value
    return total + _weekdays(cursor, last) * rate


def target_between(
    schedule: TargetSchedule, start: date, end: date, *, group_id: str | None = None,
) -> Decimal:
    """Sum weekday norms in a selected period; missing group history means zero."""
    _period(start, end)
    _group_id(group_id)
    return _decimal(_target_tenths(schedule, start, end, group_id))


def daily_target(
    schedule: TargetSchedule, day: date, *, group_id: str | None = None,
) -> Decimal:
    return target_between(schedule, day, day, group_id=group_id)


@dataclass(frozen=True)
class MeetingRecord:
    """Minimal counting projection, not a meeting persistence/domain model.

    record_id is the stable identity of this row, never a derived slot, plan link
    or fuzzy match. Repeated identical rows collapse; conflicting copies fail.
    Duration validates a positive half-hour multiple but never weights a fact.
    """

    record_id: str
    day: date
    group_id: str | None = None
    kind: Literal["fact", "plan"] = "fact"
    outcome: Literal["completed", "cancelled", "failed"] | None = "completed"
    duration_minutes: int = 60

    def __post_init__(self) -> None:
        _identity(self.record_id)
        validate_date(self.day)
        _group_id(self.group_id)
        if self.kind not in ("fact", "plan"):
            raise ValueError("Unknown record kind")
        if self.outcome not in ("completed", "cancelled", "failed", None):
            raise ValueError("Unknown meeting outcome")
        _integer(self.duration_minutes, 30, 1440, "duration_minutes")
        if self.duration_minutes % 30:
            raise ValueError("Duration must be a multiple of 30 minutes")


def _count_completed(
    records: Iterable[MeetingRecord], start: date, end: date | None, group_id: str | None,
) -> int:
    seen: dict[str, MeetingRecord] = {}
    completed = 0
    for index, record in enumerate(records):
        if index >= MAX_FACT_RECORDS:
            raise ValueError("Too many meeting records")
        if not isinstance(record, MeetingRecord):
            raise ValueError("Expected MeetingRecord entries")
        previous = seen.get(record.record_id)
        if previous is not None:
            if previous != record:
                raise ValueError("Conflicting copies of a meeting identity")
            continue
        seen[record.record_id] = record
        if (
            end is not None and start <= record.day <= end
            and record.kind == "fact" and record.outcome == "completed"
            and (group_id is None or record.group_id == group_id)
        ):
            completed += 1
    return completed


def count_completed(
    records: Iterable[MeetingRecord], start: date, end: date, *, group_id: str | None = None,
) -> int:
    """Count distinct completed facts in a selected period, including weekends."""
    _period(start, end)
    _group_id(group_id)
    return _count_completed(records, start, end, group_id)


@dataclass(frozen=True)
class CumulativeTotals:
    """through=None means there are no closed days at/after baseline yet."""

    through: date | None
    target: Decimal
    completed: int
    balance: Decimal
    backlog: Decimal


def cumulative(
    schedule: TargetSchedule, records: Iterable[MeetingRecord], period_end: date,
    *, today: date, group_id: str | None = None,
) -> CumulativeTotals:
    """Accumulate baseline..min(period_end, yesterday), retaining signed surplus.

    Today/future facts are excluded from the same closed-day interval as targets.
    The caller must pass all facts since baseline, not just the visible page.
    Historical completeness is deliberately not inferred from a numeric backlog.
    """
    validate_date(period_end)
    validate_date(today)
    _group_id(group_id)
    last = min(period_end.toordinal(), today.toordinal() - 1)
    through = date.fromordinal(last) if last >= schedule.baseline.toordinal() else None
    target = _target_tenths(schedule, schedule.baseline, through, group_id) if through else 0
    completed = _count_completed(records, schedule.baseline, through, group_id)
    balance = target - completed * 10
    return CumulativeTotals(
        through, _decimal(target), completed, _decimal(balance), _decimal(max(0, balance)),
    )


def _minute_interval(start: int, end: int) -> None:
    _integer(start, 0, 1440, "start_minute")
    _integer(end, 0, 1440, "end_minute")
    if start >= end or start % 30 or end % 30:
        raise ValueError("Expected a positive half-hour interval within 00:00..24:00")


@dataclass(frozen=True)
class AvailabilityWindow:
    """Explicit free/busy interval [start_minute, end_minute); gaps are unknown."""

    person_id: str
    day: date
    start_minute: int
    end_minute: int
    available: bool

    def __post_init__(self) -> None:
        _identity(self.person_id)
        validate_date(self.day)
        _minute_interval(self.start_minute, self.end_minute)
        if type(self.available) is not bool:
            raise ValueError("An explicit window must be free or busy")


@dataclass(frozen=True)
class Absence:
    """Inclusive absence projection; reasons/history and permissions live upstream."""

    person_id: str
    start: date
    end: date

    def __post_init__(self) -> None:
        _identity(self.person_id)
        _period(self.start, self.end)


def absent_people(absences: Iterable[Absence], day: date) -> frozenset[str]:
    validate_date(day)
    result = set()
    for absence in absences:
        if not isinstance(absence, Absence):
            raise ValueError("Expected Absence entries")
        if absence.start <= day <= absence.end:
            result.add(absence.person_id)
    return frozenset(result)


def _availability_query(person_id: str, day: date, start_minute: int, end_minute: int) -> None:
    _identity(person_id)
    validate_date(day)
    _minute_interval(start_minute, end_minute)


def paint_availability(
    windows: Iterable[AvailabilityWindow], *, person_id: str, day: date,
    start_minute: int, end_minute: int, value: bool | None,
) -> tuple[AvailabilityWindow, ...]:
    """Replace just this person's interval; None clears it, preserving residuals.

    A full-day edit uses 0..1440. No caller data is mutated, including on error.
    Overlapping imported windows are all split; new paint overrides their state
    only inside the painted interval. Unrelated records keep their values/order.
    """
    _availability_query(person_id, day, start_minute, end_minute)
    if value is not None and type(value) is not bool:
        raise ValueError("Paint value must be True, False or None")
    result = []
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise ValueError("Expected AvailabilityWindow entries")
        if (
            window.person_id != person_id or window.day != day
            or window.end_minute <= start_minute or window.start_minute >= end_minute
        ):
            result.append(window)
            continue
        if window.start_minute < start_minute:
            result.append(replace(window, end_minute=start_minute))
        if window.end_minute > end_minute:
            result.append(replace(window, start_minute=end_minute))
    if value is not None:
        result.append(AvailabilityWindow(person_id, day, start_minute, end_minute, value))
    return tuple(result)


def availability_value(
    windows: Iterable[AvailabilityWindow], *, person_id: str, day: date,
    start_minute: int, end_minute: int, absences: Iterable[Absence] = (),
) -> bool | None:
    """False for absence/any busy overlap, True only for full free coverage.

    Otherwise return None (unknown). Query endpoints, like paint endpoints, are
    half-hour aligned. Absence blocks a query but never erases stored windows.
    """
    _availability_query(person_id, day, start_minute, end_minute)
    blocked = person_id in absent_people(absences, day)
    free = []
    for window in windows:
        if not isinstance(window, AvailabilityWindow):
            raise ValueError("Expected AvailabilityWindow entries")
        if (
            window.person_id == person_id and window.day == day
            and window.start_minute < end_minute and window.end_minute > start_minute
        ):
            if window.available:
                free.append(window)
            else:
                blocked = True
    if blocked:
        return False
    covered = start_minute
    for window in sorted(free, key=lambda entry: entry.start_minute):
        if window.start_minute > covered:
            break
        covered = max(covered, window.end_minute)
        if covered >= end_minute:
            return True
    return None
