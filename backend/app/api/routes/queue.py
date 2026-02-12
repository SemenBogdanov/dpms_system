"""API глобальной очереди: доступные задачи, pull, submit, validate."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.queue import QueuePullRequest, QueueSubmitRequest, QueueValidateRequest
from app.schemas.task import TaskRead
from app.services.queue import get_available_tasks, pull_task, submit_for_review, validate_task

router = APIRouter()


@router.get("", response_model=list[TaskRead])
async def queue_list(
    user_id: UUID = Query(..., description="ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Доступные для пользователя задачи в очереди (in_queue, по лиге)."""
    tasks = await get_available_tasks(db, user_id)
    return tasks


@router.post("/pull", response_model=TaskRead)
async def queue_pull(
    body: QueuePullRequest,
    db: AsyncSession = Depends(get_db),
):
    """Взять задачу из очереди."""
    task = await pull_task(db, body.user_id, body.task_id)
    await db.refresh(task)
    return task


@router.post("/submit", response_model=TaskRead)
async def queue_submit(
    body: QueueSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Сдать задачу на проверку."""
    task = await submit_for_review(db, body.user_id, body.task_id)
    await db.refresh(task)
    return task


@router.post("/validate", response_model=TaskRead)
async def queue_validate(
    body: QueueValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Принять или отклонить задачу (с начислением Q при принятии)."""
    task = await validate_task(db, body.validator_id, body.task_id, body.approved)
    await db.refresh(task)
    return task
