"""Схемы аналитических данных (дашборд)."""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

class CapacityGauge(BaseModel):
    """Метрика «Стакан»: загрузка vs ёмкость."""
    capacity: Decimal  # сумма mpw активных пользователей
    load: Decimal  # сумма estimated_q задач in_queue + in_progress + review
    utilization: float  # load / capacity * 100
    status: str  # 'green' | 'yellow' | 'red'


class UserProgress(BaseModel):
    """Прогресс пользователя: earned vs target."""
    earned: float
    target: float
    percent: float
    karma: float


class TeamMemberSummary(BaseModel):
    """Сводка по одному сотруднику для дашборда."""
    id: UUID
    full_name: str
    league: str
    mpw: int
    earned: float
    percent: float
    karma: float
    in_progress_q: float
    is_at_risk: bool
    quality_score: float
    has_overdue: bool


class TeamSummary(BaseModel):
    """Сводка по команде (группировка по лигам)."""
    by_league: dict[str, list[TeamMemberSummary]]
    total_capacity: float
    total_load: float
    total_earned: float
    utilization: float


class PeriodStats(BaseModel):
    """Агрегаты текущего месяца для дашборда руководителя."""
    period: str  # 'YYYY-MM'
    tasks_created: int
    tasks_completed: int
    total_q_earned: float
    avg_completion_time_hours: float | None


class BurndownPoint(BaseModel):
    """Одна точка графика burn-down."""
    day: str  # "YYYY-MM-DD"
    ideal: float
    actual: float | None = None


class BurndownData(BaseModel):
    """Данные для графика burn-down текущего месяца."""
    period: str
    total_capacity: float
    working_days: int
    points: list[BurndownPoint]
