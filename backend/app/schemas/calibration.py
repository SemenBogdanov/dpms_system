"""Схемы калибровочного отчёта."""
from pydantic import BaseModel


class CalibrationItem(BaseModel):
    """Одна операция в отчёте калибровки."""
    catalog_item_id: str
    name: str
    category: str
    complexity: str
    base_cost_q: float
    tasks_count: int
    avg_estimated_q: float
    avg_actual_hours: float | None
    deviation_percent: float | None
    recommendation: str  # "OK" | "Завышена" | "Занижена"


class CalibrationReport(BaseModel):
    """Калибровочный отчёт."""
    period: str
    items: list[CalibrationItem]
    total_tasks_analyzed: int
    overall_accuracy_percent: float


class TeamleadAccuracy(BaseModel):
    """Точность оценок тимлида."""
    user_id: str
    full_name: str
    tasks_evaluated: int
    accuracy_percent: float
    bias: str  # "neutral" | "overestimates" | "underestimates"
    bias_percent: float
    trend: str  # "improving" | "stable" | "declining"
    trend_delta: float
