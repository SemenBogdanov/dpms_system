"""Схемы для очереди (pull, submit, validate, ответ списка)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
    can_pull: bool
    locked: bool
    lock_reason: str | None

    class Config:
        from_attributes = True


class PullRequest(BaseModel):
    """Взять задачу из очереди."""
    user_id: UUID
    task_id: UUID


class SubmitRequest(BaseModel):
    """Сдать задачу на проверку."""
    user_id: UUID
    task_id: UUID
    result_url: str | None = None
    comment: str | None = None


class ValidateRequest(BaseModel):
    """Принять или отклонить задачу."""
    validator_id: UUID
    task_id: UUID
    approved: bool
    comment: str | None = None
