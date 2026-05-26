"""Schemas for audit/activity observability."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ActivityEventRead(BaseModel):
    id: UUID
    actor_id: UUID
    actor_name: str
    event_type: str
    task_id: UUID | None = None
    task_number: int | None = None
    task_title: str | None = None
    metadata: dict | None = None
    occurred_at: datetime


class ActivityEventListResponse(BaseModel):
    items: list[ActivityEventRead]
    total: int
    limit: int


class FocusActivitySummary(BaseModel):
    total_focus_seconds: int
    total_focus_hours: float
    focus_start_count: int
    focus_pause_count: int
    focus_auto_pause_count: int
    focused_tasks_count: int
    avg_pauses_per_task: float


class EmployeeSummaryTask(BaseModel):
    id: UUID
    task_number: int
    title: str
    status: str
    priority: str
    task_type: str
    estimated_q: float
    started_at: datetime | None = None
    completed_at: datetime | None = None
    validated_at: datetime | None = None
    active_seconds: int
    focus_sessions: int = 0
    pause_count: int = 0
    auto_pause_count: int = 0
    result_url: str | None = None


class EmployeePeriodSummary(BaseModel):
    user_id: UUID
    full_name: str
    role: str
    league: str
    start_date: str
    end_date: str
    plan_q: float
    completed_q: float
    efficiency_percent: float
    completed_tasks_count: int
    in_progress_tasks_count: int
    review_tasks_count: int
    rejected_tasks_count: int
    absence_working_days: int = 0
    focus: FocusActivitySummary
    completed_tasks: list[EmployeeSummaryTask] = Field(default_factory=list)
    in_progress_tasks: list[EmployeeSummaryTask] = Field(default_factory=list)
    review_tasks: list[EmployeeSummaryTask] = Field(default_factory=list)
    rejected_tasks: list[EmployeeSummaryTask] = Field(default_factory=list)
    recent_activity: list[ActivityEventRead] = Field(default_factory=list)
