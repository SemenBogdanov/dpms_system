"""Схемы аналитических данных (дашборд)."""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.user import League


class CapacityGauge(BaseModel):
    """Метрика «Стакан»: загрузка vs ёмкость."""
    capacity: Decimal  # сумма mpw активных пользователей
    load: Decimal  # сумма estimated_q задач in_queue + in_progress + review
    utilization: float  # load / capacity * 100
    status: str  # 'green' | 'yellow' | 'red'


class UserProgress(BaseModel):
    """Прогресс пользователя: earned vs target."""
    earned: Decimal
    target: Decimal
    percent: float
    karma: Decimal


class TeamMemberSummary(BaseModel):
    """Сводка по одному сотруднику для дашборда."""
    user_id: UUID
    full_name: str
    league: League
    earned: Decimal
    target: Decimal
    percent: float
    karma: Decimal


class TeamSummary(BaseModel):
    """Сводка по команде (группировка по лигам)."""
    by_league: dict[str, list[TeamMemberSummary]]
    capacity: Decimal
    total_earned: Decimal
    total_load: Decimal
