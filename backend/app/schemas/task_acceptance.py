"""Schemas for structured task acceptance plans and criterion reviews."""
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


AcceptanceMode = Literal["full", "criteria"]
AcceptanceState = Literal["none", "submitted", "partially_accepted", "returned", "accepted"]
AcceptanceCriterionKind = Literal["required", "optional", "quality_gate"]
AcceptanceCriterionStatus = Literal[
    "pending",
    "submitted",
    "accepted",
    "returned",
    "not_applicable",
]


class AcceptanceCriterionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    kind: AcceptanceCriterionKind = "required"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Критерий должен содержать не менее двух символов")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


def validate_acceptance_plan(
    mode: AcceptanceMode,
    criteria: list[AcceptanceCriterionCreate],
) -> None:
    if mode == "full" and criteria:
        raise ValueError("Для приемки целиком отдельные критерии не задаются")
    if mode == "criteria":
        if not criteria:
            raise ValueError("Добавьте хотя бы один критерий приемки")
        if not any(item.kind in {"required", "quality_gate"} for item in criteria):
            raise ValueError("Нужен хотя бы один обязательный критерий или quality gate")
    normalized_titles = [item.title.casefold() for item in criteria]
    if len(normalized_titles) != len(set(normalized_titles)):
        raise ValueError("Критерии приемки не должны повторяться")


class AcceptancePlanUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    mode: AcceptanceMode
    acceptance_owner_id: UUID | None = None
    criteria: list[AcceptanceCriterionCreate] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_plan(self):
        validate_acceptance_plan(self.mode, self.criteria)
        return self


class AcceptanceCriterionEvidence(BaseModel):
    criterion_id: UUID
    evidence_comment: str | None = Field(default=None, max_length=4000)
    evidence_url: str | None = Field(default=None, max_length=1000)

    @field_validator("evidence_comment", "evidence_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_safe_evidence(self):
        if not self.evidence_comment and not self.evidence_url:
            raise ValueError("Добавьте комментарий или ссылку на подтверждение")
        if self.evidence_url:
            parsed = urlparse(self.evidence_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Ссылка на подтверждение должна начинаться с http:// или https://")
        return self


class AcceptanceCriteriaSubmitRequest(BaseModel):
    items: list[AcceptanceCriterionEvidence] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_criteria(self):
        ids = [item.criterion_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Критерий нельзя отправить дважды в одном запросе")
        return self


class AcceptanceCriterionDecision(BaseModel):
    criterion_id: UUID
    approved: bool
    comment: str | None = Field(default=None, max_length=4000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_return_comment(self):
        if not self.approved and not self.comment:
            raise ValueError("При возврате критерия комментарий обязателен")
        return self


class AcceptanceCriteriaReviewRequest(BaseModel):
    decisions: list[AcceptanceCriterionDecision] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_criteria(self):
        ids = [item.criterion_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("Критерий нельзя проверить дважды в одном запросе")
        return self


class AcceptanceCriterionEventRead(BaseModel):
    id: UUID
    actor_id: UUID | None
    actor_name: str | None
    event_type: Literal["submitted", "accepted", "returned", "not_applicable"]
    from_status: str | None
    to_status: str
    comment: str | None
    evidence_url: str | None
    acceptance_revision: int
    created_at: datetime


class AcceptanceCriterionRead(BaseModel):
    id: UUID
    task_id: UUID
    position: int
    title: str
    description: str | None
    kind: AcceptanceCriterionKind
    status: AcceptanceCriterionStatus
    baseline_revision: int
    evidence_comment: str | None
    evidence_url: str | None
    reviewer_comment: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    return_count: int
    events: list[AcceptanceCriterionEventRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TaskAcceptanceRead(BaseModel):
    task_id: UUID
    mode: AcceptanceMode
    state: AcceptanceState
    revision: int
    owner_id: UUID | None
    owner_name: str | None
    locked: bool
    can_manage_plan: bool
    can_submit: bool
    can_review: bool
    criteria: list[AcceptanceCriterionRead]
