"""Business rules for employee absences and plan capacity."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.absence import AbsenceType, GlobalHoliday, UserAbsence
from app.models.shop import PeriodSnapshot
from app.models.user import User
from app.schemas.absence import AbsenceCreate, AbsenceRead, AbsenceUpdate, HolidayCreate, HolidayRead, HolidayUpdate
from app.services.planning import working_days_between

MAX_ABSENCE_SPAN_DAYS = 366


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = date.fromordinal(current.toordinal() + 1)


def month_bounds_for(current: datetime) -> tuple[date, date]:
    import calendar

    month_start = date(current.year, current.month, 1)
    month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
    return month_start, month_end


def absence_working_days(start: date, end: date, excluded_dates: set[date] | None = None) -> int:
    return working_days_between(start, end, excluded_dates)


def _affected_periods(start: date, end: date) -> list[str]:
    periods: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        periods.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


async def _ensure_period_open(db: AsyncSession, start: date, end: date) -> None:
    periods = _affected_periods(start, end)
    result = await db.execute(select(PeriodSnapshot.period).where(PeriodSnapshot.period.in_(periods)).limit(1))
    closed = result.scalar_one_or_none()
    if closed:
        raise HTTPException(status_code=400, detail=f"Период {closed} уже закрыт, отсутствие нельзя менять")


def _validate_span(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")
    if (end - start).days > MAX_ABSENCE_SPAN_DAYS:
        raise HTTPException(status_code=400, detail="Период отсутствия не может быть длиннее 366 дней")


async def _ensure_user_exists(db: AsyncSession, user_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    return user


async def _ensure_no_overlap(
    db: AsyncSession,
    user_id: UUID,
    start: date,
    end: date,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(UserAbsence.id).where(
        UserAbsence.user_id == user_id,
        UserAbsence.start_date <= end,
        UserAbsence.end_date >= start,
    )
    if exclude_id is not None:
        stmt = stmt.where(UserAbsence.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="У сотрудника уже есть отсутствие, пересекающее эти даты")


async def _holiday_dates_between(db: AsyncSession, start: date, end: date) -> set[date]:
    result = await db.execute(
        select(GlobalHoliday.holiday_date).where(
            GlobalHoliday.affects_plan.is_(True),
            GlobalHoliday.holiday_date >= start,
            GlobalHoliday.holiday_date <= end,
        )
    )
    return {row.holiday_date for row in result.all() if row.holiday_date.weekday() < 5}


async def _ensure_holiday_unique(
    db: AsyncSession,
    holiday_date: date,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(GlobalHoliday.id).where(GlobalHoliday.holiday_date == holiday_date)
    if exclude_id is not None:
        stmt = stmt.where(GlobalHoliday.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Праздничный день с такой датой уже существует")


def _holiday_to_read(holiday: GlobalHoliday) -> HolidayRead:
    return HolidayRead(
        id=holiday.id,
        date=holiday.holiday_date,
        name=holiday.name,
        affects_plan=holiday.affects_plan,
        created_by_id=holiday.created_by_id,
        created_at=holiday.created_at,
        updated_at=holiday.updated_at,
    )


def build_absence_read(
    absence: UserAbsence,
    user: User,
    window_start: date | None = None,
    window_end: date | None = None,
    holiday_dates: set[date] | None = None,
) -> AbsenceRead:
    working_start = max(absence.start_date, window_start) if window_start else absence.start_date
    working_end = min(absence.end_date, window_end) if window_end else absence.end_date
    return AbsenceRead(
        id=absence.id,
        user_id=absence.user_id,
        user_name=user.full_name,
        user_email=user.email,
        start_date=absence.start_date,
        end_date=absence.end_date,
        type=AbsenceType(absence.type),
        affects_plan=absence.affects_plan,
        comment=absence.comment,
        source=absence.source,
        working_days=absence_working_days(working_start, working_end, holiday_dates) if absence.affects_plan else 0,
        created_by_id=absence.created_by_id,
        created_at=absence.created_at,
        updated_at=absence.updated_at,
    )


async def list_absences(
    db: AsyncSession,
    start: date,
    end: date,
    user_id: UUID | None = None,
) -> list[AbsenceRead]:
    _validate_span(start, end)
    stmt = (
        select(UserAbsence, User)
        .join(User, User.id == UserAbsence.user_id)
        .where(UserAbsence.start_date <= end, UserAbsence.end_date >= start)
        .order_by(UserAbsence.start_date, User.full_name)
    )
    if user_id is not None:
        stmt = stmt.where(UserAbsence.user_id == user_id)
    result = await db.execute(stmt)
    holiday_dates = await _holiday_dates_between(db, start, end)
    return [build_absence_read(absence, user, start, end, holiday_dates) for absence, user in result.all()]


async def create_absence(db: AsyncSession, body: AbsenceCreate, admin: User) -> AbsenceRead:
    _validate_span(body.start_date, body.end_date)
    user = await _ensure_user_exists(db, body.user_id)
    await _ensure_period_open(db, body.start_date, body.end_date)
    await _ensure_no_overlap(db, body.user_id, body.start_date, body.end_date)
    absence = UserAbsence(
        user_id=body.user_id,
        start_date=body.start_date,
        end_date=body.end_date,
        type=body.type.value,
        affects_plan=body.affects_plan,
        comment=body.comment,
        source="manual",
        created_by_id=admin.id,
    )
    db.add(absence)
    await db.flush()
    await db.refresh(absence)
    holiday_dates = await _holiday_dates_between(db, body.start_date, body.end_date)
    return build_absence_read(absence, user, holiday_dates=holiday_dates)


async def update_absence(db: AsyncSession, absence_id: UUID, body: AbsenceUpdate) -> AbsenceRead:
    result = await db.execute(select(UserAbsence).where(UserAbsence.id == absence_id))
    absence = result.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Отсутствие не найдено")

    user_id = body.user_id or absence.user_id
    start = body.start_date or absence.start_date
    end = body.end_date or absence.end_date
    _validate_span(start, end)
    user = await _ensure_user_exists(db, user_id)
    await _ensure_period_open(db, start, end)
    await _ensure_no_overlap(db, user_id, start, end, exclude_id=absence.id)

    absence.user_id = user_id
    absence.start_date = start
    absence.end_date = end
    if body.type is not None:
        absence.type = body.type.value
    if body.affects_plan is not None:
        absence.affects_plan = body.affects_plan
    if "comment" in body.model_fields_set:
        absence.comment = body.comment
    await db.flush()
    await db.refresh(absence)
    holiday_dates = await _holiday_dates_between(db, start, end)
    return build_absence_read(absence, user, holiday_dates=holiday_dates)


async def delete_absence(db: AsyncSession, absence_id: UUID) -> None:
    result = await db.execute(select(UserAbsence).where(UserAbsence.id == absence_id))
    absence = result.scalar_one_or_none()
    if not absence:
        raise HTTPException(status_code=404, detail="Отсутствие не найдено")
    await _ensure_period_open(db, absence.start_date, absence.end_date)
    await db.delete(absence)
    await db.flush()


async def absence_dates_by_user(
    db: AsyncSession,
    user_ids: list[UUID],
    start: date,
    end: date,
) -> dict[UUID, set[date]]:
    if not user_ids:
        return {}
    holiday_dates = await _holiday_dates_between(db, start, end)
    result = await db.execute(
        select(UserAbsence).where(
            UserAbsence.user_id.in_(user_ids),
            UserAbsence.affects_plan.is_(True),
            UserAbsence.start_date <= end,
            UserAbsence.end_date >= start,
        )
    )
    dates_by_user: dict[UUID, set[date]] = defaultdict(lambda: set(holiday_dates))
    for user_id in user_ids:
        dates_by_user[user_id].update(holiday_dates)
    for absence in result.scalars().all():
        clipped_start = max(start, absence.start_date)
        clipped_end = min(end, absence.end_date)
        for current in iter_dates(clipped_start, clipped_end):
            if current.weekday() < 5:
                dates_by_user[absence.user_id].add(current)
    return dict(dates_by_user)


async def absence_dates_for_user(db: AsyncSession, user_id: UUID, start: date, end: date) -> set[date]:
    return (await absence_dates_by_user(db, [user_id], start, end)).get(user_id, set())


def is_absent_on(absence_dates: set[date], current: datetime | None = None) -> bool:
    now = current or datetime.now(timezone.utc)
    return now.date() in absence_dates


async def global_holiday_dates(db: AsyncSession, start: date, end: date) -> set[date]:
    _validate_span(start, end)
    return await _holiday_dates_between(db, start, end)


async def list_holidays(db: AsyncSession, start: date, end: date) -> list[HolidayRead]:
    _validate_span(start, end)
    result = await db.execute(
        select(GlobalHoliday)
        .where(GlobalHoliday.holiday_date >= start, GlobalHoliday.holiday_date <= end)
        .order_by(GlobalHoliday.holiday_date.asc(), GlobalHoliday.name.asc())
    )
    return [_holiday_to_read(holiday) for holiday in result.scalars().all()]


async def create_holiday(db: AsyncSession, body: HolidayCreate, admin: User) -> HolidayRead:
    await _ensure_period_open(db, body.date, body.date)
    await _ensure_holiday_unique(db, body.date)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название праздника обязательно")
    holiday = GlobalHoliday(
        holiday_date=body.date,
        name=name,
        affects_plan=True,
        created_by_id=admin.id,
    )
    db.add(holiday)
    await db.flush()
    await db.refresh(holiday)
    return _holiday_to_read(holiday)


async def update_holiday(db: AsyncSession, holiday_id: UUID, body: HolidayUpdate) -> HolidayRead:
    result = await db.execute(select(GlobalHoliday).where(GlobalHoliday.id == holiday_id))
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise HTTPException(status_code=404, detail="Праздничный день не найден")

    next_date = body.date or holiday.holiday_date
    await _ensure_period_open(db, holiday.holiday_date, holiday.holiday_date)
    await _ensure_period_open(db, next_date, next_date)
    if next_date != holiday.holiday_date:
        await _ensure_holiday_unique(db, next_date, exclude_id=holiday.id)
        holiday.holiday_date = next_date
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Название праздника обязательно")
        holiday.name = name
    await db.flush()
    await db.refresh(holiday)
    return _holiday_to_read(holiday)


async def delete_holiday(db: AsyncSession, holiday_id: UUID) -> None:
    result = await db.execute(select(GlobalHoliday).where(GlobalHoliday.id == holiday_id))
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise HTTPException(status_code=404, detail="Праздничный день не найден")
    await _ensure_period_open(db, holiday.holiday_date, holiday.holiday_date)
    await db.delete(holiday)
    await db.flush()
