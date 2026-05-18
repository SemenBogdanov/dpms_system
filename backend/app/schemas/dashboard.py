"""Схемы аналитических данных (дашборд)."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CapacityGauge(BaseModel):
    """Метрика «Стакан»: загрузка vs ёмкость."""
    capacity: Decimal  # сумма effective target активных пользователей
    load: Decimal  # сумма estimated_q задач in_queue + in_progress + review
    utilization: float  # load / capacity * 100
    status: str  # 'green' | 'yellow' | 'red'


class UserProgress(BaseModel):
    """Прогресс пользователя: earned vs effective target."""
    earned: float
    target: float
    full_target: float = 0
    percent: float
    karma: float
    is_new_employee: bool = False
    onboarding_active: bool = False
    onboarding_until: datetime | None = None
    plan_started_at: datetime | None = None
    adjustment_reasons: list[str] = Field(default_factory=list)


class TeamMemberSummary(BaseModel):
    """Сводка по одному сотруднику для дашборда."""
    id: UUID
    full_name: str
    league: str
    mpw: int
    effective_mpw: float = 0
    earned: float
    percent: float
    karma: float
    in_progress_q: float
    is_at_risk: bool
    quality_score: float
    has_overdue: bool
    is_new_employee: bool = False
    onboarding_active: bool = False
    onboarding_until: datetime | None = None
    adjustment_reasons: list[str] = Field(default_factory=list)


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


class RunRate(BaseModel):
    """Прогноз выполнения плана (Run Rate)."""
    rate_daily: float          # темп Q/день
    projected: float           # прогноз Q на конец месяца
    mpw: float                 # effective plan
    full_mpw: float = 0         # full monthly plan
    run_rate_percent: float    # projected / mpw * 100
    required_rate: float | None  # нужный темп (None если план выполнен)
    status: str                # on_track | slightly_behind | at_risk | critical
    days_elapsed: int
    days_total: int
    days_remaining: int
    earned: float              # текущий wallet_main
    is_new_employee: bool = False
    onboarding_active: bool = False
    onboarding_until: datetime | None = None
