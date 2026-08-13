"""Attention projection used by the focused Messages section."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.messages import (
    CommunicationEvent,
    MessageThreadParticipant,
    UserAttentionItem,
)
from app.models.notification import Notification
from app.models.user import User


IMPORTANT_NOTIFICATION_TYPES = frozenset(
    {
        "task_assigned",
        "task_cancelled",
        "task_rejected",
        "task_validated",
        "task_acceptance_criteria_submitted",
        "task_acceptance_criteria_reviewed",
        "task_acceptance_decision_revised",
        "bugfix_assigned",
        "bugfix_orphan",
        "quality_alert",
        "feedback_created",
        "feedback_updated",
        "purchase_pending",
        "purchase_approved",
        "purchase_rejected",
        "rollover",
    }
)


def notification_is_important(notification_type: str) -> bool:
    return notification_type in IMPORTANT_NOTIFICATION_TYPES


def notification_dedupe_key(notification: Notification) -> str:
    source = notification.link or str(notification.id)
    digest = hashlib.md5(source.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"important:{notification.type}:{digest}"


async def emit_attention_event(
    db: AsyncSession,
    *,
    target_user_ids: list[UUID],
    kind: str,
    event_type: str,
    source_type: str,
    source_key: str,
    title: str,
    body: str = "",
    link: str | None = None,
    actor_id: UUID | None = None,
    dedupe_key: str,
    idempotency_key: str | None = None,
) -> CommunicationEvent | None:
    """Create an immutable event and reopen one deduplicated item per target.

    ``actor_id`` is removed from the target list, so a user never receives an
    attention item for their own action. A new event can replace an older
    unread projection with the same ``dedupe_key`` (for example several note
    comments) without growing the badge count.
    """
    if kind not in {"direct", "important"}:
        raise ValueError("Некорректный тип адресного события")

    targets = [
        user_id
        for user_id in dict.fromkeys(target_user_ids)
        if actor_id is None or user_id != actor_id
    ]
    if not targets:
        return None

    source_key = source_key.strip()[:180]
    dedupe_key = dedupe_key.strip()[:255]
    if not source_key or not dedupe_key:
        raise ValueError("Для адресного события нужен источник и ключ дедупликации")

    event_id: UUID | None = None
    if idempotency_key:
        idempotency_key = idempotency_key.strip()[:255]
        event_id = (
            await db.execute(
                insert(CommunicationEvent)
                .values(
                    id=uuid.uuid4(),
                    event_type=event_type,
                    actor_id=actor_id,
                    source_type=source_type,
                    source_key=source_key,
                    title=title,
                    body=body,
                    link=link,
                    idempotency_key=idempotency_key,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(CommunicationEvent.id)
            )
        ).scalar_one_or_none()
        if event_id is None:
            event_id = (
                await db.execute(
                    select(CommunicationEvent.id).where(
                        CommunicationEvent.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one()
    else:
        event = CommunicationEvent(
            event_type=event_type,
            actor_id=actor_id,
            source_type=source_type,
            source_key=source_key,
            title=title,
            body=body,
            link=link,
        )
        db.add(event)
        await db.flush()
        event_id = event.id

    now = datetime.now(timezone.utc)
    for user_id in targets:
        await db.execute(
            insert(UserAttentionItem)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                event_id=event_id,
                kind=kind,
                dedupe_key=dedupe_key,
                is_read=False,
                read_at=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_user_attention_items_user_dedupe",
                set_={
                    "event_id": event_id,
                    "kind": kind,
                    "is_read": False,
                    "read_at": None,
                    "updated_at": now,
                },
            )
        )

    return (
        await db.execute(
            select(CommunicationEvent).where(CommunicationEvent.id == event_id)
        )
    ).scalar_one()


async def list_attention_items(
    db: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    unread_only: bool = True,
    limit: int = 100,
):
    """Return inbox rows with optional actor data, newest activity first."""
    actor = aliased(User)
    stmt = (
        select(UserAttentionItem, CommunicationEvent, actor)
        .join(CommunicationEvent, CommunicationEvent.id == UserAttentionItem.event_id)
        .outerjoin(actor, actor.id == CommunicationEvent.actor_id)
        .where(UserAttentionItem.user_id == user_id, UserAttentionItem.kind == kind)
        .order_by(UserAttentionItem.updated_at.desc(), UserAttentionItem.id.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(UserAttentionItem.is_read.is_(False))
    return (await db.execute(stmt)).all()


async def get_attention_summary(db: AsyncSession, user_id: UUID) -> tuple[int, int]:
    direct_items = int(
        (
            await db.execute(
                select(func.count(UserAttentionItem.id)).where(
                    UserAttentionItem.user_id == user_id,
                    UserAttentionItem.kind == "direct",
                    UserAttentionItem.is_read.is_(False),
                )
            )
        ).scalar()
        or 0
    )
    unread_threads = int(
        (
            await db.execute(
                select(func.count(MessageThreadParticipant.id)).where(
                    MessageThreadParticipant.user_id == user_id,
                    MessageThreadParticipant.unread_count > 0,
                )
            )
        ).scalar()
        or 0
    )
    important_items = int(
        (
            await db.execute(
                select(func.count(UserAttentionItem.id)).where(
                    UserAttentionItem.user_id == user_id,
                    UserAttentionItem.kind == "important",
                    UserAttentionItem.is_read.is_(False),
                )
            )
        ).scalar()
        or 0
    )
    return direct_items + unread_threads, important_items


async def mark_attention_read(
    db: AsyncSession, *, user_id: UUID, item_id: UUID
) -> UserAttentionItem | None:
    item = (
        await db.execute(
            select(UserAttentionItem)
            .where(
                UserAttentionItem.id == item_id,
                UserAttentionItem.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        return None
    if not item.is_read:
        item.is_read = True
        item.read_at = datetime.now(timezone.utc)
        item.updated_at = item.read_at

    event = (
        await db.execute(
            select(CommunicationEvent).where(CommunicationEvent.id == item.event_id)
        )
    ).scalar_one()
    if event.source_type == "notification":
        try:
            notification_id = UUID(event.source_key)
        except (TypeError, ValueError):
            notification_id = None
        if notification_id is not None:
            await db.execute(
                update(Notification)
                .where(
                    Notification.id == notification_id,
                    Notification.user_id == user_id,
                )
                .values(is_read=True)
            )
    return item


async def mark_attention_context_read(
    db: AsyncSession,
    *,
    user_id: UUID,
    source_type: str,
    source_key: str | None = None,
) -> int:
    """Mark only direct items that belong to an opened business context."""
    event_ids_stmt = select(CommunicationEvent.id).where(
        CommunicationEvent.source_type == source_type
    )
    if source_key is not None:
        event_ids_stmt = event_ids_stmt.where(CommunicationEvent.source_key == source_key)
    result = await db.execute(
        update(UserAttentionItem)
        .where(
            UserAttentionItem.user_id == user_id,
            UserAttentionItem.kind == "direct",
            UserAttentionItem.is_read.is_(False),
            UserAttentionItem.event_id.in_(event_ids_stmt),
        )
        .values(
            is_read=True,
            read_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    return int(result.rowcount or 0)


async def mark_notification_attention_read(
    db: AsyncSession,
    *,
    user_id: UUID,
    notification_ids: list[UUID],
) -> int:
    """Keep legacy notification reads consistent with their attention mirrors."""
    identifiers = list(dict.fromkeys(notification_ids))
    if not identifiers:
        return 0
    event_ids = select(CommunicationEvent.id).where(
        CommunicationEvent.idempotency_key.in_(
            [f"notification:{notification_id}" for notification_id in identifiers]
        )
    )
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(UserAttentionItem)
        .where(
            UserAttentionItem.user_id == user_id,
            UserAttentionItem.is_read.is_(False),
            UserAttentionItem.event_id.in_(event_ids),
        )
        .values(is_read=True, read_at=now, updated_at=now)
    )
    return int(result.rowcount or 0)


async def resolve_attention_for_source(
    db: AsyncSession,
    *,
    user_id: UUID,
    source_type: str,
    source_key: str,
) -> int:
    return await mark_attention_context_read(
        db,
        user_id=user_id,
        source_type=source_type,
        source_key=source_key,
    )


async def mirror_notification_to_attention(
    db: AsyncSession,
    *,
    notification: Notification,
    actor_id: UUID | None = None,
    source_type: str = "notification",
    source_key: str | None = None,
    dedupe_key: str | None = None,
) -> CommunicationEvent | None:
    """Project a strict whitelist of legacy notifications into green inbox."""
    if not notification_is_important(notification.type):
        return None
    resolved_source_key = source_key or str(notification.id)
    resolved_dedupe_key = dedupe_key or notification_dedupe_key(notification)
    return await emit_attention_event(
        db,
        target_user_ids=[notification.user_id],
        kind="important",
        event_type=notification.type,
        source_type=source_type,
        source_key=resolved_source_key,
        title=notification.title,
        body=notification.message,
        link=notification.link,
        actor_id=actor_id,
        dedupe_key=resolved_dedupe_key,
        idempotency_key=f"notification:{notification.id}",
    )
