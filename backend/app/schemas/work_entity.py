"""Schemas for projects, goals, and their typed links."""
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.catalog import Complexity
from app.models.task import TaskPriority, TaskStatus, TaskType
from app.models.user import League
from app.schemas.task_acceptance import (
    AcceptanceCriterionCreate,
    AcceptanceMode,
    AcceptanceState,
    validate_acceptance_plan,
)

WorkEntityType = Literal["project", "initiative", "goal", "system", "kpi", "other"]
WorkEntityStatus = Literal["draft", "active", "paused", "done", "archived"]
WorkEntityVisibility = Literal["private", "shared"]
WorkEntityMemberRole = Literal["viewer", "participant", "editor"]
WorkEntityAccessRole = Literal["owner", "editor", "participant", "viewer"]
WorkEntityPlanningMode = Literal["free", "methodology"]
WorkEntityStageStatus = Literal["planned", "active", "done", "cancelled"]
WorkEntityStageSource = Literal["manual", "methodology"]
WorkEntityTaskStatus = Literal[
    "planned",
    "in_progress",
    "waiting",
    "blocked",
    "review",
    "done",
    "cancelled",
]
WorkEntityTaskPriority = Literal["low", "medium", "high", "critical"]
WorkEntityMilestoneLifecycleStatus = Literal["planned", "achieved", "cancelled"]
WorkEntityMilestoneDisplayStatus = Literal[
    "planned",
    "rescheduled",
    "overdue",
    "achieved",
    "cancelled",
]
WorkEntityMilestoneCriticality = Literal["control", "key", "critical"]
WorkEntityScheduleNodeType = Literal["task", "milestone"]
WorkEntityScheduleDependencyType = Literal["finish_to_start"]
WorkEntityScheduleDependencyStatus = Literal["active", "waived"]
WorkEntityArtifactType = Literal[
    "note",
    "decision",
    "evidence",
    "document",
    "reference",
    "other",
]
WorkEntityArtifactStatus = Literal["active", "archived"]
WorkEntityJournalEntryType = Literal[
    "progress",
    "meeting",
    "decision",
    "blocker",
    "comment",
]
WorkEntityTargetType = Literal[
    "entity",
    "task",
    "personal_task",
    "quick_note",
    "deadline_tracker",
]
WorkEntityRelationType = Literal[
    "contains",
    "contributes_to",
    "depends_on",
    "measures",
    "related",
]
WorkEntityExecutionContractSource = Literal[
    "linked_existing",
    "created_from_operation",
]
WorkEntityExecutionContractStatus = Literal["active", "released"]


def _clean_required(value: str, message: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(message)
    return cleaned


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
        cleaned = str(item).strip().lower()
        if cleaned and cleaned not in tags:
            tags.append(cleaned[:40])
    return tags[:20]


class _PatchModel(BaseModel):
    """Reject explicit nulls for fields backed by NOT NULL columns."""

    required_patch_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def reject_required_nulls(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        null_fields = sorted(
            field
            for field in cls.required_patch_fields
            if field in data and data[field] is None
        )
        if null_fields:
            raise ValueError(
                "Поля не могут иметь значение null: "
                + ", ".join(null_fields)
            )
        return data


class WorkEntityCreate(BaseModel):
    """Create a private-by-default entity."""

    entity_type: WorkEntityType
    title: str = Field(..., min_length=1, max_length=240)
    description: str | None = None
    outcome_statement: str | None = None
    success_criteria: str | None = None
    constraints: str | None = None
    status: WorkEntityStatus = "draft"
    visibility: WorkEntityVisibility = "private"
    starts_at: datetime | None = None
    due_at: datetime | None = None
    planning_mode: WorkEntityPlanningMode = "free"
    methodology_title: str | None = Field(None, max_length=240)
    methodology_version: str | None = Field(None, max_length=80)
    methodology_snapshot: dict | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    details_json: dict | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required(value, "Название сущности не может быть пустым")

    @field_validator(
        "description",
        "outcome_statement",
        "success_criteria",
        "constraints",
        "methodology_title",
        "methodology_version",
        mode="before",
    )
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str]:
        return _clean_tags(value)

    @model_validator(mode="after")
    def validate_dates(self) -> "WorkEntityCreate":
        if self.starts_at and self.due_at and self.due_at <= self.starts_at:
            raise ValueError("Дата окончания должна быть позже даты начала")
        return self


class WorkEntityUpdate(_PatchModel):
    """Patch descriptive fields and lifecycle state."""

    required_patch_fields = frozenset(
        {
            "entity_type",
            "title",
            "status",
            "visibility",
            "planning_mode",
            "tags",
        }
    )
    entity_type: WorkEntityType | None = None
    title: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = None
    outcome_statement: str | None = None
    success_criteria: str | None = None
    constraints: str | None = None
    status: WorkEntityStatus | None = None
    visibility: WorkEntityVisibility | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    planning_mode: WorkEntityPlanningMode | None = None
    methodology_title: str | None = Field(None, max_length=240)
    methodology_version: str | None = Field(None, max_length=80)
    methodology_snapshot: dict | None = None
    tags: list[str] | None = Field(None, max_length=20)
    details_json: dict | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value, "Название сущности не может быть пустым")

    @field_validator(
        "description",
        "outcome_statement",
        "success_criteria",
        "constraints",
        "methodology_title",
        "methodology_version",
        mode="before",
    )
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_tags(value)


