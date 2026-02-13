"""API очереди: список с can_pull/locked, pull, submit, validate."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
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
    user_id: UUID = Query(..., description="ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Задачи в очереди с полями can_pull, locked, lock_reason, estimator_name."""
    return await get_available_tasks(db, user_id)


@router.post("/pull", response_model=TaskRead)
async def queue_pull(
    body: PullRequest,
    db: AsyncSession = Depends(get_db),
):
    """Взять задачу из очереди (с блокировкой FOR UPDATE)."""
    task = await pull_task(db, body.user_id, body.task_id)
    await db.refresh(task)
    return task


@router.post("/submit", response_model=TaskRead)
async def queue_submit(
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Сдать задачу на проверку (result_url, comment опционально)."""
    task = await submit_for_review(
        db,
        body.user_id,
        body.task_id,
        result_url=body.result_url,
        comment=body.comment,
    )
    await db.refresh(task)
    return task


@router.post("/validate", response_model=TaskRead)
async def queue_validate(
    body: ValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Принять или отклонить задачу (при reject comment обязателен)."""
    task = await validate_task(
        db,
        body.validator_id,
        body.task_id,
        body.approved,
        comment=body.comment,
    )
    await db.refresh(task)
    return task