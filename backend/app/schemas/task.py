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
    """Обновление заявки без изменения оценки Q и workflow-статуса."""
    title: str | None = Field(None, max_length=500)
    description: str | None = None
    priority: TaskPriority | None = None
    tags: list[str] | None = None


class TaskRead(TaskBase):
    """Чтение задачи."""
    id: UUID
    task_number: int
    status: TaskStatus
    assignee_id: UUID | None = None
    estimator_id: UUID
    validator_id: UUID | None = None
    estimation_details: dict | None = None
    result_url: str | None = None
    result_comment: str | None = None
    brief_rating: int | None = None
    brief_feedback: str | None = None
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
    rejection_count: int = 0
    focus_started_at: datetime | None = None
    active_seconds: int = 0
    active_hours: float = 0.0
    is_focused: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskAttachmentRead(BaseModel):
    """Метаданные вложения задачи."""

    id: UUID
    task_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class FocusResponse(BaseModel):
    task_id: UUID
    action: str  # "focused" | "paused"
    active_seconds: int
    active_hours: float
    paused_task_id: UUID | None = None


class TimeCorrection(BaseModel):
    task_id: UUID
    new_active_seconds: int
    reason: str


class FocusStatus(BaseModel):
    user_id: UUID
    full_name: str
    league: str
    focused_task_id: UUID | None = None
    focused_task_title: str | None = None
    focus_duration_minutes: float = 0.0
    status: str  # "focused" | "idle" | "paused"


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


class TaskImportIssue(BaseModel):
    """Ошибка в строке импорта задач."""

    row_number: int
    field: str
    message: str


class TaskImportPreviewRow(BaseModel):
    """Нормализованная строка предпросмотра импорта задач."""

    row_number: int
    title: str
    catalog_item_id: UUID | None = None
    catalog_item_name: str | None = None
    quantity: int | None = None
    priority: str
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    task_type: str | None = None
    complexity: str | None = None
    estimated_q: float | None = None
    min_league: str | None = None
    errors: list[TaskImportIssue] = Field(default_factory=list)


class TaskImportPreview(BaseModel):
    """Предпросмотр CSV-импорта задач."""

    batch_id: str
    total_rows: int
    valid_rows: int
    error_rows: int
    has_errors: bool
    warnings: list[str] = Field(default_factory=list)
    rows: list[TaskImportPreviewRow]


class TaskImportCommitResponse(BaseModel):
    """Результат подтверждённого CSV-импорта задач."""

    batch_id: str
    created_count: int
    tasks: list[TaskRead]


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
