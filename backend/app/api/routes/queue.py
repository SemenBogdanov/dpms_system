"""API очереди: список с can_pull/locked, pull, submit, validate. Все эндпоинты защищены JWT."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.queue import (
    QueueTaskResponse,
    PullRequest,
    SubmitRequest,
    ValidateRequest,
)
from app.schemas.task import TaskRead
from app.services.queue import (
    get_available_tasks,
    pull_task,
    submit_for_review,
    validate_task,
)

router = APIRouter()


@router.get("", response_model=list[QueueTaskResponse])
async def queue_list(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Задачи в очереди с полями can_pull, locked, lock_reason, estimator_name."""
    return await get_available_tasks(db, user.id)


@router.post("/pull", response_model=TaskRead)
async def queue_pull(
    body: PullRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Взять задачу из очереди (с блокировкой FOR UPDATE)."""
    user_id = body.user_id or user.id
    task = await pull_task(db, user_id, body.task_id)
    await db.refresh(task)
    return task


@router.post("/submit", response_model=TaskRead)
async def queue_submit(
    body: SubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сдать задачу на проверку (result_url, comment опционально)."""
    user_id = body.user_id or user.id
    task = await submit_for_review(
        db,
        user_id,
        body.task_id,
        result_url=body.result_url,
        comment=body.comment,
    )
    await db.refresh(task)
    return task


@router.post("/validate", response_model=TaskRead)
async def queue_validate(
    body: ValidateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принять или отклонить задачу (при reject comment обязателен)."""
    validator_id = body.validator_id or user.id
    task = await validate_task(
        db,
        validator_id,
        body.task_id,
        body.approved,
        comment=body.comment,
    )
    await db.refresh(task)
    return task