class WorkEntityRead(BaseModel):
    """Entity list/detail item with the current user's access role."""

    id: UUID
    owner_id: UUID
    owner_name: str
    owner_email: str | None
    entity_type: WorkEntityType
    title: str
    description: str | None
    outcome_statement: str | None
    success_criteria: str | None
    constraints: str | None
    baseline_outcome_statement: str | None
    baseline_success_criteria: str | None
    baseline_constraints: str | None
    status: WorkEntityStatus
    visibility: WorkEntityVisibility
    starts_at: datetime | None
    due_at: datetime | None
    target_due_at: datetime | None
    forecast_starts_at: datetime | None
    forecast_due_at: datetime | None
    actual_starts_at: datetime | None
    actual_due_at: datetime | None
    planning_mode: WorkEntityPlanningMode
    methodology_title: str | None
    methodology_version: str | None
    methodology_snapshot: dict | None
    baseline_locked_at: datetime | None
    baseline_locked_by_id: UUID | None
    schedule_revision: int
    tags: list[str]
    details_json: dict | None
    archived_at: datetime | None
    access_role: WorkEntityAccessRole
    members_count: int = 0
    links_count: int = 0
    stages_count: int = 0
    tasks_count: int = 0
    milestones_count: int = 0
    artifacts_count: int = 0
    created_at: datetime
    updated_at: datetime


class WorkEntityMemberCreate(BaseModel):
    """Share an entity with an accepted contact."""

    user_id: UUID
    role: WorkEntityMemberRole = "participant"


class WorkEntityMemberUpdate(BaseModel):
    """Change viewer/editor role."""

    role: WorkEntityMemberRole


class WorkEntityMemberRead(BaseModel):
    """Entity member with display identity."""

    id: UUID
    entity_id: UUID
    user_id: UUID
    user_name: str
    user_email: str | None
    role: WorkEntityMemberRole
    created_at: datetime
    updated_at: datetime


class WorkEntityLinkCreate(BaseModel):
    """Link an entity to one accessible target."""

    target_type: WorkEntityTargetType
    target_id: UUID
    relation_type: WorkEntityRelationType = "contains"
    notes: str | None = Field(None, max_length=2000)
    position: int = Field(0, ge=0, le=100000)

    @field_validator("notes", mode="before")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityLinkUpdate(_PatchModel):
    """Patch link semantics without changing its target."""

    required_patch_fields = frozenset({"relation_type", "position"})
    relation_type: WorkEntityRelationType | None = None
    notes: str | None = Field(None, max_length=2000)
    position: int | None = Field(None, ge=0, le=100000)

    @field_validator("notes", mode="before")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityLinkRead(BaseModel):
    """Link enriched only with target data visible to the current user."""

    id: UUID
    entity_id: UUID
    relation_type: WorkEntityRelationType
    notes: str | None
    position: int
    target_type: WorkEntityTargetType
    target_accessible: bool
    target_id: UUID | None = None
    target_title: str | None = None
    target_subtitle: str | None = None
    target_status: str | None = None
    target_starts_at: datetime | None = None
    target_due_at: datetime | None = None
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class WorkEntityLinkOption(BaseModel):
    """One accessible object offered by the link picker."""

    target_type: WorkEntityTargetType
    target_id: UUID
    title: str
    subtitle: str | None = None
    status: str | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None


