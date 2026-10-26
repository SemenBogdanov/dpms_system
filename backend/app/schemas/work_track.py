"""Schemas for task tracks and ordered work sequences."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


WorkTrackStatus = Literal["draft", "active", "paused", "done", "archived"]
WorkTrackItemType = Literal["task", "personal_task", "manual", "cube"]
WorkTrackItemStatus = Literal["active", "waiting", "blocked", "done", "skipped"]
WorkTrackReservationStatus = Literal["draft", "sent", "reserved", "declined", "released"]


class WorkMethodologyImport(BaseModel):
    payload: dict[str, Any]
    source_kind: str = Field(default="kubiki_json", max_length=60)

    @field_validator("source_kind", mode="before")
    @classmethod
    def clean_source_kind(cls, value):
        if isinstance(value, str):
            value = value.strip() or "kubiki_json"
        return value


class WorkMethodologyRead(BaseModel):
    id: UUID
    created_by_id: UUID | None = None
    title: str
    description: str | None = None
    schema_version: int | None = None
    methodology_version: str | None = None
    display_version: str | None = None
    release_kind: str | None = None
    source_kind: str
    fingerprint: str
    stages_count: int = 0
    cubes_count: int = 0
    routes_count: int = 0
    products_count: int = 0
    is_active: bool = False
    activated_at: datetime | None = None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkTrackApplyMethodologyRequest(BaseModel):
    methodology_id: UUID
    route_key: str | None = Field(None, max_length=100)
    product_key: str | None = Field(None, max_length=100)
    replace_existing_cubes: bool = False

    @field_validator("route_key", "product_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        if isinstance(value, str):
            value = value.strip() or None
        return value


class WorkTrackSendReviewRequest(BaseModel):
    item_ids: list[UUID] | None = None


class WorkTrackReservationDecisionRequest(BaseModel):
    decision: Literal["reserved", "declined"]
    comment: str | None = Field(None, max_length=2000)

    @field_validator("comment", mode="before")
    @classmethod
    def clean_comment(cls, value):
        if isinstance(value, str):
            value = value.strip() or None
        return value


class WorkTrackCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = None
    status: WorkTrackStatus = "draft"
    start_at: datetime | None = None
    due_at: datetime | None = None
    color: str = Field(default="slate", max_length=30)
    methodology_id: UUID | None = None
    product_key: str | None = Field(None, max_length=100)
    route_key: str | None = Field(None, max_length=100)

    @field_validator("title", "description", "color", "product_key", "route_key", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_at is not None and self.due_at is not None and self.due_at <= self.start_at:
            raise ValueError("Дата окончания трека должна быть позже даты старта")
        return self


class WorkTrackActivationIssue(BaseModel):
    item_id: UUID | None = None
    item_title: str | None = None
    code: str
    message: str


class WorkTrackReadinessRead(BaseModel):
    can_activate: bool
    issues: list[WorkTrackActivationIssue] = []


class WorkTrackUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = None
    status: WorkTrackStatus | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    color: str | None = Field(None, max_length=30)
    methodology_id: UUID | None = None
    product_key: str | None = Field(None, max_length=100)
    route_key: str | None = Field(None, max_length=100)

    @field_validator("title", "description", "color", "product_key", "route_key", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value


class WorkTrackItemCreate(BaseModel):
    item_type: WorkTrackItemType
    task_id: UUID | None = None
    personal_task_id: UUID | None = None
    methodology_id: UUID | None = None
    methodology_node_type: str | None = Field(None, max_length=40)
    methodology_node_id: str | None = Field(None, max_length=120)
    methodology_stage_id: str | None = Field(None, max_length=120)
    methodology_snapshot: dict[str, Any] | None = None
    checklist_snapshot: list[Any] | dict[str, Any] | None = None
    proposed_executor_email: str | None = Field(None, max_length=320)
    proposed_executor_name: str | None = Field(None, max_length=200)
    reservation_status: WorkTrackReservationStatus = "draft"
    title: str | None = Field(None, max_length=300)
    description: str | None = None
    status: WorkTrackItemStatus = "active"
    position: int | None = Field(None, ge=0)
    starts_at: datetime | None = None
    due_at: datetime | None = None
    notes: str | None = None

    @field_validator(
        "title",
        "description",
        "notes",
        "methodology_node_type",
        "methodology_node_id",
        "methodology_stage_id",
        "proposed_executor_email",
        "proposed_executor_name",
        mode="before",
    )
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_link(self):
        if self.item_type == "task" and self.task_id is None:
            raise ValueError("Для элемента типа task нужна task_id")
        if self.item_type == "personal_task" and self.personal_task_id is None:
            raise ValueError("Для элемента типа personal_task нужна personal_task_id")
        if self.item_type == "manual" and not self.title:
            raise ValueError("Для ручного элемента нужно название")
        if self.item_type == "cube" and not (self.methodology_node_id or self.title):
            raise ValueError("Для кубика нужен идентификатор методологии или название")
        if self.item_type != "task":
            self.task_id = None
        if self.item_type != "personal_task":
            self.personal_task_id = None
        if self.proposed_executor_email:
            self.proposed_executor_email = self.proposed_executor_email.lower()
        if self.starts_at is not None and self.due_at is not None and self.due_at <= self.starts_at:
            raise ValueError("Срок элемента должен быть позже даты старта")
        return self


class WorkTrackItemUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    description: str | None = None
    status: WorkTrackItemStatus | None = None
    position: int | None = Field(None, ge=0)
    starts_at: datetime | None = None
    due_at: datetime | None = None
    notes: str | None = None
    checklist_snapshot: list[Any] | dict[str, Any] | None = None
    proposed_executor_email: str | None = Field(None, max_length=320)
    proposed_executor_name: str | None = Field(None, max_length=200)
    reservation_status: WorkTrackReservationStatus | None = None

    @field_validator("title", "description", "notes", "proposed_executor_email", "proposed_executor_name", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def normalize_email(self):
        if self.proposed_executor_email:
            self.proposed_executor_email = self.proposed_executor_email.lower()
        return self


class WorkTrackReorderRequest(BaseModel):
    item_ids: list[UUID] = Field(..., min_length=1)


class WorkTrackItemRead(BaseModel):
    id: UUID
    track_id: UUID
    item_type: str
    task_id: UUID | None = None
    personal_task_id: UUID | None = None
    methodology_id: UUID | None = None
    methodology_node_type: str | None = None
    methodology_node_id: str | None = None
    methodology_stage_id: str | None = None
    methodology_snapshot: dict[str, Any] | None = None
    checklist_snapshot: list[Any] | dict[str, Any] | None = None
    proposed_executor_email: str | None = None
    proposed_executor_name: str | None = None
    reservation_status: str = "draft"
    title: str | None = None
    description: str | None = None
    status: str
    position: int
    starts_at: datetime | None = None
    due_at: datetime | None = None
    notes: str | None = None
    linked_title: str | None = None
    linked_number: int | None = None
    linked_status: str | None = None
    linked_due_at: datetime | None = None
    effective_title: str
    effective_due_at: datetime | None = None
    is_done: bool = False
    source_available: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkTrackRead(BaseModel):
    id: UUID
    owner_id: UUID
    title: str
    description: str | None = None
    status: str
    start_at: datetime | None = None
    due_at: datetime | None = None
    color: str
    methodology_id: UUID | None = None
    methodology_title: str | None = None
    methodology_version: str | None = None
    product_key: str | None = None
    route_key: str | None = None
    route_name: str | None = None
    methodology_snapshot: dict[str, Any] | None = None
    route_snapshot: dict[str, Any] | None = None
    items_count: int = 0
    done_count: int = 0
    progress_percent: int = 0
    next_due_at: datetime | None = None
    items: list[WorkTrackItemRead] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkTrackAssignedItemRead(BaseModel):
    track_id: UUID
    track_title: str
    track_owner_id: UUID
    item: WorkTrackItemRead
