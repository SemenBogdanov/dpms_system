"""Схемы для очереди (pull, submit, validate)."""
from uuid import UUID

from pydantic import BaseModel


class QueuePullRequest(BaseModel):
    """Взять задачу из очереди."""
    user_id: UUID
    task_id: UUID


class QueueSubmitRequest(BaseModel):
    """Сдать задачу на проверку."""
    user_id: UUID
    task_id: UUID


class QueueValidateRequest(BaseModel):
    """Принять или отклонить задачу."""
    validator_id: UUID
    task_id: UUID
    approved: bool
    comment: str | None = None
