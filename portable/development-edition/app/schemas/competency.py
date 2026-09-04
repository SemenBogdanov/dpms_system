"""Schemas for competency development module."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CompetencyAccess(BaseModel):
    development_enabled: bool
    constructor_enabled: bool
    is_admin: bool


class CompetencyChoiceRead(BaseModel):
    id: UUID
    text: str

    model_config = {"from_attributes": True}


class CompetencyQuestionRead(BaseModel):
    id: UUID
    text: str
    question_type: str
    position: int
    choices: list[CompetencyChoiceRead]

    model_config = {"from_attributes": True}


class CompetencySummary(BaseModel):
    id: UUID
    title: str
    description: str | None
    source: str
    department: str | None = None
    visibility: Literal["assigned", "all"] | str = "assigned"
    created_by_id: UUID | None = None
    questions_count: int
    status: str
    is_required_builtin: bool = False
    assigned_count: int = 0
    attempts_count: int = 0
    completed_count: int = 0
    can_edit_content: bool = True
    active_attempt_id: UUID | None = None
    latest_attempt_id: UUID | None = None
    score_ib: int | None = None
    score_ich: int | None = None
    is_overused: bool = False
    completed_at: datetime | None = None
    retake_allowed_at: datetime | None = None


class CompetencyListResponse(BaseModel):
    competencies: list[CompetencySummary]


class CompetencyAttemptStartResponse(BaseModel):
    attempt_id: UUID
    competency_id: UUID
    competency_title: str
    competency_description: str | None
    status: str
    questions: list[CompetencyQuestionRead]


class CompetencyAnswerRequest(BaseModel):
    question_id: UUID
    choice_id: UUID | None = None
    time_spent_seconds: int | None = Field(None, ge=0, le=3600)
    timed_out: bool = False

    @model_validator(mode="after")
    def require_choice_or_timeout(self):
        if self.choice_id is None and not self.timed_out:
            raise ValueError("choice_id_required_unless_timed_out")
        return self


class CompetencyAnswerResponse(BaseModel):
    saved: bool
    answered_count: int
    total_questions: int


class CompetencyResultResponse(BaseModel):
    attempt_id: UUID
    competency_id: UUID
    competency_title: str
    status: str
    score_ib: int | None
    score_ich: int | None
    is_overused: bool
    interpretation_text: str | None
    avg_time_per_question: float | None
    completed_at: datetime | None
    retake_allowed_at: datetime | None


class DevelopmentPlanItemCreate(BaseModel):
    competency_id: UUID | None = None
    source_attempt_id: UUID | None = None
    goal: str = Field(..., min_length=3, max_length=255)
    action_text: str = Field(..., min_length=3)
    expected_result: str | None = None
    due_at: datetime | None = None


class DevelopmentPlanItemUpdate(BaseModel):
    competency_id: UUID | None = None
    source_attempt_id: UUID | None = None
    goal: str | None = Field(None, min_length=3, max_length=255)
    action_text: str | None = Field(None, min_length=3)
    expected_result: str | None = None
    due_at: datetime | None = None
    status: str | None = None


class DevelopmentPlanItemRead(BaseModel):
    id: UUID
    competency_id: UUID | None
    source_attempt_id: UUID | None
    competency_title: str | None = None
    goal: str
    action_text: str
    expected_result: str | None
    due_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


class DevelopmentPlanPromptResponse(BaseModel):
    prompt: str
    completed_assessments_count: int
    generated_at: datetime


class DevelopmentPlanImportRequest(BaseModel):
    raw_text: str = Field(..., min_length=3)


class DevelopmentPlanImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    warnings: list[str] = Field(default_factory=list)
    items: list[DevelopmentPlanItemRead]


class DevelopmentPlanReportAssessment(BaseModel):
    attempt_id: UUID
    competency_id: UUID
    competency_title: str
    source: str
    score_ib: int | None = None
    score_ich: int | None = None
    is_overused: bool = False
    interpretation_text: str | None = None
    completed_at: datetime | None = None
    retake_allowed_at: datetime | None = None


class DevelopmentPlanRoadmapPoint(BaseModel):
    id: UUID | None = None
    title: str
    description: str | None = None
    status: str
    due_at: datetime | None = None
    completed_at: datetime | None = None


class DevelopmentPlanReportResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    completed_assessments_count: int
    plan_total: int
    plan_planned: int
    plan_in_progress: int
    plan_done: int
    plan_cancelled: int
    progress_percent: int
    assessments: list[DevelopmentPlanReportAssessment]
    roadmap: list[DevelopmentPlanRoadmapPoint]


class DevelopmentPlanAdminSummaryUser(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    completed_assessments_count: int
    plan_total: int
    plan_done: int
    plan_in_progress: int
    progress_percent: int
    last_activity_at: datetime | None = None


class DevelopmentPlanAdminSummaryResponse(BaseModel):
    total_enabled_users: int
    users_with_completed_assessments: int
    completed_assessments_count: int
    users_with_plan: int
    plan_total: int
    plan_planned: int
    plan_in_progress: int
    plan_done: int
    plan_cancelled: int
    users: list[DevelopmentPlanAdminSummaryUser]


class ConstructorChoiceCreate(BaseModel):
    text: str = Field(..., min_length=1)
    value: int = Field(..., ge=1, le=5)

    @field_validator("text")
    @classmethod
    def strip_non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty_choice_text")
        return value


class ConstructorQuestionCreate(BaseModel):
    text: str = Field(..., min_length=3)
    question_type: str = "custom"
    choices: list[ConstructorChoiceCreate] = Field(..., min_length=2, max_length=10)

    @field_validator("text")
    @classmethod
    def strip_question_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("question_text_too_short")
        return value


class ConstructorInterpretationCreate(BaseModel):
    min_score_ib: int = Field(..., ge=0)
    max_score_ib: int = Field(..., ge=0)
    text: str = Field(..., min_length=3)
    overuse_modifier_text: str | None = None
    recommendation_text: str | None = None

    @field_validator("text")
    @classmethod
    def strip_interpretation_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("interpretation_text_too_short")
        return value

    @model_validator(mode="after")
    def validate_range(self):
        if self.max_score_ib < self.min_score_ib:
            raise ValueError("invalid_interpretation_range")
        return self


class ConstructorCompetencyCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = None
    department: str | None = Field(None, max_length=255)
    visibility: Literal["assigned", "all"] = "assigned"
    questions: list[ConstructorQuestionCreate] = Field(..., min_length=1, max_length=100)
    interpretations: list[ConstructorInterpretationCreate] = Field(..., min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("competency_title_too_short")
        return value


class ConstructorCompetencyUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = None
    department: str | None = Field(None, max_length=255)
    visibility: Literal["assigned", "all"] | None = None
    questions: list[ConstructorQuestionCreate] | None = Field(None, min_length=1, max_length=100)
    interpretations: list[ConstructorInterpretationCreate] | None = Field(None, min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 3:
            raise ValueError("competency_title_too_short")
        return value


class ConstructorChoiceRead(BaseModel):
    id: UUID
    text: str
    value: int
    position: int

    model_config = {"from_attributes": True}


class ConstructorQuestionRead(BaseModel):
    id: UUID
    text: str
    question_type: str
    position: int
    choices: list[ConstructorChoiceRead]

    model_config = {"from_attributes": True}


class ConstructorInterpretationRead(BaseModel):
    id: UUID
    min_score_ib: int
    max_score_ib: int
    text: str
    overuse_modifier_text: str | None = None
    recommendation_text: str | None = None

    model_config = {"from_attributes": True}


class ConstructorCompetencyDetail(CompetencySummary):
    questions: list[ConstructorQuestionRead]
    interpretations: list[ConstructorInterpretationRead]


class ConstructorAssignmentCreate(BaseModel):
    target_user_id: UUID
    due_at: datetime | None = None


class ConstructorAssignmentSet(BaseModel):
    target_user_ids: list[UUID] = Field(default_factory=list)
    visibility: Literal["assigned", "all"] | None = None


class ConstructorAssignmentRead(BaseModel):
    id: UUID
    competency_id: UUID
    target_user_id: UUID
    status: str
    link: str
    due_at: datetime | None
    created_at: datetime


class ConstructorReportRow(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    assignment_status: str | None = None
    attempt_status: str
    score_ib: int | None = None
    score_ich: int | None = None
    is_overused: bool = False
    completed_at: datetime | None = None
    retake_allowed_at: datetime | None = None
    attention_points: list[str] = Field(default_factory=list)
    interpretation_text: str | None = None


class ConstructorReportResponse(BaseModel):
    competency_id: UUID
    title: str
    visibility: str
    assigned_count: int
    completed_count: int
    rows: list[ConstructorReportRow]
