"""Схемы уведомлений."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationRead(BaseModel):
    """Уведомление для ответа API."""
    id: UUID
    user_id: UUID
    type: str
    title: str
    message: str
    is_read: bool
    link: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    """Количество непрочитанных."""
    count: int
