"""Схемы для базы знаний."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.knowledge import KnowledgeStatus


class KnowledgeArticleCreate(BaseModel):
    """Создание статьи базы знаний."""

    slug: str | None = Field(None, max_length=160)
    title: str = Field(..., max_length=255)
    summary: str = Field(default="", max_length=500)
    section: str = Field(default="general", max_length=80)
    body: str = Field(..., min_length=1)
    status: KnowledgeStatus = KnowledgeStatus.draft
    sort_order: int = 100


class KnowledgeArticleUpdate(BaseModel):
    """Частичное обновление статьи базы знаний."""

    slug: str | None = Field(None, max_length=160)
    title: str | None = Field(None, max_length=255)
    summary: str | None = Field(None, max_length=500)
    section: str | None = Field(None, max_length=80)
    body: str | None = Field(None, min_length=1)
    status: KnowledgeStatus | None = None
    sort_order: int | None = None


class KnowledgeArticleRead(BaseModel):
    """Чтение статьи базы знаний."""

    id: UUID
    slug: str
    title: str
    summary: str
    section: str
    body: str
    status: KnowledgeStatus
    sort_order: int
    created_by_id: UUID | None = None
    updated_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None

    model_config = {"from_attributes": True}
