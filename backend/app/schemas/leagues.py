"""Схемы прогресса по лигам."""
from pydantic import BaseModel


class CriteriaPeriod(BaseModel):
    """Помесячная детализация критерия."""
    period: str  # "2026-01"
    value: float | None  # 92.0 (percent) или количество задач
    met: bool
    current: bool = False  # Текущий месяц (ещё не закрыт)


class LeagueCriterion(BaseModel):
    """Один критерий перехода в следующую лигу."""
    name: str
    description: str
    required: int
    completed: int
    met: bool
    progress_percent: float
    details: list[CriteriaPeriod]


class LeagueProgress(BaseModel):
    """Детальный прогресс пользователя к следующей лиге."""
    user_id: str
    current_league: str
    next_league: str | None
    at_max: bool
    criteria: list[LeagueCriterion]
    overall_progress: float
    message: str
