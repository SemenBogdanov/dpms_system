"""Feedback/change request service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import FeedbackCategory, FeedbackPriority, FeedbackRequest, FeedbackStatus
from app.models.user import User, UserRole
from app.schemas.feedback import FeedbackRequestCreate, FeedbackRequestListResponse, FeedbackRequestRead, FeedbackRequestUpdate
from app.services.activity import record_activity_event
from app.services.notifications import create_notification


FINAL_STATUSES = {FeedbackStatus.rejected, FeedbackStatus.done}


def _is_manager(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.teamlead)


def _clean_required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"Поле {field_name} не может быть пустым")
    return cleaned


async def _users_by_id(db: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}


def _to_read(item: FeedbackRequest, users: dict[uuid.UUID, User]) -> FeedbackRequestRead:
    author = users.get(item.author_id)
    reviewer = users.get(item.reviewer_id) if item.reviewer_id else None
    return FeedbackRequestRead(
        id=item.id,
        author_id=item.author_id,
        author_name=author.full_name if author else "—",
        reviewer_id=item.reviewer_id,
        reviewer_name=reviewer.full_name if reviewer else None,
        category=item.category,
        status=item.status,
        priority=item.priority,
        title=item.title,
        description=item.description,
        resolution=item.resolution,
        created_at=item.created_at,
        updated_at=item.updated_at,
        reviewed_at=item.reviewed_at,
        closed_at=item.closed_at,
    )


async def _manager_users(db: AsyncSession, exclude_user_id: uuid.UUID | None = None) -> list[User]:
    stmt = select(User).where(
        User.role.in_([UserRole.admin, UserRole.teamlead]),
        User.is_active.is_(True),
    )
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _validate_reviewer(db: AsyncSession, reviewer_id: uuid.UUID | None) -> None:
    if reviewer_id is None:
        return
    result = await db.execute(select(User).where(User.id == reviewer_id))
    reviewer = result.scalar_one_or_none()
    if not reviewer or not reviewer.is_active or reviewer.role not in (UserRole.admin, UserRole.teamlead):
        raise HTTPException(status_code=400, detail="Ответственным может быть только активный admin/teamlead")


async def list_feedback_requests(
    db: AsyncSession,
    user: User,
    *,
    status_filter: FeedbackStatus | None = None,
    category: FeedbackCategory | None = None,
    author_id: uuid.UUID | None = None,
    reviewer_id: uuid.UUID | None = None,
    limit: int = 100,
) -> FeedbackRequestListResponse:
    limit = min(max(limit, 1), 500)
    filters = []
    if _is_manager(user):
        if author_id is not None:
            filters.append(FeedbackRequest.author_id == author_id)
        if reviewer_id is not None:
            filters.append(FeedbackRequest.reviewer_id == reviewer_id)
    else:
        filters.append(FeedbackRequest.author_id == user.id)
    if status_filter is not None:
        filters.append(FeedbackRequest.status == status_filter)
    if category is not None:
        filters.append(FeedbackRequest.category == category)

    status_order = case(
        (FeedbackRequest.status == FeedbackStatus.new, 0),
        (FeedbackRequest.status == FeedbackStatus.in_review, 1),
        else_=2,
    )
    priority_order = case(
        (FeedbackRequest.priority == FeedbackPriority.high, 0),
        (FeedbackRequest.priority == FeedbackPriority.medium, 1),
        else_=2,
    )
    stmt = select(FeedbackRequest).order_by(status_order.asc(), priority_order.asc(), FeedbackRequest.updated_at.desc())
    count_stmt = select(func.count(FeedbackRequest.id))
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    result = await db.execute(stmt.limit(limit))
    items = list(result.scalars().all())
    total = int((await db.execute(count_stmt)).scalar() or 0)
    user_ids = {item.author_id for item in items} | {item.reviewer_id for item in items if item.reviewer_id}
    users = await _users_by_id(db, user_ids)
    return FeedbackRequestListResponse(
        items=[_to_read(item, users) for item in items],
        total=total,
        limit=limit,
    )


async def get_feedback_request(db: AsyncSession, user: User, feedback_id: uuid.UUID) -> FeedbackRequestRead:
    item = await _get_feedback_or_404(db, feedback_id)
    if not _is_manager(user) and item.author_id != user.id:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    user_ids = {item.author_id} | ({item.reviewer_id} if item.reviewer_id else set())
    users = await _users_by_id(db, user_ids)
    return _to_read(item, users)


async def _get_feedback_or_404(db: AsyncSession, feedback_id: uuid.UUID) -> FeedbackRequest:
    result = await db.execute(select(FeedbackRequest).where(FeedbackRequest.id == feedback_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    return item


async def create_feedback_request(db: AsyncSession, user: User, body: FeedbackRequestCreate) -> FeedbackRequestRead:
    now = datetime.now(timezone.utc)
    item = FeedbackRequest(
        author_id=user.id,
        category=body.category,
        priority=body.priority,
        status=FeedbackStatus.new,
        title=_clean_required(body.title, "title"),
        description=_clean_required(body.description, "description"),
    )
    db.add(item)
    await db.flush()

    await record_activity_event(
        db,
        user.id,
        "feedback_created",
        metadata={
            "feedback_id": item.id,
            "category": item.category.value,
            "priority": item.priority.value,
            "status": item.status.value,
        },
        occurred_at=now,
    )

    for manager in await _manager_users(db, exclude_user_id=user.id):
        await create_notification(
            db,
            manager.id,
            "feedback_created",
            "Новое обращение",
            f"{user.full_name}: {item.title}",
            "/feedback",
        )

    await db.refresh(item)
    users = await _users_by_id(db, {item.author_id})
    return _to_read(item, users)


async def update_feedback_request(
    db: AsyncSession,
    user: User,
    feedback_id: uuid.UUID,
    body: FeedbackRequestUpdate,
) -> FeedbackRequestRead:
    if not _is_manager(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    item = await _get_feedback_or_404(db, feedback_id)
    now = datetime.now(timezone.utc)
    changed_status = False
    changed_reviewer = False
    changed_resolution = False

    if body.priority is not None:
        item.priority = body.priority
    if "reviewer_id" in body.model_fields_set:
        await _validate_reviewer(db, body.reviewer_id)
        if item.reviewer_id != body.reviewer_id:
            item.reviewer_id = body.reviewer_id
            changed_reviewer = True
    if body.status is not None and item.status != body.status:
        item.status = body.status
        changed_status = True
        if item.reviewed_at is None and body.status != FeedbackStatus.new:
            item.reviewed_at = now
        item.closed_at = now if body.status in FINAL_STATUSES else None
    if body.resolution is not None:
        resolution = body.resolution.strip() or None
        if item.resolution != resolution:
            item.resolution = resolution
            changed_resolution = True
            if item.reviewed_at is None and resolution:
                item.reviewed_at = now

    if changed_reviewer:
        await record_activity_event(
            db,
            user.id,
            "feedback_assigned",
            metadata={"feedback_id": item.id, "reviewer_id": item.reviewer_id},
            occurred_at=now,
        )
    if changed_status:
        await record_activity_event(
            db,
            user.id,
            "feedback_status_changed",
            metadata={"feedback_id": item.id, "status": item.status.value},
            occurred_at=now,
        )
    if changed_resolution:
        await record_activity_event(
            db,
            user.id,
            "feedback_commented",
            metadata={"feedback_id": item.id, "status": item.status.value},
            occurred_at=now,
        )

    if changed_status or changed_resolution:
        await create_notification(
            db,
            item.author_id,
            "feedback_updated",
            "Обращение обновлено",
            f"{item.title}: {item.status.value}",
            "/feedback",
        )

    await db.flush()
    await db.refresh(item)
    user_ids = {item.author_id} | ({item.reviewer_id} if item.reviewer_id else set())
    users = await _users_by_id(db, user_ids)
    return _to_read(item, users)
