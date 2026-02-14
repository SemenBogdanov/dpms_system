"""Схемы для оценки и применения изменений лиг."""
from uuid import UUID

from pydantic import BaseModel


class ApplyLeagueChangesRequest(BaseModel):
    """Запрос на применение изменений лиг (только admin)."""
    admin_id: UUID


class LeagueEvaluation(BaseModel):
    """Оценка смены лиги для одного пользователя."""
    user_id: str
    full_name: str
    current_league: str
    suggested_league: str
    reason: str
    eligible: bool
    history: list[dict]  # [{"period": "2026-01", "percent": 92.0}, ...]


class LeagueChange(BaseModel):
    """Фактическое изменение лиги после применения."""
    user_id: str
    full_name: str
    old_league: str
    new_league: str
    reason: str
