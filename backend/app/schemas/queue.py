"""Схемы для очереди (pull, submit, validate, ответ списка)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# user_id в body опционален (deprecated): берётся из JWT


class QueueTaskResponse(BaseModel):
    """Задача в очереди с флагами доступности."""
    id: UUID
    title: str
    description: str | None
    task_type: str
    complexity: str
    estimated_q: float
    priority: str
    min_league: str
    created_at: datetime
    estimator_name: str | None
    due_date: datetime | None = None
    deadline_zone: str | None = None
    can_pull: bool
    locked: bool
    lock_reason: str | None
    is_proactive: bool = False
    tags: list[str] = []
    is_stale: bool = False
    hours_in_queue: float = 0.0
    can_assign: bool = False
    recommended: bool = False
    assigned_by_name: str | None = None

    class Config:
        from_attributes = True


class AssignRequest(BaseModel):
    """Назначить задачу на исполнителя."""
    task_id: UUID
    executor_id: UUID
    comment: str | None = None


class AssignCandidate(BaseModel):
    """Кандидат для назначения задачи."""
    id: UUID
    full_name: str
    league: str
    wip_current: int
    wip_limit: int
    is_available: bool


class PullRequest(BaseModel):
    """Взять задачу из очереди. user_id опционален (из JWT)."""
    user_id: UUID | None = None
    task_id: UUID


class SubmitRequest(BaseModel):
    """Сдать задачу на проверку. user_id опционален (из JWT)."""
    user_id: UUID | None = None
    task_id: UUID
    result_url: str | None = None
    comment: str | None = None


class ValidateRequest(BaseModel):
    """Принять или отклонить задачу. validator_id опционален (из JWT)."""
    validator_id: UUID | None = None
    task_id: UUID
    approved: bool
    comment: str | None = None
