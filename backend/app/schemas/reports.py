"""Схемы отчётов за период."""
from pydantic import BaseModel


class PerformerSummary(BaseModel):
    full_name: str
    league: str
    percent: float
    tasks_completed: int


class TasksOverview(BaseModel):
    total_created: int
    total_completed: int
    avg_time_hours: float | None
    by_category: dict[str, int]


class ShopActivity(BaseModel):
    total_purchases: int
    total_karma_spent: float
    popular_items: list[dict]


class CalibrationSummary(BaseModel):
    accurate_count: int
    overestimated_count: int
    underestimated_count: int


class PeriodReport(BaseModel):
    period: str
    generated_at: str
    team_members: list[PerformerSummary]
    top_performers: list[PerformerSummary]
    underperformers: list[PerformerSummary]
    tasks_overview: TasksOverview
    shop_activity: ShopActivity
    calibration_summary: CalibrationSummary
    total_capacity: float
    total_earned: float
    utilization_percent: float


class EmployeeScorecardRow(BaseModel):
    rank: int
    user_id: str
    full_name: str
    role: str
    league: str
    plan_q: float
    completed_q: float
    efficiency_percent: float
    completed_tasks_count: int
    first_pass_tasks_count: int
    first_pass_rate: float
    rejection_events_count: int
    active_overdue_count: int
    completed_late_count: int
    high_priority_completed_count: int
    critical_completed_count: int
    focus_hours: float
    focus_start_count: int
    focus_pause_count: int
    avg_pauses_per_task: float
    focus_task_coverage_percent: float
    quality_score: float
    efficiency_score: float
    acceptance_score: float
    reliability_score: float
    focus_score: float
    score: float


class EmployeeScorecardResponse(BaseModel):
    start_date: str
    end_date: str
    generated_at: str
    weights: dict[str, float]
    rows: list[EmployeeScorecardRow]
