"""Owner-only organization, series, occurrences and reminder history."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.deadline_tracker import (
    DeadlineTracker, DeadlineTrackerCategory, DeadlineTrackerDelivery, DeadlineTrackerEvent,
    DeadlineTrackerGroup, DeadlineTrackerOccurrence, DeadlineTrackerReminder,
)
from app.models.notification import Notification
from app.models.personal_task import PersonalTask
from app.models.task import Task
from app.models.user import User
from app.schemas.deadline_tracker import (
    DeadlineTrackerCreate, DeadlineTrackerRead, DeadlineTrackerStatus, DeadlineTrackerType,
    DeadlineTrackerUpdate, TrackerAlertRead, TrackerCategoryRead, TrackerCategoryUpdate,
    TrackerEventRead, TrackerGroupRead, TrackerGroupUpdate, TrackerOccurrenceRead,
    TrackerOrganizationCreate, TrackerRecurrence, TrackerReminderInput, TrackerReorder,
)
from app.services.deadline_tracker_calendar import utc
from app.services.deadline_tracker_notifications import mark_tracker_alerts_read
from app.services.deadline_tracker_organization import owned_organization, seed_categories
from app.services.deadline_tracker_schedule import (
    record_event, reset_series_schedule, set_reminders, suppress_due_deliveries, sync_tracker_schedule,
    tracker_source_deleted, reopen_one_time_tracker,
)
from app.services.deadline_tracker_sources import get_source, reconcile_linked_tracker, task_access_clause

router = APIRouter()


async def _commit(db):
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Связь или запись уже существует") from None


async def _get_owned_tracker_or_404(db, tracker_id, owner_id):
    row = (await db.execute(select(DeadlineTracker).where(
        DeadlineTracker.id == tracker_id, DeadlineTracker.owner_id == owner_id,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Трекер срока не найден")
    return row


def _close_pause_period(tracker, now=None):
    now = now or datetime.now(timezone.utc)
    if tracker.pause_started_at:
        tracker.paused_seconds = max(0, tracker.paused_seconds or 0) + max(0, int((now - utc(tracker.pause_started_at)).total_seconds()))
        tracker.pause_started_at = None


def _apply_status_side_effects(tracker, new_status):
    now = datetime.now(timezone.utc)
    if new_status == "paused":
        tracker.pause_started_at = tracker.pause_started_at or now
        tracker.completed_at = None
    elif new_status in {"active", "done", "archived"}:
        _close_pause_period(tracker, now)
        tracker.completed_at = (tracker.completed_at or now) if new_status == "done" else None


def _safe_starts_at(candidate, due_at):
    return min(utc(candidate or datetime.now(timezone.utc)), utc(due_at) - timedelta(minutes=1))


async def _validate_organization(db, data, user, tracker=None):
    for field, model in (("group_id", DeadlineTrackerGroup), ("category_id", DeadlineTrackerCategory)):
        if field in data and data[field] is not None:
            unchanged = tracker is not None and getattr(tracker, field) == data[field]
            await owned_organization(db, model, data[field], user.id, active=not unchanged)


async def _read_payload(db, trackers, user):
    if not trackers:
        return []
    tracker_ids = [t.id for t in trackers]
    personal_ids = [t.personal_task_id for t in trackers if t.personal_task_id]
    q_ids = [t.linked_task_id for t in trackers if t.linked_task_id]
    personal = {t.id: t for t in (await db.execute(select(PersonalTask).where(
        PersonalTask.id.in_(personal_ids), PersonalTask.owner_id == user.id,
    ))).scalars()} if personal_ids else {}
    tasks = {t.id: t for t in (await db.execute(select(Task).where(
        Task.id.in_(q_ids), task_access_clause(user),
    ))).scalars()} if q_ids else {}
    assignees = [t.assignee_id for t in tasks.values() if t.assignee_id]
    names = dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(assignees)))).all()) if assignees else {}
    reminders = list((await db.execute(select(DeadlineTrackerReminder).where(
        DeadlineTrackerReminder.tracker_id.in_(tracker_ids), DeadlineTrackerReminder.is_active.is_(True),
    ).order_by(DeadlineTrackerReminder.offset_seconds.desc()))).scalars())
    ranked = select(DeadlineTrackerOccurrence.id, func.row_number().over(
        partition_by=DeadlineTrackerOccurrence.tracker_id,
        order_by=(DeadlineTrackerOccurrence.due_at, DeadlineTrackerOccurrence.id),
    ).label("rank")).where(
        DeadlineTrackerOccurrence.tracker_id.in_(tracker_ids), DeadlineTrackerOccurrence.status == "pending",
    ).subquery()
    current = {o.tracker_id: o for o in (await db.execute(select(DeadlineTrackerOccurrence).join(
        ranked, ranked.c.id == DeadlineTrackerOccurrence.id,
    ).where(ranked.c.rank == 1))).scalars()}
    items = []
    now = datetime.now(timezone.utc)
    for tracker in trackers:
        item = DeadlineTrackerRead.model_validate(tracker)
        item.reminders = [TrackerReminderInput(value=r.value, unit=r.unit) for r in reminders if r.tracker_id == tracker.id]
        item.source = "personal_task" if tracker.personal_task_id else "task" if tracker.linked_task_id else "standalone"
        source = personal.get(tracker.personal_task_id) if tracker.personal_task_id else tasks.get(tracker.linked_task_id)
        item.source_available = not tracker_source_deleted(tracker) and (item.source == "standalone" or source is not None)
        if source:
            item.source_title = source.title
            item.source_responsible = source.responsible if tracker.personal_task_id else names.get(source.assignee_id)
            item.responsible = item.source_responsible
            if tracker.personal_task_id:
                item.personal_task_key = f"PT-{source.task_number}"
                item.personal_task_title = source.title
            source_due = source.due_at if tracker.personal_task_id else source.due_date
            if source_due:
                item.due_at = utc(source_due)
                item.starts_at = _safe_starts_at((source.start_at if tracker.personal_task_id else source.started_at) or source.created_at, source_due)
        elif not item.source_available:
            item.title = "Источник недоступен"
            item.description = item.next_action = item.responsible = item.url = None
            item.tags = []
        total = max(0, tracker.paused_seconds or 0)
        if tracker.status == "paused" and tracker.pause_started_at:
            total += max(1, int((now - utc(tracker.pause_started_at)).total_seconds()))
        item.total_pause_seconds = total
        item.shifted_due_at = item.due_at if tracker.recurrence or item.source != "standalone" else utc(item.due_at) + timedelta(days=(total + 86399) // 86400)
        if tracker.id in current:
            item.current_occurrence = TrackerOccurrenceRead.model_validate(current[tracker.id])
        item.series_exhausted = (
            tracker.recurrence is not None and tracker.next_occurrence_at is None and tracker.id not in current
        )
        items.append(item)
    return items


@router.get("/groups", response_model=list[TrackerGroupRead])
async def list_tracker_groups(include_archived: bool = False, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(DeadlineTrackerGroup).where(DeadlineTrackerGroup.owner_id == user.id)
    if not include_archived:
        stmt = stmt.where(DeadlineTrackerGroup.is_archived.is_(False))
    return list((await db.execute(stmt.order_by(DeadlineTrackerGroup.sort_order, DeadlineTrackerGroup.id))).scalars())


@router.post("/groups", response_model=TrackerGroupRead)
async def create_tracker_group(payload: TrackerOrganizationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = DeadlineTrackerGroup(owner_id=user.id, **payload.model_dump())
    db.add(row)
    await _commit(db)
    await db.refresh(row)
    return row


@router.post("/groups/reorder", response_model=list[TrackerGroupRead])
async def reorder_tracker_groups(payload: TrackerReorder, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = []
    for identity in sorted(payload.ids, key=str):
        rows.append(await owned_organization(db, DeadlineTrackerGroup, identity, user.id))
    positions = {identity: position for position, identity in enumerate(payload.ids)}
    for row in rows:
        row.sort_order = positions[row.id]
    await _commit(db)
    return sorted(rows, key=lambda row: row.sort_order)


@router.patch("/groups/{group_id}", response_model=TrackerGroupRead)
async def update_tracker_group(group_id: UUID, payload: TrackerGroupUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_organization(db, DeadlineTrackerGroup, group_id, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await _commit(db)
    return row


@router.delete("/groups/{group_id}")
async def delete_tracker_group(group_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_organization(db, DeadlineTrackerGroup, group_id, user.id)
    await db.delete(row)
    await _commit(db)
    return {"status": "deleted"}


@router.get("/categories", response_model=list[TrackerCategoryRead])
async def list_tracker_categories(include_archived: bool = False, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await seed_categories(db, user.id)
    await _commit(db)
    return sorted([r for r in rows if include_archived or not r.is_archived], key=lambda r: (r.sort_order, str(r.id)))


@router.post("/categories", response_model=TrackerCategoryRead)
async def create_tracker_category(payload: TrackerOrganizationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = DeadlineTrackerCategory(owner_id=user.id, **payload.model_dump())
    db.add(row)
    await _commit(db)
    await db.refresh(row)
    return row


@router.patch("/categories/{category_id}", response_model=TrackerCategoryRead)
async def update_tracker_category(category_id: UUID, payload: TrackerCategoryUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_organization(db, DeadlineTrackerCategory, category_id, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await _commit(db)
    return row


@router.delete("/categories/{category_id}")
async def delete_tracker_category(category_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_organization(db, DeadlineTrackerCategory, category_id, user.id)
    if row.legacy_type:
        row.is_archived = True
    else:
        await db.delete(row)
    await _commit(db)
    return {"status": "archived" if row.legacy_type else "deleted"}


@router.get("", response_model=list[DeadlineTrackerRead])
async def list_deadline_trackers(
    status_filter: DeadlineTrackerStatus | None = Query(None, alias="status"),
    tracker_type: DeadlineTrackerType | None = None, search: str | None = Query(None, min_length=1, max_length=100),
    include_archived: bool = False, group_id: UUID | None = None, category_id: UUID | None = None,
    ungrouped: bool = False, limit: int = Query(100, ge=1, le=300), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    stmt = select(DeadlineTracker).where(DeadlineTracker.owner_id == user.id)
    if status_filter:
        stmt = stmt.where(DeadlineTracker.status == status_filter)
    elif not include_archived:
        stmt = stmt.where(DeadlineTracker.status != "archived")
    if tracker_type:
        stmt = stmt.where(DeadlineTracker.tracker_type == tracker_type)
    if group_id:
        await owned_organization(db, DeadlineTrackerGroup, group_id, user.id)
        stmt = stmt.where(DeadlineTracker.group_id == group_id)
    if category_id:
        await owned_organization(db, DeadlineTrackerCategory, category_id, user.id)
        stmt = stmt.where(DeadlineTracker.category_id == category_id)
    if ungrouped:
        stmt = stmt.where(DeadlineTracker.group_id.is_(None))
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(DeadlineTracker.title.ilike(pattern), DeadlineTracker.description.ilike(pattern), DeadlineTracker.next_action.ilike(pattern)))
    trackers = list((await db.execute(stmt.order_by(DeadlineTracker.due_at, DeadlineTracker.id).offset(offset).limit(limit))).scalars())
    return await _read_payload(db, trackers, user)


async def _insert_tracker(db, payload, user):
    data = payload.model_dump(exclude={"reminders", "recurrence", "status", "responsible"})
    await _validate_organization(db, data, user)
    if "category_id" not in payload.model_fields_set:
        categories = await seed_categories(db, user.id)
        data["category_id"] = next(c.id for c in categories if c.legacy_type == payload.tracker_type)
    tracker = DeadlineTracker(owner_id=user.id, status="active", **data)
    tracker.recurrence = payload.recurrence.model_dump(mode="json") if payload.recurrence else None
    if tracker.personal_task_id or tracker.linked_task_id:
        if await get_source(db, tracker, user) is None:
            raise HTTPException(404, "Источник недоступен")
        tracker.source_check_at = datetime.now(timezone.utc)
    db.add(tracker)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Трекер этой задачи уже существует") from None
    await set_reminders(db, tracker, payload.reminders)
    if tracker.personal_task_id or tracker.linked_task_id:
        if not await reconcile_linked_tracker(db, tracker, user=user):
            raise HTTPException(409, "У источника нет срока")
    await sync_tracker_schedule(db, tracker)
    record_event(db, tracker, "created")
    await _commit(db)
    await db.refresh(tracker)
    return (await _read_payload(db, [tracker], user))[0]


@router.post("", response_model=DeadlineTrackerRead)
async def create_deadline_tracker(payload: DeadlineTrackerCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _insert_tracker(db, payload, user)


async def _from_task(db, task_id, user, *, personal):
    probe = DeadlineTracker(owner_id=user.id, personal_task_id=task_id if personal else None, linked_task_id=None if personal else task_id)
    source = await get_source(db, probe, user)
    if source is None:
        raise HTTPException(404, "Источник недоступен")
    due = source.due_at if personal else source.due_date
    if due is None:
        raise HTTPException(400, "У задачи не задан дедлайн")
    field = DeadlineTracker.personal_task_id if personal else DeadlineTracker.linked_task_id
    tracker = (await db.execute(select(DeadlineTracker).where(DeadlineTracker.owner_id == user.id, field == task_id).with_for_update())).scalar_one_or_none()
    if tracker:
        await reconcile_linked_tracker(db, tracker, user=user)
        await _commit(db)
        return (await _read_payload(db, [tracker], user))[0]
    return await _insert_tracker(db, DeadlineTrackerCreate(
        title=source.title[:200], starts_at=_safe_starts_at(source.created_at, due), due_at=utc(due),
        tracker_type="task", personal_task_id=task_id if personal else None, linked_task_id=None if personal else task_id,
    ), user)


@router.post("/from-task/{task_id}", response_model=DeadlineTrackerRead)
async def create_tracker_from_task(task_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _from_task(db, task_id, user, personal=False)


@router.post("/from-personal-task/{task_id}", response_model=DeadlineTrackerRead)
async def create_tracker_from_personal_task(task_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _from_task(db, task_id, user, personal=True)


async def _delete_by_link(db, user, field, task_id):
    tracker = (await db.execute(select(DeadlineTracker).where(DeadlineTracker.owner_id == user.id, field == task_id).with_for_update())).scalar_one_or_none()
    if tracker is None:
        raise HTTPException(404, "Связанный трекер не найден")
    await db.delete(tracker)
    await _commit(db)
    return {"status": "deleted"}


@router.delete("/by-task/{task_id}")
async def delete_tracker_by_task(task_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _delete_by_link(db, user, DeadlineTracker.linked_task_id, task_id)


@router.delete("/by-personal-task/{task_id}")
async def delete_tracker_by_personal_task(task_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _delete_by_link(db, user, DeadlineTracker.personal_task_id, task_id)


@router.get("/{tracker_id}", response_model=DeadlineTrackerRead)
async def get_deadline_tracker(tracker_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    await reconcile_linked_tracker(db, tracker, user=user)
    await sync_tracker_schedule(db, tracker)
    await mark_tracker_alerts_read(db, tracker)
    await _commit(db)
    return (await _read_payload(db, [tracker], user))[0]


@router.patch("/{tracker_id}", response_model=DeadlineTrackerRead)
async def update_deadline_tracker(tracker_id: UUID, payload: DeadlineTrackerUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    if tracker_source_deleted(tracker):
        await sync_tracker_schedule(db, tracker)
        await _commit(db)
        raise HTTPException(409, "Источник удален; трекер доступен только для чтения")
    data = payload.model_dump(exclude_unset=True, exclude={"reminders", "recurrence"})
    for field in ("personal_task_id", "linked_task_id"):
        if field in data and data[field] != getattr(tracker, field):
            raise HTTPException(409, "Источник трекера доступен только для чтения")
    if tracker.personal_task_id or tracker.linked_task_id:
        for field in ("title", "description", "starts_at", "due_at", "responsible"):
            if field in data and data[field] != getattr(tracker, field):
                raise HTTPException(409, "Измените данные в исходной задаче")
        if payload.recurrence is not None:
            raise HTTPException(409, "Связанный трекер может быть только разовым")
    elif "responsible" in data:
        data.pop("responsible")
    recurrence = payload.recurrence.model_dump(mode="json") if payload.recurrence else None
    if "recurrence" not in payload.model_fields_set:
        recurrence = tracker.recurrence
    starts, due = data.get("starts_at", tracker.starts_at), data.get("due_at", tracker.due_at)
    if utc(due) <= utc(starts):
        raise HTTPException(422, "Дедлайн должен быть позже даты старта")
    if recurrence:
        rule = TrackerRecurrence.model_validate(recurrence)
        if rule.until and utc(rule.until) < utc(due):
            raise HTTPException(422, "Окончание серии раньше первого срока")
    if tracker.recurrence and data.get("status") == "done":
        raise HTTPException(409, "Используйте действие Завершить серию")
    await _validate_organization(db, data, user, tracker)
    reset = recurrence != tracker.recurrence or (bool(recurrence) and utc(due) != utc(tracker.due_at))
    if tracker.status == "paused" and data.get("status", "paused") != "paused":
        await suppress_due_deliveries(db, tracker)
    old_status = tracker.status
    for field, value in data.items():
        setattr(tracker, field, value)
    tracker.recurrence = recurrence
    _apply_status_side_effects(tracker, data.get("status"))
    tracker.updated_at = datetime.now(timezone.utc)
    if "reminders" in payload.model_fields_set:
        await set_reminders(db, tracker, payload.reminders)
    if old_status in {"done", "archived"} and data.get("status") == "active" and recurrence is None:
        await reopen_one_time_tracker(db, tracker)
    elif reset:
        await reset_series_schedule(db, tracker)
    else:
        await sync_tracker_schedule(db, tracker)
    if tracker.status == "done" and not tracker.recurrence:
        await db.execute(update(DeadlineTrackerOccurrence).where(
            DeadlineTrackerOccurrence.tracker_id == tracker.id, DeadlineTrackerOccurrence.status == "pending",
        ).values(status="completed", completed_at=tracker.completed_at))
    record_event(db, tracker, "updated", fields=sorted(payload.model_fields_set), old_status=old_status, status=tracker.status)
    await _commit(db)
    return (await _read_payload(db, [tracker], user))[0]


@router.delete("/{tracker_id}")
async def delete_deadline_tracker(tracker_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    await db.delete(tracker)
    await _commit(db)
    return {"status": "deleted"}


@router.get("/{tracker_id}/occurrences", response_model=list[TrackerOccurrenceRead])
async def list_tracker_occurrences(tracker_id: UUID, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_tracker_or_404(db, tracker_id, user.id)
    return list((await db.execute(select(DeadlineTrackerOccurrence).where(DeadlineTrackerOccurrence.tracker_id == tracker_id)
        .order_by(DeadlineTrackerOccurrence.due_at.desc(), DeadlineTrackerOccurrence.id).offset(offset).limit(limit))).scalars())


@router.post("/{tracker_id}/occurrences/{occurrence_id}/complete", response_model=DeadlineTrackerRead)
async def complete_tracker_occurrence(tracker_id: UUID, occurrence_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    occurrence = (await db.execute(select(DeadlineTrackerOccurrence).where(
        DeadlineTrackerOccurrence.id == occurrence_id, DeadlineTrackerOccurrence.tracker_id == tracker_id,
    ).with_for_update())).scalar_one_or_none()
    if occurrence is None:
        raise HTTPException(404, "Повторение не найдено")
    if occurrence.status == "cancelled" or tracker.status in {"done", "archived"} and occurrence.status != "completed":
        raise HTTPException(409, "Серия или повторение уже завершены")
    if occurrence.status != "completed":
        occurrence.status = "completed"
        occurrence.completed_at = datetime.now(timezone.utc)
        await db.execute(update(DeadlineTrackerDelivery).where(
            DeadlineTrackerDelivery.occurrence_id == occurrence.id, DeadlineTrackerDelivery.status == "pending",
        ).values(status="cancelled"))
        if not tracker.recurrence:
            tracker.status = "done"
            _apply_status_side_effects(tracker, "done")
        record_event(db, tracker, "occurrence_completed", occurrence_id=str(occurrence.id))
        await sync_tracker_schedule(db, tracker)
    await _commit(db)
    return (await _read_payload(db, [tracker], user))[0]


@router.post("/{tracker_id}/finish-series", response_model=DeadlineTrackerRead)
async def finish_tracker_series(tracker_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    if tracker.recurrence is None:
        raise HTTPException(409, "Трекер не является серией")
    if tracker.status != "done":
        tracker.status = "done"
        _apply_status_side_effects(tracker, "done")
        await db.execute(update(DeadlineTrackerOccurrence).where(
            DeadlineTrackerOccurrence.tracker_id == tracker.id, DeadlineTrackerOccurrence.status == "pending",
        ).values(status="cancelled"))
        await sync_tracker_schedule(db, tracker)
        record_event(db, tracker, "series_finished")
    await _commit(db)
    return (await _read_payload(db, [tracker], user))[0]


@router.get("/{tracker_id}/history", response_model=list[TrackerEventRead])
async def list_tracker_history(tracker_id: UUID, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_tracker_or_404(db, tracker_id, user.id)
    return list((await db.execute(select(DeadlineTrackerEvent).where(DeadlineTrackerEvent.tracker_id == tracker_id)
        .order_by(DeadlineTrackerEvent.created_at.desc(), DeadlineTrackerEvent.id).offset(offset).limit(limit))).scalars())


@router.get("/{tracker_id}/alerts", response_model=list[TrackerAlertRead])
async def list_tracker_alerts(tracker_id: UUID, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_tracker_or_404(db, tracker_id, user.id)
    rows = (await db.execute(select(DeadlineTrackerDelivery, Notification.is_read).outerjoin(Notification,
        (Notification.id == DeadlineTrackerDelivery.notification_id) & (Notification.user_id == user.id),
    ).where(DeadlineTrackerDelivery.tracker_id == tracker_id)
        .order_by(DeadlineTrackerDelivery.scheduled_for.desc(), DeadlineTrackerDelivery.id).offset(offset).limit(limit))).all()
    return [TrackerAlertRead.model_validate(row).model_copy(update={"is_read": is_read}) for row, is_read in rows]


@router.post("/{tracker_id}/alerts/read")
async def read_tracker_alerts(tracker_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    marked = await mark_tracker_alerts_read(db, tracker)
    await _commit(db)
    return {"marked": marked}
