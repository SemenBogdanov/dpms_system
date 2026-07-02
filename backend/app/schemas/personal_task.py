"""Schemas for personal tasks."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.catalog import Complexity
from app.models.task import TaskPriority, TaskType
from app.models.user import League

PersonalTaskStatus = Literal["inbox", "planned", "next", "in_progress", "waiting", "blocked", "done", "archived"]
PersonalTaskPriority = Literal["low", "medium", "high", "critical"]
PersonalTaskCategory = Literal["work", "meeting", "follow_up", "research", "decision", "admin", "other"]
PersonalTaskEventType = Literal[
    "task_created",
    "task_updated",
    "status_changed",
    "meeting",
    "follow_up",
    "note",
    "checkpoint_created",
    "checkpoint_updated",
    "checkpoint_done",
    "promoted",
]
PersonalTaskManualEventType = Literal["meeting", "follow_up", "note"]
PersonalTaskCheckpointStatus = Literal["planned", "in_progress", "waiting", "blocked", "done"]


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


class PersonalTaskCreate(BaseModel):
    """Create current user's personal task."""

    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    notes: str | None = None
    status: PersonalTaskStatus = "inbox"
    priority: PersonalTaskPriority = "medium"
    category: PersonalTaskCategory = "work"
    project: str | None = Field(None, max_length=200)
    context: str | None = Field(None, max_length=200)
    responsible: str | None = Field(None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    acceptance_criteria: str | None = None
    next_step: str | None = Field(None, max_length=500)
    next_step_at: datetime | None = None
    due_at: datetime | None = None
    waiting_for: str | None = Field(None, max_length=200)
    blocked_reason: str | None = None
    impact: int | None = Field(None, ge=1, le=5)
    effort: int | None = Field(None, ge=1, le=5)
    linked_task_id: UUID | None = None
    source_quick_note_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Название личной задачи не может быть пустым")
        return cleaned

    @field_validator(
        "description",
        "notes",
        "project",
        "context",
        "responsible",
        "acceptance_criteria",
        "next_step",
        "waiting_for",
        "blocked_reason",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str]:
        return _clean_tags(value)


class PersonalTaskUpdate(BaseModel):
    """Patch current user's personal task."""

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    notes: str | None = None
    status: PersonalTaskStatus | None = None
    priority: PersonalTaskPriority | None = None
    category: PersonalTaskCategory | None = None
    project: str | None = Field(None, max_length=200)
    context: str | None = Field(None, max_length=200)
    responsible: str | None = Field(None, max_length=200)
    tags: list[str] | None = Field(None, max_length=20)
    acceptance_criteria: str | None = None
    next_step: str | None = Field(None, max_length=500)
    next_step_at: datetime | None = None
    due_at: datetime | None = None
    waiting_for: str | None = Field(None, max_length=200)
    blocked_reason: str | None = None
    impact: int | None = Field(None, ge=1, le=5)
    effort: int | None = Field(None, ge=1, le=5)
    linked_task_id: UUID | None = None
    source_quick_note_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название личной задачи не может быть пустым")
        return cleaned

    @field_validator(
        "description",
        "notes",
        "project",
        "context",
        "responsible",
        "acceptance_criteria",
        "next_step",
        "waiting_for",
        "blocked_reason",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)


class PersonalTaskPromoteRequest(BaseModel):
    """Create a global queue task from a personal task."""

    task_type: TaskType = TaskType.proactive
    complexity: Complexity = Complexity.S
    estimated_q: float = Field(default=0, ge=0)
    priority: TaskPriority = TaskPriority.medium
    min_league: League = League.C
    due_date: datetime | None = None
    tags: list[str] | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)


