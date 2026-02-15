"""Сервис уведомлений: создание, список, пометка прочитанным."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    user_id: UUID,
    type: str,
    title: str,
    message: str = "",
    link: str | None = None,
) -> Notification:
    """Создать уведомление."""
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
    )
    db.add(n)
    await db.flush()
    await db.refresh(n)
    return n


async def get_user_notifications(
    db: AsyncSession,
    user_id: UUID,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    """Список уведомлений пользователя (новые сверху)."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_as_read(
    db: AsyncSession,
    notification_id: UUID,
    user_id: UUID,
) -> None:
    """Пометить уведомление как прочитанное (только своё)."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    n = result.scalar_one_or_none()
    if n:
        n.is_read = True
        db.add(n)


async def mark_all_as_read(db: AsyncSession, user_id: UUID) -> int:
    """Пометить все уведомления пользователя как прочитанные. Вернуть количество."""
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )
    notifications = result.scalars().all()
    for n in notifications:
        n.is_read = True
        db.add(n)
    return len(notifications)


async def get_unread_count(db: AsyncSession, user_id: UUID) -> int:
    """Количество непрочитанных уведомлений."""
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )
    return int(result.scalar() or 0)