class WorkEntitySummary(BaseModel):
    """Transparent direct-link summary without recursive or weighted progress."""

    entity_id: UUID
    accessible_links: int
    restricted_links: int
    native_tasks: int = 0
    artifacts: int = 0
    work_items_total: int
    work_items_done: int
    overdue_items: int
    next_due_at: datetime | None
    counts_by_type: dict[str, int]
    counts_by_status: dict[str, int]


class WorkEntityReadinessIssue(BaseModel):
    severity: Literal["blocking", "warning"]
    code: str
    scope_type: Literal["entity", "stage", "task", "milestone"]
    scope_id: UUID
    scope_ref: str | None = None
    scope_title: str
    field: str | None = None
    message: str
    guidance: str


class WorkEntityReadinessRead(BaseModel):
    entity_id: UUID
    can_activate: bool
    blocking_count: int
    warning_count: int
    issues: list[WorkEntityReadinessIssue]


class WorkEntityEventRead(BaseModel):
    """Structured audit event: actor, object, change, reason, and impact."""

    id: UUID
    entity_id: UUID
    actor_id: UUID | None
    actor_name: str | None
    event_type: str
    object_type: str | None = None
    object_id: UUID | None = None
    object_ref: str | None = None
    object_title: str | None = None
    action: str | None = None
    reason: str | None = None
    correlation_id: UUID | None = None
    payload: dict | None
    created_at: datetime


class WorkEntityReverseLinkRead(BaseModel):
    """Entity backlink shown from a linked task, note, or tracker."""

    link_id: UUID
    entity_id: UUID
    entity_type: WorkEntityType
    entity_title: str
    entity_status: WorkEntityStatus
    relation_type: WorkEntityRelationType
    access_role: WorkEntityAccessRole


