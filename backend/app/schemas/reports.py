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
