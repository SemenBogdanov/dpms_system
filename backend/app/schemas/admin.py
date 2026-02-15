"""Схемы админки: rollover, история периодов."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class RolloverRequest(BaseModel):
    """Запрос на закрытие периода (только admin). admin_id опционален (из JWT)."""
    admin_id: UUID | None = None


class RolloverResponse(BaseModel):
    """Результат закрытия периода."""
    period: str
    users_processed: int
    total_main_reset: float
    total_karma_burned: float


class PeriodSnapshotResponse(BaseModel):
    """Снимок сотрудника за период."""
    id: UUID
    user_id: UUID
    period: str
    mpw: int
    earned_main: Decimal
    earned_karma: Decimal
    tasks_completed: int
    league: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PeriodHistoryItem(BaseModel):
    """Один период в истории (агрегат по всем снимкам периода)."""
    period: str
    closed_at: datetime | None
    users_count: int
    total_main_reset: float
    total_karma_burned: float
