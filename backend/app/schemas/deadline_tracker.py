"""Schemas for universal deadline trackers."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


REMINDER_UNITS = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}


def aware_date(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Дата должна содержать часовой пояс")
    return value


class TrackerRecurrence(BaseModel):
    frequency: Literal["day", "week", "month", "year"]
    interval: int = Field(1, ge=1, le=1000, strict=True)
    timezone: str = Field("Europe/Moscow", max_length=100)
    end_type: Literal["never", "until", "count"] = "never"
    until: datetime | None = None
    count: int | None = Field(None, ge=1, le=100000, strict=True)
    model_config = {"extra": "forbid"}

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Неизвестный часовой пояс")
        return value

    @model_validator(mode="after")
    def valid_end(self):
        if self.end_type == "until":
            if self.until is None or self.count is not None:
                raise ValueError("Для окончания по дате требуется только until")
            aware_date(self.until)
        elif self.end_type == "count":
            if self.count is None or self.until is not None:
                raise ValueError("Для окончания по числу требуется только count")
        elif self.until is not None or self.count is not None:
            raise ValueError("Бесконечная серия не имеет until/count")
        return self


class TrackerReminderInput(BaseModel):
    value: int = Field(1, ge=0, le=527040, strict=True)
    unit: Literal["minute", "hour", "day", "week"]
    model_config = {"extra": "forbid"}

    @property
    def offset_seconds(self) -> int:
        return self.value * REMINDER_UNITS[self.unit]

    @model_validator(mode="after")
    def bounded_offset(self):
        if self.offset_seconds > 366 * 86400:
            raise ValueError("Напоминание не может быть раньше срока более чем на 366 дней")
        return self


class TrackerOrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = Field(0, ge=0, le=1000000)
    model_config = {"extra": "forbid"}

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class TrackerCategoryUpdate(TrackerOrganizationCreate):
    name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = Field(None, ge=0, le=1000000)
    is_archived: bool | None = None

    @model_validator(mode="after")
    def reject_nulls(self):
        for name in self.model_fields_set - {"color"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        return self


class TrackerGroupUpdate(TrackerCategoryUpdate):
    is_collapsed: bool | None = None


class TrackerCategoryRead(TrackerOrganizationCreate):
    id: UUID
    is_archived: bool
    legacy_type: str | None
    model_config = {"from_attributes": True}


class TrackerGroupRead(TrackerOrganizationCreate):
    id: UUID
    is_archived: bool
    is_collapsed: bool
    model_config = {"from_attributes": True}


class TrackerReorder(BaseModel):
    ids: list[UUID] = Field(max_length=1000)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Повторяющиеся группы")
        return value


class TrackerOccurrenceRead(BaseModel):
    id: UUID
    sequence: int
    due_at: datetime
    status: Literal["pending", "completed", "cancelled"]
    completed_at: datetime | None
    model_config = {"from_attributes": True}


class TrackerEventRead(BaseModel):
    id: UUID
    event_type: str
    details: dict
    created_at: datetime
    model_config = {"from_attributes": True}


class TrackerAlertRead(BaseModel):
    id: UUID
    occurrence_id: UUID
    reminder_id: UUID
    scheduled_for: datetime
    status: Literal["pending", "sent", "suppressed", "cancelled"]
    delivered_at: datetime | None
    notification_id: UUID | None
    is_read: bool | None = None
    model_config = {"from_attributes": True}

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
    group_id: UUID | None = None
    category_id: UUID | None = None
    url: str | None = Field(None, max_length=2000)
    recurrence: TrackerRecurrence | None = None
    reminders: list[TrackerReminderInput] = Field(default_factory=list, max_length=10)

    @field_validator("starts_at", "due_at")
    @classmethod
    def validate_timezone(cls, value):
        return aware_date(value)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        if not value:
            return None
        from pydantic import HttpUrl, TypeAdapter
        return str(TypeAdapter(HttpUrl).validate_python(value))

    @field_validator("reminders")
    @classmethod
    def unique_reminders(cls, value):
        if value is not None and len({r.offset_seconds for r in value}) != len(value):
            raise ValueError("Напоминания должны иметь уникальные смещения")
        return value

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
        if self.personal_task_id and self.linked_task_id:
            raise ValueError("У трекера может быть только один источник")
        if self.recurrence:
            if self.personal_task_id or self.linked_task_id:
                raise ValueError("Связанный трекер может быть только разовым")
            if self.recurrence.until and self.recurrence.until < self.due_at:
                raise ValueError("Окончание серии раньше первого срока")
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
    group_id: UUID | None = None
    category_id: UUID | None = None
    url: str | None = Field(None, max_length=2000)
    recurrence: TrackerRecurrence | None = None
    reminders: list[TrackerReminderInput] | None = Field(None, max_length=10)

    validate_url = field_validator("url")(DeadlineTrackerCreate.validate_url.__func__)
    unique_reminders = field_validator("reminders")(DeadlineTrackerCreate.unique_reminders.__func__)

    @field_validator("starts_at", "due_at")
    @classmethod
    def validate_timezone(cls, value):
        return aware_date(value) if value is not None else None

    @model_validator(mode="after")
    def reject_nulls(self):
        required = {"title", "tracker_type", "status", "starts_at", "due_at", "tags", "reminders"}
        for name in required & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        return self

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
    group_id: UUID | None = None
    category_id: UUID | None = None
    url: str | None = None
    recurrence: TrackerRecurrence | None = None
    reminders: list[TrackerReminderInput] = Field(default_factory=list)
    source: Literal["standalone", "personal_task", "task"] = "standalone"
    source_available: bool = True
    source_title: str | None = None
    source_responsible: str | None = None
    current_occurrence: TrackerOccurrenceRead | None = None
    series_exhausted: bool = False
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
