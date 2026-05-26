"""Effective monthly plan helpers."""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass(frozen=True)
class EffectivePlan:
    full_target: Decimal
    effective_target: Decimal
    partial_month_factor: Decimal
    onboarding_factor: Decimal
    absence_working_days: int
    onboarding_active: bool
    plan_started_at: datetime | None
    onboarding_started_at: datetime | None
    onboarding_until: datetime | None
    adjustment_reasons: list[str]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _round_q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def add_months(value: datetime, months: int) -> datetime:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def working_days_in_month(year: int, month: int) -> int:
    return working_days_between(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def working_days_between(start: date, end: date, excluded_dates: set[date] | None = None) -> int:
    if end < start:
        return 0
    excluded = excluded_dates or set()
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in excluded:
            count += 1
        current = date.fromordinal(current.toordinal() + 1)
    return count


def current_plan_window(
    user: Any,
    now: datetime | None = None,
    absence_dates: set[date] | None = None,
) -> tuple[int, int, int]:
    """Return elapsed, total, remaining working days for the user's current plan window."""
    current = _as_utc(now) or datetime.now(timezone.utc)
    month_start = date(current.year, current.month, 1)
    month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
    start = month_start
    plan_started_at = _as_utc(getattr(user, "plan_started_at", None))
    if plan_started_at and plan_started_at.year == current.year and plan_started_at.month == current.month:
        start = max(start, plan_started_at.date())
    today = min(max(current.date(), start), month_end)
    total = working_days_between(start, month_end, absence_dates)
    elapsed = working_days_between(start, today, absence_dates)
    remaining = max(0, total - elapsed)
    return elapsed, total, remaining


def effective_plan_for_user(
    user: Any,
    now: datetime | None = None,
    absence_dates: set[date] | None = None,
) -> EffectivePlan:
    current = _as_utc(now) or datetime.now(timezone.utc)
    full_target = Decimal(str(getattr(user, "mpw", 0) or 0))
    if full_target <= 0:
        return EffectivePlan(
            full_target=Decimal("0"),
            effective_target=Decimal("0"),
            partial_month_factor=Decimal("1"),
            onboarding_factor=Decimal("1"),
            absence_working_days=0,
            onboarding_active=False,
            plan_started_at=_as_utc(getattr(user, "plan_started_at", None)),
            onboarding_started_at=_as_utc(getattr(user, "onboarding_started_at", None)),
            onboarding_until=_as_utc(getattr(user, "onboarding_until", None)),
            adjustment_reasons=[],
        )

    reasons: list[str] = []
    target = full_target
    partial_month_factor = Decimal("1")
    month_days = working_days_in_month(current.year, current.month)
    month_start = date(current.year, current.month, 1)
    month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
    plan_start = month_start
    plan_started_at = _as_utc(getattr(user, "plan_started_at", None))
    if plan_started_at and plan_started_at.year == current.year and plan_started_at.month == current.month:
        plan_start = max(month_start, plan_started_at.date())

    absence_days = 0
    if month_days > 0:
        working_days_without_absences = working_days_between(plan_start, month_end)
        available_days = working_days_between(plan_start, month_end, absence_dates)
        absence_days = max(0, working_days_without_absences - available_days)
        partial_month_factor = Decimal(available_days) / Decimal(month_days)
        target *= partial_month_factor
        if plan_start > month_start:
            reasons.append("partial_month")
        if absence_days > 0:
            reasons.append("absence")

    onboarding_started_at = _as_utc(getattr(user, "onboarding_started_at", None))
    onboarding_until = _as_utc(getattr(user, "onboarding_until", None))
    onboarding_active = bool(getattr(user, "is_new_employee", False)) and (
        onboarding_until is None or current < onboarding_until
    )
    onboarding_factor = Decimal("0.5") if onboarding_active else Decimal("1")
    if onboarding_active:
        target *= onboarding_factor
        reasons.append("new_employee")

    return EffectivePlan(
        full_target=_round_q(full_target),
        effective_target=_round_q(max(Decimal("0"), target)),
        partial_month_factor=partial_month_factor,
        onboarding_factor=onboarding_factor,
        absence_working_days=absence_days,
        onboarding_active=onboarding_active,
        plan_started_at=plan_started_at,
        onboarding_started_at=onboarding_started_at,
        onboarding_until=onboarding_until,
        adjustment_reasons=reasons,
    )
