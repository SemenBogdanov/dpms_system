"""API задач."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.task import Task, TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter()


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    status: TaskStatus | None = Query(None),
    assignee_id: UUID | None = Query(None),
    task_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Список задач с фильтрами."""
    stmt = select(Task).order_by(Task.created_at.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if task_type is not None:
        from app.models.task import TaskType
        try:
            tt = TaskType(task_type)
            stmt = stmt.where(Task.task_type == tt)
        except ValueError:
            pass
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Детали задачи."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("", response_model=TaskRead)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """Создать задачу (с оценкой или без)."""
    task = Task(
        title=body.title,
        description=body.description,
        task_type=body.task_type,
        complexity=body.complexity,
        estimated_q=body.estimated_q,
        priority=body.priority,
        status=body.status,
        min_league=body.min_league,
        estimator_id=body.estimator_id,
        estimation_details=body.estimation_details,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: UUID,
    body: TaskUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Обновить описание/приоритет задачи."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.priority is not None:
        task.priority = body.priority
    await db.flush()
    await db.refresh(task)
    return task
