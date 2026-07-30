"""Outcome-oriented project cockpit schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Дата должна содержать часовой пояс")
    return value


class CockpitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidedProjectMember(CockpitModel):
    user_id: UUID
    role: Literal["participant", "editor", "viewer"] = "participant"


class GuidedProjectMilestone(CockpitModel):
    title: str = Field(..., min_length=1, max_length=240)
    acceptance_criteria: str = Field(..., min_length=1, max_length=4000)
    baseline_at: datetime
    decision_owner_id: UUID | None = None
    criticality: Literal["control", "key", "critical"] = "control"
    criticality_reason: str | None = Field(None, max_length=4000)

    @field_validator("title", "acceptance_criteria", mode="before")
    @classmethod
    def clean_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("baseline_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)

    @model_validator(mode="after")
    def validate_criticality(self) -> "GuidedProjectMilestone":
        if self.criticality in {"key", "critical"} and not (
            self.criticality_reason or ""
        ).strip():
            raise ValueError(
                "Для ключевой или критической точки нужна причина"
            )
        return self


class GuidedProjectTask(CockpitModel):
    title: str = Field(..., min_length=1, max_length=240)
    acceptance_criteria: str = Field(..., min_length=1, max_length=4000)
    baseline_starts_at: datetime
    baseline_due_at: datetime
    assignee_id: UUID | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    target_milestone_index: int = Field(..., ge=0, le=199)

    @field_validator("title", "acceptance_criteria", mode="before")
    @classmethod
    def clean_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("baseline_starts_at", "baseline_due_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)

    @model_validator(mode="after")
    def validate_dates(self) -> "GuidedProjectTask":
        if self.baseline_due_at <= self.baseline_starts_at:
            raise ValueError("Срок работы должен быть позже ее начала")
        return self


class GuidedProjectCreate(CockpitModel):
    title: str = Field(..., min_length=1, max_length=240)
    outcome_statement: str = Field(..., min_length=1, max_length=8000)
    success_criteria: str = Field(..., min_length=1, max_length=8000)
    constraints: str | None = Field(None, max_length=8000)
    starts_at: datetime
    due_at: datetime
    members: list[GuidedProjectMember] = Field(default_factory=list, max_length=100)
    milestones: list[GuidedProjectMilestone] = Field(
        ...,
        min_length=1,
        max_length=200,
    )
    tasks: list[GuidedProjectTask] = Field(default_factory=list, max_length=500)

    @field_validator(
        "title",
        "outcome_statement",
        "success_criteria",
        mode="before",
    )
    @classmethod
    def clean_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("starts_at", "due_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)

    @model_validator(mode="after")
    def validate_plan(self) -> "GuidedProjectCreate":
        if self.due_at <= self.starts_at:
            raise ValueError("Срок проекта должен быть позже даты начала")
        member_ids = [member.user_id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Участник не должен повторяться")
        previous_at: datetime | None = None
        for milestone in self.milestones:
            if not self.starts_at <= milestone.baseline_at <= self.due_at:
                raise ValueError(
                    "Контрольные точки должны находиться внутри срока проекта"
                )
            if previous_at and milestone.baseline_at <= previous_at:
                raise ValueError(
                    "Контрольные точки должны идти в хронологическом порядке"
                )
            previous_at = milestone.baseline_at
        for task in self.tasks:
            if task.target_milestone_index >= len(self.milestones):
                raise ValueError("Для работы выбрана неизвестная контрольная точка")
            if (
                task.baseline_starts_at < self.starts_at
                or task.baseline_due_at > self.due_at
            ):
                raise ValueError("Работы должны находиться внутри срока проекта")
            target = self.milestones[task.target_milestone_index]
            if task.baseline_due_at > target.baseline_at:
                raise ValueError(
                    "Работа должна завершиться не позже связанной контрольной точки"
                )
        return self


class GuidedProjectCreated(CockpitModel):
    entity_id: UUID
    schedule_revision: int


class ProjectWorkCreate(CockpitModel):
    title: str = Field(..., min_length=1, max_length=240)
    acceptance_criteria: str = Field(..., min_length=1, max_length=4000)
    baseline_starts_at: datetime
    baseline_due_at: datetime
    assignee_id: UUID | None = None
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    target_milestone_id: UUID

    @field_validator("title", "acceptance_criteria", mode="before")
    @classmethod
    def clean_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("baseline_starts_at", "baseline_due_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)

    @model_validator(mode="after")
    def validate_dates(self) -> "ProjectWorkCreate":
        if self.baseline_due_at <= self.baseline_starts_at:
            raise ValueError("Срок работы должен быть позже ее начала")
        return self


class ProjectWorkCreated(CockpitModel):
    task_id: UUID
    schedule_revision: int


class ProjectDeadlineChangeRequest(CockpitModel):
    target_due_at: datetime
    reason: str = Field(..., min_length=5, max_length=4000)
    expected_revision: int = Field(..., ge=0)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 5:
            raise ValueError("Укажите содержательную причину изменения срока")
        return cleaned

    @field_validator("target_due_at")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)


class ProjectDeadlineConflict(CockpitModel):
    node_type: Literal["task", "milestone"]
    node_id: UUID
    node_ref: str
    title: str
    forecast_due_at: datetime
    message: str


class ProjectDeadlineChangePreview(CockpitModel):
    entity_id: UUID
    schedule_revision: int
    baseline_due_at: datetime | None
    target_due_before: datetime | None
    target_due_after: datetime
    forecast_due_at: datetime | None
    shift_days: int
    conflicts: list[ProjectDeadlineConflict]
    can_apply: bool


class ProjectCharterChangeRequest(CockpitModel):
    outcome_statement: str | None = Field(None, max_length=8000)
    success_criteria: str | None = Field(None, max_length=8000)
    constraints: str | None = Field(None, max_length=8000)
    reason: str = Field(..., min_length=5, max_length=4000)
    expected_revision: int = Field(..., ge=0)

    @field_validator("outcome_statement", "success_criteria", mode="before")
    @classmethod
    def clean_required_change(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Результат и критерии успеха нельзя очистить")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Результат и критерии успеха нельзя очистить")
        return cleaned

    @field_validator("constraints", mode="before")
    @classmethod
    def clean_constraints(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 5:
            raise ValueError("Укажите содержательную причину изменения")
        return cleaned

    @model_validator(mode="after")
    def validate_change(self) -> "ProjectCharterChangeRequest":
        change_fields = {
            "outcome_statement",
            "success_criteria",
            "constraints",
        }
        if not change_fields & self.model_fields_set:
            raise ValueError("Укажите хотя бы одно изменение паспорта проекта")
        return self


class ProjectCharterFieldChange(CockpitModel):
    field: Literal[
        "outcome_statement",
        "success_criteria",
        "constraints",
    ]
    before: str | None
    after: str | None


class ProjectCharterChangePreview(CockpitModel):
    entity_id: UUID
    schedule_revision: int
    baseline_outcome_statement: str | None
    baseline_success_criteria: str | None
    baseline_constraints: str | None
    changes: list[ProjectCharterFieldChange]
    can_apply: bool


class ProjectDecisionCreate(CockpitModel):
    decided_at: datetime
    title: str = Field(..., min_length=1, max_length=240)
    decision: str = Field(..., min_length=1, max_length=8000)
    reason: str | None = Field(None, max_length=4000)
    participants: str | None = Field(None, max_length=4000)
    follow_up: str | None = Field(None, max_length=8000)
    owner_id: UUID | None = None
    due_at: datetime | None = None

    @field_validator("title", "decision", mode="before")
    @classmethod
    def clean_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым")
        return cleaned

    @field_validator("decided_at", "due_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        return _timezone_aware(value) if value is not None else None
