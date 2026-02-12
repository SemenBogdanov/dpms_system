"""Схемы запроса/ответа калькулятора оценки."""
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import League


class CalculatorItem(BaseModel):
    """Одна позиция в запросе калькулятора (catalog_id + количество)."""
    catalog_id: UUID
    quantity: int = Field(default=1, ge=1)


class CalculatorRequest(BaseModel):
    """Запрос на расчёт стоимости задачи."""
    items: list[CalculatorItem]
    complexity_multiplier: float = Field(default=1.0, ge=0.5, le=3.0)
    urgency_multiplier: float = Field(default=1.0, ge=1.0, le=2.0)


class CalculatorBreakdownItem(BaseModel):
    """Детализация по одной позиции в ответе."""
    catalog_id: UUID
    name: str
    base_cost_q: Decimal
    quantity: int
    subtotal_q: Decimal


class CalculatorResponse(BaseModel):
    """Ответ калькулятора: итоговая Q и детализация."""
    total_q: Decimal
    breakdown: list[CalculatorBreakdownItem]
    min_league: League