class WorkEntityStageCreate(BaseModel):
    """Create a manual or methodology-derived project stage."""

    title: str = Field(..., min_length=1, max_length=240)
    description: str | None = None
    completion_criteria: str | None = None
    guidance: str | None = None
    status: WorkEntityStageStatus = "planned"
    source_type: WorkEntityStageSource = "manual"
    source_key: str | None = Field(None, max_length=120)
    source_snapshot: dict | None = None
    position: int = Field(0, ge=0, le=100000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required(value, "Название этапа не может быть пустым")

    @field_validator(
        "description",
        "completion_criteria",
        "guidance",
        "source_key",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityStageUpdate(_PatchModel):
    required_patch_fields = frozenset({"title", "status", "position"})
    title: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = None
    completion_criteria: str | None = None
    guidance: str | None = None
    status: WorkEntityStageStatus | None = None
    position: int | None = Field(None, ge=0, le=100000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value, "Название этапа не может быть пустым")

    @field_validator(
        "description",
        "completion_criteria",
        "guidance",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityStageRead(BaseModel):
    id: UUID
    entity_id: UUID
    title: str
    description: str | None
    completion_criteria: str | None
    guidance: str | None
    status: WorkEntityStageStatus
    source_type: WorkEntityStageSource
    source_key: str | None
    source_snapshot: dict | None
    position: int
    tasks_count: int
    milestones_count: int
    can_manage: bool
    created_at: datetime
    updated_at: datetime


class WorkEntityTaskCreate(BaseModel):
    """Create executable work; dates become its immutable initial baseline."""

    title: str = Field(..., min_length=1, max_length=240)
    description: str | None = None
    status: WorkEntityTaskStatus = "planned"
    priority: WorkEntityTaskPriority = "medium"
    assignee_id: UUID | None = None
    stage_id: UUID | None = None
    target_milestone_id: UUID | None = None
    acceptance_criteria: str | None = None
    next_step: str | None = Field(None, max_length=500)
    waiting_for: str | None = Field(None, max_length=240)
    baseline_starts_at: datetime | None = None
    baseline_due_at: datetime | None = None
    position: int = Field(0, ge=0, le=100000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required(value, "Название задачи не может быть пустым")

    @field_validator(
        "description",
        "acceptance_criteria",
        "next_step",
        "waiting_for",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def validate_dates(self) -> "WorkEntityTaskCreate":
        if (
            self.baseline_starts_at
            and self.baseline_due_at
            and self.baseline_due_at <= self.baseline_starts_at
        ):
            raise ValueError("Срок задачи должен быть позже даты начала")
        return self


class WorkEntityTaskUpdate(_PatchModel):
    """Patch task execution or current forecast without rewriting baseline."""

    required_patch_fields = frozenset(
        {"title", "status", "priority", "position"}
    )
    title: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = None
    status: WorkEntityTaskStatus | None = None
    priority: WorkEntityTaskPriority | None = None
    assignee_id: UUID | None = None
    stage_id: UUID | None = None
    target_milestone_id: UUID | None = None
    acceptance_criteria: str | None = None
    next_step: str | None = Field(None, max_length=500)
    waiting_for: str | None = Field(None, max_length=240)
    forecast_starts_at: datetime | None = None
    forecast_due_at: datetime | None = None
    position: int | None = Field(None, ge=0, le=100000)
    change_reason: str | None = Field(None, max_length=2000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value, "Название задачи не может быть пустым")

    @field_validator(
        "description",
        "acceptance_criteria",
        "next_step",
        "waiting_for",
        "change_reason",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityExecutionContractTaskOption(BaseModel):
    """Eligible global Q task that can be linked to an operation."""

    task_id: UUID
    task_number: int
    title: str
    status: TaskStatus
    estimated_q: Decimal
    priority: TaskPriority
    due_date: datetime
    acceptance_mode: AcceptanceMode
    acceptance_state: AcceptanceState
    assignee_name: str | None = None


class WorkEntityExecutionContractCreateRequest(BaseModel):
    """Link an existing Q task or publish a new one from an operation."""

    mode: Literal["link", "publish"]
    idempotency_key: UUID
    task_id: UUID | None = None
    title: str | None = Field(None, min_length=5, max_length=120)
    description: str | None = Field(None, max_length=8000)
    task_type: TaskType | None = None
    complexity: Complexity | None = None
    estimated_q: Decimal | None = Field(None, ge=0, le=9999)
    priority: TaskPriority | None = None
    min_league: League | None = None
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    acceptance_mode: AcceptanceMode | None = None
    acceptance_criteria: list[AcceptanceCriterionCreate] = Field(
        default_factory=list,
        max_length=50,
    )

    @field_validator("title", "description", mode="before")
    @classmethod
    def clean_publish_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("due_date")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Срок Q-задачи должен содержать часовой пояс")
        return value

    @model_validator(mode="after")
    def validate_mode_payload(self):
        if self.mode == "link":
            if self.task_id is None:
                raise ValueError("Выберите Q-задачу для привязки")
            publish_fields = (
                self.title,
                self.task_type,
                self.complexity,
                self.estimated_q,
                self.priority,
                self.min_league,
                self.due_date,
                self.acceptance_mode,
            )
            if any(value is not None for value in publish_fields) or self.acceptance_criteria:
                raise ValueError("Для привязки существующей задачи не передавайте поля публикации")
            return self

        if self.task_id is not None:
            raise ValueError("Для новой Q-задачи task_id не передается")
        required = {
            "title": self.title,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "estimated_q": self.estimated_q,
            "priority": self.priority,
            "min_league": self.min_league,
            "due_date": self.due_date,
            "acceptance_mode": self.acceptance_mode,
        }
        missing = [field for field, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "Заполните поля публикации: " + ", ".join(missing)
            )
        validate_acceptance_plan(self.acceptance_mode, self.acceptance_criteria)
        return self


class WorkEntityExecutionContractReleaseRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=4000)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return _clean_required(value, "Укажите причину освобождения Q-контракта")


class WorkEntityExecutionContractRead(BaseModel):
    """Current Q execution state projected into a project operation."""

    id: UUID
    entity_id: UUID
    operation_id: UUID
    task_id: UUID
    task_number: int
    source: WorkEntityExecutionContractSource
    status: WorkEntityExecutionContractStatus
    task_title: str
    task_status: TaskStatus
    estimated_q: Decimal
    priority: TaskPriority
    assignee_id: UUID | None
    assignee_name: str | None
    planned_starts_at: datetime | None
    planned_due_at: datetime | None
    due_date: datetime | None
    acceptance_mode: AcceptanceMode
    acceptance_state: AcceptanceState
    acceptance_total_count: int
    acceptance_accepted_count: int
    acceptance_required_count: int
    acceptance_required_accepted_count: int
    result_url: str | None
    result_comment: str | None
    created_at: datetime
    can_release: bool


class WorkEntityTaskRead(BaseModel):
    """Executable project task with baseline, forecast, and actual dates."""

    id: UUID
    task_number: int
    entity_id: UUID
    stage_id: UUID | None
    stage_title: str | None
    target_milestone_id: UUID | None
    title: str
    description: str | None
    status: WorkEntityTaskStatus
    priority: WorkEntityTaskPriority
    assignee_id: UUID | None
    assignee_name: str | None
    assignee_email: str | None
    created_by_id: UUID | None
    created_by_name: str | None
    acceptance_criteria: str | None
    next_step: str | None
    waiting_for: str | None
    baseline_starts_at: datetime | None
    baseline_due_at: datetime | None
    forecast_starts_at: datetime | None
    forecast_due_at: datetime | None
    actual_starts_at: datetime | None
    actual_due_at: datetime | None
    introduced_after_baseline: bool
    introduced_at_revision: int | None
    variance_days: int | None
    position: int
    predecessor_ids: list[str]
    can_manage: bool
    can_execute: bool
    can_manage_execution_contract: bool = False
    execution_contract: WorkEntityExecutionContractRead | None = None
    created_at: datetime
    updated_at: datetime


class WorkEntityMilestoneCreate(BaseModel):
    """Create a zero-duration checkpoint with one baseline date."""

    title: str = Field(..., min_length=1, max_length=240)
    description: str | None = None
    status: WorkEntityMilestoneLifecycleStatus = "planned"
    criticality: WorkEntityMilestoneCriticality = "control"
    criticality_reason: str | None = Field(None, max_length=2000)
    acceptance_criteria: str = Field(..., min_length=1, max_length=4000)
    decision_owner_id: UUID | None = None
    stage_id: UUID | None = None
    baseline_at: datetime
    position: int = Field(0, ge=0, le=100000)

    @field_validator("title", "acceptance_criteria", mode="before")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        return _clean_required(value, "Заполните обязательное поле")

    @field_validator("description", "criticality_reason", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def validate_milestone(self) -> "WorkEntityMilestoneCreate":
        if self.criticality in {"key", "critical"} and not self.criticality_reason:
            raise ValueError("Обоснуйте ключевую или критическую контрольную точку")
        return self


class WorkEntityMilestoneUpdate(_PatchModel):
    """Patch milestone semantics; forecast date changes only through reschedule."""

    required_patch_fields = frozenset(
        {
            "title",
            "status",
            "criticality",
            "acceptance_criteria",
            "position",
        }
    )
    title: str | None = Field(None, min_length=1, max_length=240)
    description: str | None = None
    status: WorkEntityMilestoneLifecycleStatus | None = None
    criticality: WorkEntityMilestoneCriticality | None = None
    criticality_reason: str | None = Field(None, max_length=2000)
    acceptance_criteria: str | None = Field(None, min_length=1, max_length=4000)
    decision_owner_id: UUID | None = None
    stage_id: UUID | None = None
    position: int | None = Field(None, ge=0, le=100000)
    change_reason: str | None = Field(None, max_length=2000)

    @field_validator("title", "acceptance_criteria", mode="before")
    @classmethod
    def clean_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value, "Поле не может быть пустым")

    @field_validator(
        "description",
        "criticality_reason",
        "change_reason",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityMilestoneRead(BaseModel):
    id: UUID
    milestone_number: int
    entity_id: UUID
    stage_id: UUID | None
    stage_title: str | None
    title: str
    description: str | None
    status: WorkEntityMilestoneLifecycleStatus
    display_status: WorkEntityMilestoneDisplayStatus
    criticality: WorkEntityMilestoneCriticality
    criticality_reason: str | None
    acceptance_criteria: str
    decision_owner_id: UUID | None
    decision_owner_name: str | None
    created_by_id: UUID | None
    created_by_name: str | None
    baseline_at: datetime
    forecast_at: datetime
    actual_at: datetime | None
    cancelled_at: datetime | None
    variance_days: int
    reschedule_reason: str | None
    reschedule_count: int
    introduced_after_baseline: bool
    introduced_at_revision: int | None
    position: int
    predecessor_ids: list[str]
    can_manage: bool
    created_at: datetime
    updated_at: datetime


class WorkEntityScheduleDependencyCreate(BaseModel):
    predecessor_type: WorkEntityScheduleNodeType
    predecessor_id: UUID
    successor_type: WorkEntityScheduleNodeType
    successor_id: UUID
    dependency_type: WorkEntityScheduleDependencyType = "finish_to_start"
    lag_days: int = Field(0, ge=0, le=3650)
    cascade_on_shift: bool = True

    @model_validator(mode="after")
    def reject_self_reference(self) -> "WorkEntityScheduleDependencyCreate":
        if (
            self.predecessor_type == self.successor_type
            and self.predecessor_id == self.successor_id
        ):
            raise ValueError("Элемент не может зависеть от самого себя")
        return self


class WorkEntityScheduleDependencyRead(BaseModel):
    id: UUID
    entity_id: UUID
    predecessor_type: WorkEntityScheduleNodeType
    predecessor_id: UUID
    predecessor_ref: str
    predecessor_title: str
    successor_type: WorkEntityScheduleNodeType
    successor_id: UUID
    successor_ref: str
    successor_title: str
    dependency_type: WorkEntityScheduleDependencyType
    lag_days: int
    cascade_on_shift: bool
    status: WorkEntityScheduleDependencyStatus
    waiver_reason: str | None
    waived_by_id: UUID | None
    waived_by_name: str | None
    waived_at: datetime | None
    created_by_id: UUID | None
    created_at: datetime


class WorkEntityScheduleDependencyWaiveRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return _clean_required(
            value,
            "Укажите, почему отмена предшественника не блокирует следующий шаг",
        )


class WorkEntityMilestoneRescheduleRequest(BaseModel):
    forecast_at: datetime
    reason: str = Field(..., min_length=3, max_length=2000)
    cascade: bool = True
    expected_revision: int | None = Field(None, ge=0)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return _clean_required(value, "Укажите причину переноса")


class WorkEntityScheduleChangeRead(BaseModel):
    node_type: WorkEntityScheduleNodeType
    node_id: UUID
    node_ref: str
    node_title: str
    status: str
    criticality: str | None = None
    baseline_start_at: datetime | None = None
    baseline_due_at: datetime | None = None
    forecast_start_before: datetime | None = None
    forecast_start_after: datetime | None = None
    forecast_due_before: datetime
    forecast_due_after: datetime
    shift_days: int


class WorkEntityScheduleConflictRead(BaseModel):
    node_type: WorkEntityScheduleNodeType
    node_id: UUID
    node_ref: str
    node_title: str
    code: str
    message: str


class WorkEntityMilestoneReschedulePreviewRead(BaseModel):
    entity_id: UUID
    milestone_id: UUID
    schedule_revision: int
    shift_days: int
    reason: str
    changes: list[WorkEntityScheduleChangeRead]
    conflicts: list[WorkEntityScheduleConflictRead]
    project_forecast_due_before: datetime | None
    project_forecast_due_after: datetime | None
    requires_confirmation: bool = True


class WorkEntityTaskDependencyCreate(WorkEntityScheduleDependencyCreate):
    """Compatibility alias for the typed schedule dependency request."""


class WorkEntityTaskDependencyRead(WorkEntityScheduleDependencyRead):
    """Compatibility alias retained for old imports while the UI migrates."""


class WorkEntityJournalEntryCreate(BaseModel):
    """Human-readable progress note attached to one project task."""

    entry_type: WorkEntityJournalEntryType = "progress"
    body: str = Field(..., min_length=1, max_length=4000)

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str) -> str:
        return _clean_required(value, "Запись журнала не может быть пустой")


class WorkEntityArtifactCreate(BaseModel):
    """Create a shared project-native artifact."""

    artifact_type: WorkEntityArtifactType = "note"
    title: str = Field(..., min_length=1, max_length=240)
    body: str | None = None
    url: str | None = Field(None, max_length=1000)
    task_id: UUID | None = None
    milestone_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required(value, "Название артефакта не может быть пустым")

    @field_validator("body", "url", mode="before")
    @classmethod
    def clean_content(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def validate_content(self) -> "WorkEntityArtifactCreate":
        if not self.body and not self.url:
            raise ValueError("Добавьте текст или ссылку")
        if self.url and not self.url.lower().startswith(("http://", "https://")):
            raise ValueError("Ссылка должна начинаться с http:// или https://")
        if self.task_id and self.milestone_id:
            raise ValueError("Артефакт привязывается либо к задаче, либо к контрольной точке")
        if self.artifact_type == "evidence" and not self.milestone_id:
            raise ValueError(
                "Подтверждение должно быть привязано к контрольной точке"
            )
        return self


class WorkEntityArtifactUpdate(_PatchModel):
    """Patch or archive a shared artifact."""

    required_patch_fields = frozenset({"artifact_type", "title", "status"})
    artifact_type: WorkEntityArtifactType | None = None
    title: str | None = Field(None, min_length=1, max_length=240)
    body: str | None = None
    url: str | None = Field(None, max_length=1000)
    task_id: UUID | None = None
    milestone_id: UUID | None = None
    status: WorkEntityArtifactStatus | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value, "Название артефакта не может быть пустым")

    @field_validator("body", "url", mode="before")
    @classmethod
    def clean_content(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class WorkEntityArtifactRead(BaseModel):
    """Shared artifact visible through entity membership."""

    id: UUID
    entity_id: UUID
    task_id: UUID | None
    task_title: str | None
    milestone_id: UUID | None
    milestone_title: str | None
    artifact_type: WorkEntityArtifactType
    title: str
    body: str | None
    url: str | None
    status: WorkEntityArtifactStatus
    created_by_id: UUID | None
    created_by_name: str | None
    updated_by_id: UUID | None
    updated_by_name: str | None
    archived_at: datetime | None
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class WorkEntityParticipantRead(BaseModel):
    """Owner or explicit member available in the workspace."""

    user_id: UUID
    user_name: str
    user_email: str | None
    role: WorkEntityAccessRole
    can_be_assigned: bool
    open_tasks: int


class WorkEntityWorkspaceRead(BaseModel):
    """Complete project-native workspace payload."""

    entity_id: UUID
    current_access_role: WorkEntityAccessRole
    participants: list[WorkEntityParticipantRead]
    stages: list[WorkEntityStageRead]
    tasks: list[WorkEntityTaskRead]
    milestones: list[WorkEntityMilestoneRead]
    dependencies: list[WorkEntityScheduleDependencyRead]
    artifacts: list[WorkEntityArtifactRead]


class WorkEntityMapNode(BaseModel):
    """One visible node in the project timeline projection."""

    id: str
    node_type: Literal["entity", "task", "milestone", "artifact", "linked_object"]
    ref: str | None = None
    title: str
    status: str | None = None
    criticality: str | None = None
    baseline_starts_at: datetime | None = None
    baseline_due_at: datetime | None = None
    forecast_starts_at: datetime | None = None
    forecast_due_at: datetime | None = None
    actual_at: datetime | None = None
    stage_title: str | None = None
    stage_position: int | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    occurred_at: datetime | None = None
    assignee_name: str | None = None
    parent_id: str | None = None
    accessible: bool = True


class WorkEntityMapEdge(BaseModel):
    """Directed edge used by the project map."""

    id: str
    edge_type: Literal["dependency", "artifact", "link"]
    from_node_id: str
    to_node_id: str


class WorkEntityMapRead(BaseModel):
    """Read-time map projection for temporal and dependency visualization."""

    entity_id: UUID
    range_start: datetime
    range_end: datetime
    nodes: list[WorkEntityMapNode]
    edges: list[WorkEntityMapEdge]
    generated_at: datetime
