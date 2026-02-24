"""Схемы калибровочного отчёта."""
from pydantic import BaseModel


class CalibrationItem(BaseModel):
    """Одна операция в отчёте калибровки (старый формат для reports)."""
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
    """Калибровочный отчёт (старый формат для reports)."""
    period: str
    items: list[CalibrationItem]
    total_tasks_analyzed: int
    overall_accuracy_percent: float


# --- Новый формат калибровки (по задачам, оценщикам, популярность) ---

class TaskCalibration(BaseModel):
    """Калибровка по одной задаче."""
    task_id: str
    title: str
    task_type: str
    complexity: str
    estimated_q: float
    actual_hours: float
    deviation_pct: int
    assignee_name: str
    estimator_name: str
    tags: list[str]


class EstimatorCalibration(BaseModel):
    """Калибровка по оценщику."""
    estimator_name: str
    tasks_count: int
    avg_deviation_pct: int
    accuracy_pct: int
    bias: str  # "точно" | "завышает" | "занижает"
    overestimates: int
    underestimates: int


class WidgetPopularityItem(BaseModel):
    """Популярность операции каталога."""
    name: str
    tasks_count: int
    usage_percent: int


class CalibrationReportNew(BaseModel):
    """Новый калибровочный отчёт: задачи, оценщики, популярность операций."""
    period: str
    total_tasks_analyzed: int
    overall_accuracy_pct: int
    avg_deviation_pct: int
    task_calibrations: list[TaskCalibration]
    estimator_calibrations: list[EstimatorCalibration]
    widget_popularity: list[WidgetPopularityItem]
    total_tasks_with_breakdown: int


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
