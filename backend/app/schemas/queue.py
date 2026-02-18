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

    class Config:
        from_attributes = True


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
