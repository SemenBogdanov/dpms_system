"""API уведомлений. Все эндпоинты защищены JWT."""
from uuid import UUID

from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.notification import NotificationRead, UnreadCountResponse
from app.services.notifications import (
    get_user_notifications,
    mark_as_read as svc_mark_as_read,
    mark_all_as_read,
    get_unread_count,
)

router = APIRouter()


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список уведомлений текущего пользователя."""
    notifications = await get_user_notifications(db, user.id, unread_only=unread_only, limit=limit)
    return [NotificationRead.model_validate(n) for n in notifications]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Количество непрочитанных."""
    count = await get_unread_count(db, user.id)
    return UnreadCountResponse(count=count)


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пометить уведомление как прочитанное."""
    await svc_mark_as_read(db, notification_id, user.id)
    return {"ok": True}


@router.post("/read-all")
async def read_all_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пометить все уведомления как прочитанные."""
    count = await mark_all_as_read(db, user.id)
    return {"marked": count}
