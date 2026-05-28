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


FINAL_STATUSES = {FeedbackStatus.rejected, FeedbackStatus.done, FeedbackStatus.withdrawn}
DECISION_STATUSES = {FeedbackStatus.accepted, FeedbackStatus.planned, FeedbackStatus.rejected, FeedbackStatus.done}


def _is_manager(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.teamlead)


def _clean_required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"Поле {field_name} не может быть пустым")
    return cleaned


def _feedback_code(feedback_number: int) -> str:
    return f"FB-{feedback_number:06d}"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _has_decision(item: FeedbackRequest) -> bool:
    return bool(item.decision_summary or item.decision_reason or item.next_action or item.target_release)


def _ensure_decision(item: FeedbackRequest) -> None:
    if item.status == FeedbackStatus.rejected and not (item.decision_reason or item.decision_summary):
        raise HTTPException(status_code=400, detail="Для отклонения нужно указать причину решения")
    if item.status in DECISION_STATUSES and not _has_decision(item):
        raise HTTPException(status_code=400, detail="Для выбранного статуса нужно зафиксировать решение или следующее действие")


async def _users_by_id(db: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}


def _to_read(item: FeedbackRequest, users: dict[uuid.UUID, User]) -> FeedbackRequestRead:
    author = users.get(item.author_id)
    reviewer = users.get(item.reviewer_id) if item.reviewer_id else None
    decided_by = users.get(item.decided_by_id) if item.decided_by_id else None
    return FeedbackRequestRead(
        id=item.id,
        feedback_number=item.feedback_number,
        feedback_code=_feedback_code(item.feedback_number),
        author_id=item.author_id,
        author_name=author.full_name if author else "—",
        reviewer_id=item.reviewer_id,
        reviewer_name=reviewer.full_name if reviewer else None,
        decided_by_id=item.decided_by_id,
        decided_by_name=decided_by.full_name if decided_by else None,
        category=item.category,
        status=item.status,
        priority=item.priority,
        title=item.title,
        description=item.description,
        object_type=item.object_type,
        object_ref=item.object_ref,
        expected_result=item.expected_result,
        impact=item.impact,
        evidence_links=item.evidence_links or [],
        resolution=item.resolution,
        decision_summary=item.decision_summary,
        decision_reason=item.decision_reason,
        next_action=item.next_action,
        target_release=item.target_release,
        created_at=item.created_at,
        updated_at=item.updated_at,
        reviewed_at=item.reviewed_at,
        closed_at=item.closed_at,
        decided_at=item.decided_at,
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
        (FeedbackRequest.status == FeedbackStatus.triage, 1),
        (FeedbackRequest.status == FeedbackStatus.in_review, 1),
        (FeedbackRequest.status == FeedbackStatus.needs_info, 2),
        (FeedbackRequest.status == FeedbackStatus.accepted, 3),
        (FeedbackRequest.status == FeedbackStatus.planned, 4),
        else_=5,
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
    user_ids = (
        {item.author_id for item in items}
        | {item.reviewer_id for item in items if item.reviewer_id}
        | {item.decided_by_id for item in items if item.decided_by_id}
    )
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
    user_ids = {item.author_id} | ({item.reviewer_id} if item.reviewer_id else set()) | ({item.decided_by_id} if item.decided_by_id else set())
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
        object_type=body.object_type,
        object_ref=body.object_ref,
        expected_result=body.expected_result,
        impact=body.impact,
        evidence_links=body.evidence_links,
    )
    db.add(item)
    await db.flush()
    code = _feedback_code(item.feedback_number)

    await record_activity_event(
        db,
        user.id,
        "feedback_created",
        metadata={
            "feedback_id": item.id,
            "feedback_number": item.feedback_number,
            "feedback_code": code,
            "category": item.category.value,
            "object_type": item.object_type.value,
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
            f"Новое обращение {code}",
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
    changed_context = False
    changed_decision = False

    if body.priority is not None:
        item.priority = body.priority
    if body.object_type is not None and item.object_type != body.object_type:
        item.object_type = body.object_type
        changed_context = True
    for field_name in ("object_ref", "expected_result", "impact"):
        if field_name in body.model_fields_set:
            value = _clean_optional(getattr(body, field_name))
            if getattr(item, field_name) != value:
                setattr(item, field_name, value)
                changed_context = True
    if body.evidence_links is not None and item.evidence_links != body.evidence_links:
        item.evidence_links = body.evidence_links
        changed_context = True
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
        resolution = _clean_optional(body.resolution)
        if item.resolution != resolution:
            item.resolution = resolution
            changed_resolution = True
            if item.reviewed_at is None and resolution:
                item.reviewed_at = now
    for field_name in ("decision_summary", "decision_reason", "next_action", "target_release"):
        if field_name in body.model_fields_set:
            value = _clean_optional(getattr(body, field_name))
            if getattr(item, field_name) != value:
                setattr(item, field_name, value)
                changed_decision = True
    if changed_decision:
        item.decided_by_id = user.id
        item.decided_at = now
        if item.reviewed_at is None:
            item.reviewed_at = now
        if item.resolution is None and item.decision_summary:
            item.resolution = item.decision_summary
    if item.status in DECISION_STATUSES:
        _ensure_decision(item)

    if changed_reviewer:
        await record_activity_event(
            db,
            user.id,
            "feedback_assigned",
            metadata={"feedback_id": item.id, "feedback_number": item.feedback_number, "reviewer_id": item.reviewer_id},
            occurred_at=now,
        )
    if changed_context:
        await record_activity_event(
            db,
            user.id,
            "feedback_context_changed",
            metadata={"feedback_id": item.id, "feedback_number": item.feedback_number, "object_type": item.object_type.value},
            occurred_at=now,
        )
    if changed_status:
        await record_activity_event(
            db,
            user.id,
            "feedback_status_changed",
            metadata={"feedback_id": item.id, "feedback_number": item.feedback_number, "status": item.status.value},
            occurred_at=now,
        )
    if changed_resolution or changed_decision:
        await record_activity_event(
            db,
            user.id,
            "feedback_decision_recorded" if changed_decision else "feedback_commented",
            metadata={
                "feedback_id": item.id,
                "feedback_number": item.feedback_number,
                "status": item.status.value,
                "target_release": item.target_release,
            },
            occurred_at=now,
        )

    if changed_status or changed_resolution or changed_decision:
        await create_notification(
            db,
            item.author_id,
            "feedback_updated",
            f"Обращение {_feedback_code(item.feedback_number)} обновлено",
            f"{item.title}: {item.status.value}",
            "/feedback",
        )

    await db.flush()
    await db.refresh(item)
    user_ids = {item.author_id} | ({item.reviewer_id} if item.reviewer_id else set()) | ({item.decided_by_id} if item.decided_by_id else set())
    users = await _users_by_id(db, user_ids)
    return _to_read(item, users)
