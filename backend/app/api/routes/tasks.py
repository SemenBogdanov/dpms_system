"""API задач. Все эндпоинты защищены JWT."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.models.user import User
from app.models.task import Task, TaskStatus
from app.schemas.task import (
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TaskExportRow,
    TasksExport,
    SetDueDateRequest,
    CreateBugfixRequest,
)
from app.services.queue import create_bugfix

router = APIRouter()


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    status: TaskStatus | None = Query(None),
    assignee_id: UUID | None = Query(None),
    task_type: str | None = Query(None),
    user: User = Depends(get_current_user),
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


@router.get("/export", response_model=TasksExport)
async def export_tasks(
    period: str = Query(..., description="YYYY-MM"),
    assignee_id: UUID | None = Query(None),
    category: str | None = Query(None, description="task_type: widget, etl, api, docs"),
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт завершённых задач за период (admin/teamlead)."""
    try:
        year, month = int(period[:4]), int(period[5:7])
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Некорректный период (ожидается YYYY-MM)")
    stmt = (
        select(Task)
        .where(Task.completed_at >= start, Task.completed_at < end)
        .order_by(Task.completed_at)
    )
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if category is not None:
        from app.models.task import TaskType
        try:
            stmt = stmt.where(Task.task_type == TaskType(category))
        except ValueError:
            pass
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())
    user_ids = set()
    for t in tasks:
        if t.assignee_id:
            user_ids.add(t.assignee_id)
        if t.validator_id:
            user_ids.add(t.validator_id)
    users_map: dict[UUID, str] = {}
    if user_ids:
        u_res = await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        users_map = {row.id: row.full_name for row in u_res.all()}
    rows: list[TaskExportRow] = []
    total_q = 0.0
    for t in tasks:
        duration_hours = None
        if t.started_at and t.completed_at:
            delta = t.completed_at - t.started_at
            duration_hours = round(delta.total_seconds() / 3600, 1)
        rows.append(
            TaskExportRow(
                title=t.title,
                category=t.task_type.value,
                complexity=t.complexity.value,
                estimated_q=float(t.estimated_q),
                assignee_name=users_map.get(t.assignee_id) if t.assignee_id else "",
                started_at=t.started_at.isoformat() if t.started_at else None,
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                duration_hours=duration_hours,
                validator_name=users_map.get(t.validator_id) if t.validator_id else None,
                status=t.status.value,
            )
        )
        total_q += float(t.estimated_q)
    return TasksExport(period=period, rows=rows, total_tasks=len(rows), total_q=round(total_q, 1))


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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


@router.patch("/{task_id}/due-date", response_model=TaskRead)
async def set_due_date(
    task_id: UUID,
    body: SetDueDateRequest,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Ручная установка дедлайна задачи (только admin/teamlead).
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    task.due_date = body.due_date
    await db.flush()
    await db.refresh(task)
    return task


@router.post("/bugfix", response_model=TaskRead)
async def create_bugfix_task(
    body: CreateBugfixRequest,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Создать гарантийный баг-фикс по завершённой задаче (admin/teamlead).
    """
    task = await create_bugfix(
        db,
        reporter_id=user.id,
        parent_task_id=body.parent_task_id,
        title=body.title,
        description=body.description or "",
    )
    await db.refresh(task)
    return task
