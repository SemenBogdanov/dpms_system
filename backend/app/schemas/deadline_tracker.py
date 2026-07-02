"""Schemas for universal deadline trackers."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

DeadlineTrackerType = Literal["subscription", "system", "password", "task", "document", "payment", "other"]
DeadlineTrackerStatus = Literal["active", "paused", "done", "archived"]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_tags(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    raw = value.split(",") if isinstance(value, str) else value
    tags: list[str] = []
    for item in raw:
        cleaned = str(item).strip()
        if cleaned and cleaned not in tags:
            tags.append(cleaned[:40])
    return tags[:20]


class DeadlineTrackerCreate(BaseModel):
    """Create current user's timeline item."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    tracker_type: DeadlineTrackerType = "other"
    status: DeadlineTrackerStatus = "active"
    starts_at: datetime
    due_at: datetime
    next_action: str | None = Field(None, max_length=500)
    responsible: str | None = Field(None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    personal_task_id: UUID | None = None
    linked_task_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Название трекера не может быть пустым")
        return cleaned

    @field_validator("description", "next_action", "responsible", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str]:
        return _clean_tags(value)

    @model_validator(mode="after")
    def validate_dates(self) -> "DeadlineTrackerCreate":
        if self.due_at <= self.starts_at:
            raise ValueError("Дедлайн должен быть позже даты старта")
        return self


class DeadlineTrackerUpdate(BaseModel):
    """Patch timeline item."""

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    tracker_type: DeadlineTrackerType | None = None
    status: DeadlineTrackerStatus | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    next_action: str | None = Field(None, max_length=500)
    responsible: str | None = Field(None, max_length=200)
    tags: list[str] | None = Field(None, max_length=20)
    personal_task_id: UUID | None = None
    linked_task_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название трекера не может быть пустым")
        return cleaned

    @field_validator("description", "next_action", "responsible", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)


class DeadlineTrackerRead(BaseModel):
    """Timeline item returned to frontend."""

    id: UUID
    owner_id: UUID
    title: str
    description: str | None
    tracker_type: DeadlineTrackerType
    status: DeadlineTrackerStatus
    starts_at: datetime
    due_at: datetime
    pause_started_at: datetime | None
    paused_seconds: int
    shifted_due_at: datetime | None = None
    total_pause_seconds: int = 0
    next_action: str | None
    responsible: str | None
    tags: list[str]
    personal_task_id: UUID | None
    linked_task_id: UUID | None
    personal_task_key: str | None = None
    personal_task_title: str | None = None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
