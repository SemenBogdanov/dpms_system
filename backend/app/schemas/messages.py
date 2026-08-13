"""API contracts for focused attention and asynchronous correspondence."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


AttentionKind = Literal["direct", "important"]
AttentionSourceType = Literal["contact", "quick_note"]


class AttentionSummaryRead(BaseModel):
    direct_count: int = 0
    important_count: int = 0


class AttentionItemRead(BaseModel):
    id: UUID
    kind: AttentionKind
    event_type: str
    title: str
    body: str
    link: str | None
    source_type: str
    source_key: str
    actor_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    is_read: bool
    created_at: datetime
    updated_at: datetime


class AttentionContextRead(BaseModel):
    source_type: AttentionSourceType
    source_key: str | None = Field(default=None, max_length=180)

    @field_validator("source_key", mode="before")
    @classmethod
    def clean_source_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class MessageThreadCreate(BaseModel):
    recipient_id: UUID
    subject: str = Field(..., min_length=1, max_length=180)
    body: str = Field(..., min_length=1, max_length=20_000)
    quick_note_id: UUID | None = None
    request_id: UUID

    @field_validator("subject", "body", mode="before")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        return (value or "").strip()


class MessagePostCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=20_000)
    quick_note_id: UUID | None = None
    request_id: UUID

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str) -> str:
        return (value or "").strip()


class MessageParticipantRead(BaseModel):
    user_id: UUID
    full_name: str
    email: str


class MessagePostRead(BaseModel):
    id: UUID
    thread_id: UUID
    author_id: UUID
    author_name: str
    author_email: str
    body: str
    quick_note_id: UUID | None
    quick_note_title: str | None
    quick_note_available: bool
    created_at: datetime


class MessageThreadRead(BaseModel):
    id: UUID
    subject: str
    created_by_id: UUID
    participants: list[MessageParticipantRead]
    last_post_preview: str
    last_post_at: datetime
    unread_count: int
    created_at: datetime
    updated_at: datetime


class MessageThreadDetailRead(MessageThreadRead):
    posts: list[MessagePostRead]
