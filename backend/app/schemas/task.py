"""Схемы для задач."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.task import TaskPriority, TaskStatus, TaskType
from app.models.catalog import Complexity
from app.models.user import League


class TaskBase(BaseModel):
    """Базовая схема задачи."""
    title: str = Field(..., max_length=500)
    description: str | None = None
    task_type: TaskType
    complexity: Complexity
    estimated_q: Decimal = Field(default=Decimal("0"), ge=0)
    priority: TaskPriority = TaskPriority.medium
    min_league: League


class TaskCreate(TaskBase):
    """Создание задачи (оценка может быть 0, потом через калькулятор)."""
    status: TaskStatus = TaskStatus.new
    estimator_id: UUID
    estimation_details: dict | None = None


class TaskUpdate(BaseModel):
    """Обновление задачи (описание, приоритет)."""
    title: str | None = Field(None, max_length=500)
    description: str | None = None
    priority: TaskPriority | None = None


class TaskRead(TaskBase):
    """Чтение задачи."""
    id: UUID
    status: TaskStatus
    assignee_id: UUID | None = None
    estimator_id: UUID
    validator_id: UUID | None = None
    estimation_details: dict | None = None
    result_url: str | None = None
    rejection_comment: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    validated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskExportRow(BaseModel):
    """Строка экспорта задач."""
    title: str
    category: str
    complexity: str
    estimated_q: float
    assignee_name: str
    started_at: str | None
    completed_at: str | None
    duration_hours: float | None
    validator_name: str | None
    status: str


class TasksExport(BaseModel):
    """Экспорт задач за период."""
    period: str
    rows: list[TaskExportRow]
    total_tasks: int
    total_q: float
