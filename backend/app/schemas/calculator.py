"""Схемы запроса/ответа калькулятора оценки (Фаза 2)."""
from uuid import UUID

from pydantic import BaseModel, Field


class CalcItemInput(BaseModel):
    """Одна позиция: catalog_id + количество."""
    catalog_id: UUID
    quantity: int = Field(ge=1, le=50)


class EstimateRequest(BaseModel):
    """Запрос на расчёт стоимости."""
    items: list[CalcItemInput]


class EstimateBreakdownItem(BaseModel):
    """Детализация по одной позиции."""
    catalog_id: UUID
    name: str
    category: str
    complexity: str
    base_cost_q: float
    quantity: int
    subtotal_q: float


class EstimateResponse(BaseModel):
    """Ответ калькулятора."""
    total_q: float
    min_league: str
    breakdown: list[EstimateBreakdownItem]


class CreateTaskFromCalcRequest(BaseModel):
    """Создать задачу из калькулятора."""
    title: str = Field(min_length=5, max_length=500)
    description: str = ""
    priority: str = "medium"
    estimator_id: UUID
    items: list[CalcItemInput]
    tags: list[str] = []