class PersonalTaskEventCreate(BaseModel):
    """Append manual task history event."""

    event_type: PersonalTaskManualEventType = "note"
    title: str | None = Field(None, max_length=200)
    body: str | None = None
    next_step: str | None = Field(None, max_length=500)
    waiting_for: str | None = Field(None, max_length=200)
    due_at: datetime | None = None
    metadata_json: dict | None = None

    @field_validator("title", "body", "next_step", "waiting_for", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class PersonalTaskEventRead(BaseModel):
    """Timeline event."""

    id: UUID
    task_id: UUID
    actor_id: UUID | None = None
    event_type: PersonalTaskEventType
    title: str | None = None
    body: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    next_step: str | None = None
    waiting_for: str | None = None
    due_at: datetime | None = None
    metadata_json: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonalTaskCheckpointCreate(BaseModel):
    """Create task control checkpoint."""

    title: str = Field(..., min_length=1, max_length=200)
    status: PersonalTaskCheckpointStatus = "planned"
    next_step: str | None = Field(None, max_length=500)
    waiting_for: str | None = Field(None, max_length=200)
    notes: str | None = None
    due_at: datetime | None = None
    sort_order: int = Field(default=100, ge=0, le=10000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Название этапа не может быть пустым")
        return cleaned

    @field_validator("next_step", "waiting_for", "notes", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class PersonalTaskCheckpointUpdate(BaseModel):
    """Patch task control checkpoint."""

    title: str | None = Field(None, min_length=1, max_length=200)
    status: PersonalTaskCheckpointStatus | None = None
    next_step: str | None = Field(None, max_length=500)
    waiting_for: str | None = Field(None, max_length=200)
    notes: str | None = None
    due_at: datetime | None = None
    sort_order: int | None = Field(None, ge=0, le=10000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Название этапа не может быть пустым")
        return cleaned

    @field_validator("next_step", "waiting_for", "notes", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class PersonalTaskCheckpointRead(BaseModel):
    """Read task control checkpoint."""

    id: UUID
    task_id: UUID
    title: str
    status: PersonalTaskCheckpointStatus
    next_step: str | None = None
    waiting_for: str | None = None
    notes: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonalTaskDeadlineRead(BaseModel):
    """Control deadline strip item."""

    item_type: Literal["task", "checkpoint"]
    item_id: UUID
    task_id: UUID
    task_key: str
    task_title: str
    title: str
    status: str
    due_at: datetime
    start_at: datetime
    responsible: str | None = None
    waiting_for: str | None = None
    project: str | None = None


class PersonalTaskRead(BaseModel):
    """Read personal task."""

    id: UUID
    task_number: int
    task_key: str
    owner_id: UUID
    title: str
    description: str | None = None
    notes: str | None = None
    status: PersonalTaskStatus
    priority: PersonalTaskPriority
    category: PersonalTaskCategory
    project: str | None = None
    context: str | None = None
    responsible: str | None = None
    tags: list[str] = Field(default_factory=list)
    acceptance_criteria: str | None = None
    next_step: str | None = None
    next_step_at: datetime | None = None
    due_at: datetime | None = None
    waiting_for: str | None = None
    blocked_reason: str | None = None
    impact: int | None = None
    effort: int | None = None
    linked_task_id: UUID | None = None
    source_quick_note_id: UUID | None = None
    promoted_task_id: UUID | None = None
    promoted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        if hasattr(obj, "task_number") and not isinstance(obj, dict):
            data = {
                key: getattr(obj, key)
                for key in (
                    "id",
                    "task_number",
                    "owner_id",
                    "title",
                    "description",
                    "notes",
                    "status",
                    "priority",
                    "category",
                    "project",
                    "context",
                    "responsible",
                    "tags",
                    "acceptance_criteria",
                    "next_step",
                    "next_step_at",
                    "due_at",
                    "waiting_for",
                    "blocked_reason",
                    "impact",
                    "effort",
                    "linked_task_id",
                    "source_quick_note_id",
                    "promoted_task_id",
                    "promoted_at",
                    "created_at",
                    "updated_at",
                )
            }
            data["task_key"] = f"PT-{obj.task_number}"
            return super().model_validate(data, *args, **kwargs)
        return super().model_validate(obj, *args, **kwargs)
