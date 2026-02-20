"""Схемы для задач."""
from datetime import datetime, timezone
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
    due_date: datetime | None = None
    sla_hours: int | None = None
    is_overdue: bool = False
    parent_task_id: UUID | None = None
    deadline_zone: str | None = None  # "green" | "yellow" | "red" | None
    tags: list[str] = Field(default_factory=list)
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


class SetDueDateRequest(BaseModel):
    """Запрос на установку дедлайна задачи (доступен тимлиду/админу)."""

    due_date: datetime


class CreateBugfixRequest(BaseModel):
    """Создание гарантийного баг-фикса по принятой задаче."""

    parent_task_id: UUID
    title: str = Field(..., max_length=500)
    description: str | None = None


def compute_deadline_zone(task) -> str | None:
    """
    Вычислить зону дедлайна:
    - None: нет дедлайна
    - red: просрочено
    - yellow: осталось <= 50% времени (между started_at и due_date)
    - green: остальное
    """
    if getattr(task, "due_date", None) is None:
        return None
    due = task.due_date
    now = datetime.now(timezone.utc)
    if now > due:
        return "red"
    started_at = getattr(task, "started_at", None)
    if started_at:
        total = (due - started_at).total_seconds()
        remaining = (due - now).total_seconds()
        if total > 0 and remaining / total <= 0.5:
            return "yellow"
    return "green"
