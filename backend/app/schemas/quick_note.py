"""Schemas for personal quick notes."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

QuickNoteStatus = Literal["draft", "processed", "archived"]
QuickNoteShareStatus = Literal["active", "revoked"]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_tags(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in value:
        item = tag.strip().lower()
        if item and item not in cleaned:
            cleaned.append(item[:40])
    return cleaned[:8]


class QuickNoteCreate(BaseModel):
    """Create current user's quick note."""

    title: str | None = Field(None, max_length=160)
    body: str = Field(..., min_length=1)
    context: str | None = Field(None, max_length=160)
    tags: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("title", "context", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Текст заметки не может быть пустым")
        return cleaned

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class QuickNoteUpdate(BaseModel):
    """Patch current user's quick note."""

    title: str | None = Field(None, max_length=160)
    body: str | None = Field(None, min_length=1)
    context: str | None = Field(None, max_length=160)
    status: QuickNoteStatus | None = None
    tags: list[str] | None = Field(None, max_length=8)

    @field_validator("title", "context", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Текст заметки не может быть пустым")
        return cleaned

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)


class QuickNoteRead(BaseModel):
    """Read quick note."""

    id: UUID
    owner_id: UUID
    title: str
    body: str
    context: str | None = None
    status: QuickNoteStatus
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuickNoteShareCreate(BaseModel):
    """Share a note with accepted contacts."""

    recipient_ids: list[UUID] = Field(..., min_length=1, max_length=20)


class QuickNoteShareRead(BaseModel):
    """Read a quick-note share."""

    id: UUID
    note_id: UUID
    owner_id: UUID
    owner_name: str
    owner_email: str
    recipient_id: UUID
    recipient_name: str
    recipient_email: str
    status: QuickNoteShareStatus
    created_at: datetime
    updated_at: datetime


class SharedQuickNoteRead(BaseModel):
    """Read a note shared with current user."""

    share: QuickNoteShareRead
    note: QuickNoteRead


class QuickNoteAttachmentRead(BaseModel):
    """Metadata for a quick-note attachment."""

    id: UUID
    note_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class QuickNoteCommentCreate(BaseModel):
    """Discussion comment body for a note."""

    body: str = Field(..., min_length=1, max_length=5000)
    parent_id: UUID | None = None

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Текст комментария не может быть пустым")
        return cleaned


class QuickNoteCommentRead(BaseModel):
    """Read a note discussion comment."""

    id: UUID
    note_id: UUID
    author_id: UUID
    author_name: str
    author_email: str
    parent_id: UUID | None = None
    body: str
    created_at: datetime
