"""Схемы прогресса по лигам."""
from pydantic import BaseModel
from uuid import UUID


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


class LeagueHistory(BaseModel):
    """История выполнения плана за один период."""
    period: str
    percent: float

class LeagueEvaluation(BaseModel):
    """Оценка возможной смены лиги для сотрудника."""
    user_id: str
    full_name: str
    current_league: str
    suggested_league: str
    history: list[LeagueHistory]

class LeagueChange(BaseModel):
    """Результат применённого изменения лиги."""
    user_id: str
    full_name: str
    old_league: str
    new_league: str

class ApplyLeagueChangesRequest(BaseModel):
    """Запрос на применение изменений лиг."""
    admin_id: UUID | None = None