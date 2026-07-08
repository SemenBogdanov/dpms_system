"""Очередь: список с can_pull/locked, pull (FOR UPDATE), submit, validate."""
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskPriority, TaskReviewEvent, TaskReviewEventType, TaskStatus, TaskType
from app.models.user import User, League, UserRole
from app.models.transaction import QTransaction, WalletType
from app.schemas.queue import QueueTaskResponse
from app.schemas.task import compute_deadline_zone
from app.services.focus import add_bounded_focus_time
from app.services.activity import record_activity_event
from app.services.wallet import credit_q

_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}
_PRIORITY_ORDER = {TaskPriority.low: 1, TaskPriority.medium: 2, TaskPriority.high: 3, TaskPriority.critical: 4}
CRITICAL_BLOCK_REASON = "Сначала нужно взять или назначить критическую задачу"

def _add_review_event(
    db: AsyncSession,
    task: Task,
    actor_id: UUID | None,
    event_type: TaskReviewEventType,
    *,
    comment: str | None = None,
    result_url: str | None = None,
    result_comment: str | None = None,
    brief_rating: int | None = None,
    brief_feedback: str | None = None,
    created_at: datetime | None = None,
) -> None:
    """Append task acceptance-cycle history without changing current task summary fields."""
    db.add(
        TaskReviewEvent(
            task_id=task.id,
            actor_id=actor_id,
            event_type=event_type,
            comment=comment.strip() if comment else None,
            result_url=result_url,
            result_comment=result_comment.strip() if result_comment else None,
            brief_rating=brief_rating,
            brief_feedback=brief_feedback.strip() if brief_feedback else None,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
_MAINTENANCE_INTERVAL = timedelta(seconds=60)
_maintenance_lock = asyncio.Lock()
_maintenance_last_run: datetime | None = None


async def run_dashboard_maintenance(db: AsyncSession) -> None:
    """Run expensive queue maintenance at most once per backend process interval."""
    global _maintenance_last_run

    now = datetime.now(timezone.utc)
    if _maintenance_last_run and now - _maintenance_last_run < _MAINTENANCE_INTERVAL:
        return

    async with _maintenance_lock:
        now = datetime.now(timezone.utc)
        if _maintenance_last_run and now - _maintenance_last_run < _MAINTENANCE_INTERVAL:
            return
        await check_overdue_tasks(db)
        await check_stale_tasks(db)
        _maintenance_last_run = datetime.now(timezone.utc)


async def _critical_queue_exists(db: AsyncSession, exclude_task_id: UUID | None = None) -> bool:
    stmt = select(Task.id).where(
        Task.status == TaskStatus.in_queue,
        Task.priority == TaskPriority.critical,
    )
    if exclude_task_id is not None:
        stmt = stmt.where(Task.id != exclude_task_id)
    result = await db.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None


async def get_available_tasks(
    db: AsyncSession,
    user_id: UUID,
    category: str | None = None,
) -> list[QueueTaskResponse]:
    """
    Все задачи in_queue. category: "proactive" — только проактивные,
    "!proactive" — только обычные, None — все.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return []

    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.in_queue)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    if category == "proactive":
        stmt = stmt.where(Task.task_type == TaskType.proactive)
    elif category == "!proactive":
        stmt = stmt.where(Task.task_type != TaskType.proactive)
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())
    has_critical_queue = await _critical_queue_exists(db)

    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    user_league_order = _LEAGUE_ORDER.get(user.league, 0)
    can_pull_by_wip = wip_count < user.wip_limit
    is_manager = user.role in (UserRole.teamlead, UserRole.admin)

    estimator_ids = {t.estimator_id for t in tasks if t.estimator_id}
    assigned_by_ids = {t.assigned_by_id for t in tasks if getattr(t, "assigned_by_id", None)}
    estimator_map: dict[UUID, str] = {}
    if estimator_ids:
        est_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(estimator_ids))
        )
        estimator_map = {row.id: row.full_name for row in est_result.all()}
    assigned_by_map: dict[UUID, str] = {}
    if assigned_by_ids:
        ab_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(assigned_by_ids))
        )
        assigned_by_map = {row.id: row.full_name for row in ab_result.all()}

    available_priorities: list[TaskPriority] = []
    for task in tasks:
        task_league_order = _LEAGUE_ORDER.get(task.min_league, 0)
        if (
            user_league_order >= task_league_order
            and can_pull_by_wip
            and (not has_critical_queue or task.priority == TaskPriority.critical)
        ):
            available_priorities.append(task.priority)
    top_priority = max(available_priorities, key=lambda p: _PRIORITY_ORDER.get(p, 0), default=None)

    out: list[QueueTaskResponse] = []
    for task in tasks:
        hours_in_queue = (now - task.created_at).total_seconds() / 3600
        is_stale = hours_in_queue > 48
        critical_blocked = has_critical_queue and task.priority != TaskPriority.critical
        can_assign = (
            is_manager
            and (task.priority == TaskPriority.critical or hours_in_queue > 24)
            and not critical_blocked
        )

        task_league_order = _LEAGUE_ORDER.get(task.min_league, 0)
        league_ok = user_league_order >= task_league_order
        if critical_blocked:
            can_pull = False
            locked = True
            lock_reason = CRITICAL_BLOCK_REASON
        elif not league_ok:
            can_pull = False
            locked = True
            lock_reason = f"Требуется Лига {task.min_league.value}"
        elif not can_pull_by_wip:
            can_pull = False
            locked = False
            lock_reason = "WIP-лимит исчерпан"
        else:
            can_pull = True
            locked = False
            lock_reason = None

        recommended = (
            can_pull
            and not locked
            and top_priority is not None
            and task.priority == top_priority
        )
        estimator_name = estimator_map.get(task.estimator_id) if task.estimator_id else None
        assigned_by_name = assigned_by_map.get(task.assigned_by_id) if getattr(task, "assigned_by_id", None) else None

        is_proactive = task.task_type == TaskType.proactive or getattr(task, "is_proactive", False)
        out.append(
            QueueTaskResponse(
                id=task.id,
                task_number=task.task_number,
                title=task.title,
                description=task.description,
                task_type=task.task_type.value,
                complexity=task.complexity.value,
                estimated_q=float(task.estimated_q),
                priority=task.priority.value,
                min_league=task.min_league.value,
                created_at=task.created_at,
                estimator_name=estimator_name,
                due_date=task.due_date,
                deadline_zone=compute_deadline_zone(task),
                is_proactive=is_proactive,
                can_pull=can_pull,
                locked=locked,
                lock_reason=lock_reason,
                tags=getattr(task, "tags", None) or [],
                is_stale=is_stale,
                hours_in_queue=round(hours_in_queue, 1),
                can_assign=can_assign,
                recommended=recommended,
                assigned_by_name=assigned_by_name,
            )
        )
    return out


async def pull_task(db: AsyncSession, user_id: UUID, task_id: UUID) -> Task:
    """Взять задачу. Атомарная блокировка SELECT FOR UPDATE."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    task_result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.in_queue:
        raise HTTPException(status_code=400, detail="Задача уже взята другим")
    if task.priority != TaskPriority.critical and await _critical_queue_exists(db, exclude_task_id=task.id):
        raise HTTPException(status_code=400, detail=CRITICAL_BLOCK_REASON)
    if _LEAGUE_ORDER.get(user.league, 0) < _LEAGUE_ORDER.get(task.min_league, 0):
        raise HTTPException(status_code=400, detail="Недостаточный уровень лиги")
    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    if wip_count >= user.wip_limit:
        raise HTTPException(status_code=400, detail="WIP-лимит исчерпан")

    task.status = TaskStatus.in_progress
    task.assignee_id = user_id
    task.started_at = datetime.now(timezone.utc)

    # Автоматический расчёт SLA, если дедлайн ещё не установлен тимлидом
    if task.due_date is None:
        league_value = user.league.value if hasattr(user.league, "value") else str(user.league)
        sla_multiplier = {"C": 3.0, "B": 2.0, "A": 1.5}.get(league_value, 3.0)
        try:
            est_q = float(task.estimated_q)
        except Exception:
            est_q = 0.0
        sla_hours = int(float(est_q) * sla_multiplier)
        task.sla_hours = sla_hours

        # Преобразование рабочих часов в календарное время (упрощённо: 1 рабочий день = 8 часов)
        from datetime import timedelta

        work_days_needed = max(1, sla_hours // 8)
        remaining_hours = sla_hours % 8
        task.due_date = datetime.now(timezone.utc) + timedelta(
            days=work_days_needed,
            hours=remaining_hours,
        )

    # Автофокус: у пользователя может быть только одна задача с активным фокусом
    now = datetime.now(timezone.utc)
    current_focus_result = await db.execute(
        select(Task).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
            Task.focus_started_at.is_not(None),
            Task.id != task.id,
        )
    )
    current_focus = current_focus_result.scalar_one_or_none()
    if current_focus and current_focus.focus_started_at is not None:
        added = add_bounded_focus_time(current_focus, now)
        await record_activity_event(
            db,
            user_id,
            "focus_auto_pause",
            task_id=current_focus.id,
            metadata={
                "reason": "pulled_another_task",
                "added_seconds": added,
                "active_seconds": current_focus.active_seconds,
            },
            occurred_at=now,
        )

    task.focus_started_at = now
    await record_activity_event(
        db,
        user_id,
        "task_pulled",
        task_id=task.id,
        metadata={"priority": task.priority.value, "estimated_q": float(task.estimated_q)},
        occurred_at=now,
    )
    await record_activity_event(
        db,
        user_id,
        "focus_start",
        task_id=task.id,
        metadata={"source": "auto_on_pull", "active_seconds": task.active_seconds},
        occurred_at=now,
    )

    await db.flush()
    return task


async def submit_for_review(
    db: AsyncSession,
    user_id: UUID,
    task_id: UUID,
    result_url: str | None = None,
    comment: str | None = None,
    brief_rating: int | None = None,
    brief_feedback: str | None = None,
) -> Task:
    """Сдать задачу на проверку."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.assignee_id != user_id:
        raise HTTPException(status_code=400, detail="Это не ваша задача")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=400, detail="Задача не в работе")
    if brief_rating is None:
        raise HTTPException(status_code=400, detail="Оценка постановки задачи обязательна")
    # Если задача в фокусе — зафиксировать время и снять с фокуса
    now = datetime.now(timezone.utc)
    if task.focus_started_at:
        added = add_bounded_focus_time(task, now)
        await record_activity_event(
            db,
            user_id,
            "focus_pause",
            task_id=task.id,
            metadata={"source": "submit_for_review", "added_seconds": added, "active_seconds": task.active_seconds},
            occurred_at=now,
        )

    task.status = TaskStatus.review
    task.completed_at = now
    if result_url is not None:
        task.result_url = result_url
    if comment is not None:
        task.result_comment = comment.strip() or None
    if brief_rating is not None:
        task.brief_rating = brief_rating
    if brief_feedback is not None:
        task.brief_feedback = brief_feedback.strip() or None
    _add_review_event(
        db,
        task,
        user_id,
        TaskReviewEventType.submitted,
        result_url=task.result_url,
        result_comment=task.result_comment,
        brief_rating=task.brief_rating,
        brief_feedback=task.brief_feedback,
        created_at=now,
    )
    await record_activity_event(
        db,
        user_id,
        "task_submitted",
        task_id=task.id,
        metadata={"estimated_q": float(task.estimated_q), "brief_rating": brief_rating},
        occurred_at=now,
    )
    await db.flush()
    return task


async def validate_task(
    db: AsyncSession,
    validator_id: UUID,
    task_id: UUID,
    approved: bool,
    comment: str | None = None,
) -> Task:
    """
    Принять или отклонить. Запрет самовалидации. При reject comment обязателен.
    Валидатор — teamlead или admin.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.review:
        raise HTTPException(status_code=400, detail="Задача не на проверке")

    validator_result = await db.execute(select(User).where(User.id == validator_id))
    validator = validator_result.scalar_one_or_none()
    if not validator:
        raise HTTPException(status_code=404, detail="Валидатор не найден")
    if validator.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(status_code=400, detail="Валидировать могут только тимлид или админ")
    if task.assignee_id == validator_id:
        raise HTTPException(status_code=400, detail="Нельзя валидировать свою задачу")

    if not approved:
        if not (comment and comment.strip()):
            raise HTTPException(status_code=400, detail="При возврате комментарий обязателен")
        task.status = TaskStatus.in_progress
        task.validator_id = None
        task.validated_at = None
        task.completed_at = None
        task.rejection_comment = comment.strip()
        # При возврате задача не должна оставаться в фокусе
        task.focus_started_at = None
        # Счётчик возвратов
        task.rejection_count = (getattr(task, "rejection_count", 0) or 0) + 1
        rejected_at = datetime.now(timezone.utc)

        # Quality Score: штраф за возврат
        if task.assignee_id:
            assignee_result = await db.execute(select(User).where(User.id == task.assignee_id))
            assignee = assignee_result.scalar_one_or_none()
            if assignee:
                old_score = float(getattr(assignee, "quality_score", 100.0))
                new_score = max(0.0, round(old_score - 5.0, 1))
                assignee.quality_score = new_score

                # Уведомление тимлидов при падении ниже 50
                if new_score < 50.0 <= old_score:
                    from app.services.notifications import create_notification

                    teamleads_result = await db.execute(
                        select(User).where(
                            User.role.in_([UserRole.teamlead, UserRole.admin]),
                            User.is_active.is_(True),
                        )
                    )
                    for tl in teamleads_result.scalars().all():
                        await create_notification(
                            db,
                            tl.id,
                            "quality_alert",
                            "⚠️ Низкий Quality Score",
                            message=f"{assignee.full_name}: Quality Score упал до {new_score:.0f}%",
                            link=f"/profile?user_id={assignee.id}",
                        )

        await db.flush()
        if task.assignee_id:
            from app.services.notifications import create_notification

            await create_notification(
                db,
                task.assignee_id,
                "task_rejected",
                "Задача отклонена",
                message=f"«{task.title}» отклонена: {comment.strip()}",
                link="/my-tasks",
            )
        _add_review_event(
            db,
            task,
            validator_id,
            TaskReviewEventType.returned,
            comment=comment.strip(),
            created_at=rejected_at,
        )
        await record_activity_event(
            db,
            validator_id,
            "task_rejected",
            task_id=task.id,
            metadata={
                "assignee_id": task.assignee_id,
                "comment": comment.strip(),
                "rejection_count": task.rejection_count,
            },
            occurred_at=rejected_at,
        )
        await db.flush()
        return task

    # Принятие задачи
    validated_at = datetime.now(timezone.utc)
    task.status = TaskStatus.done
    task.validator_id = validator_id
    task.validated_at = validated_at
    task.rejection_comment = None
    task.is_overdue = False

    assignee = None
    if task.assignee_id:
        assignee_result = await db.execute(select(User).where(User.id == task.assignee_id))
        assignee = assignee_result.scalar_one_or_none()

    if task.assignee_id:
        # Начисление Q
        if task.task_type == TaskType.bugfix and task.parent_task_id:
            # Гарантийный баг-фикс
            est_q = Decimal(str(task.estimated_q))
            if est_q > 0 and assignee:
                # Сиротский баг: бонус в karma-кошелёк
                assignee.wallet_karma += est_q
                db.add(
                    QTransaction(
                        user_id=assignee.id,
                        amount=est_q,
                        wallet_type=WalletType.karma,
                        reason=f"Гарантийный баг-фикс #{task.id}",
                        task_id=task.id,
                    )
                )
            # Если est_q == 0 — автор чинит бесплатно, без начисления Q
        else:
            # Обычная задача: начисление Q по стандартным правилам
            await credit_q(
                db,
                task.assignee_id,
                task.estimated_q,
                reason=f"Задача #{task.id} принята",
                task_id=task.id,
            )

        # Quality Score: бонус за успешную валидацию
        if assignee:
            old_score = float(getattr(assignee, "quality_score", 100.0))
            new_score = min(100.0, round(old_score + 1.0, 1))
            assignee.quality_score = new_score

        from app.services.notifications import create_notification

        await create_notification(
            db,
            task.assignee_id,
            "task_validated",
            "Задача принята",
            message=f"«{task.title}» валидирована. +{float(task.estimated_q)} Q",
            link="/my-tasks",
        )

    _add_review_event(
        db,
        task,
        validator_id,
        TaskReviewEventType.accepted,
        comment=comment,
        created_at=validated_at,
    )
    await record_activity_event(
        db,
        validator_id,
        "task_verified",
        task_id=task.id,
        metadata={"assignee_id": task.assignee_id, "estimated_q": float(task.estimated_q)},
        occurred_at=validated_at,
    )

    await db.flush()
    return task


async def create_bugfix(
    db: AsyncSession,
    reporter_id: UUID,
    parent_task_id: UUID,
    title: str,
    description: str,
) -> Task:
    """
    Создать гарантийный баг-фикс.

    1. Найти parent_task (должна быть status=done)
    2. Найти автора (parent_task.assignee_id)
    3. Если автор is_active=True:
       - Создать задачу bugfix, назначить на автора
       - status = in_progress, estimated_q = 0, priority = critical
       - Уведомить автора
    4. Если автор is_active=False или отсутствует:
       - Создать задачу bugfix, assignee_id = None
       - status = in_queue, estimated_q = parent_task.estimated_q * 0.5
       - Уведомить тимлидов
    """
    parent_result = await db.execute(select(Task).where(Task.id == parent_task_id))
    parent_task = parent_result.scalar_one_or_none()
    if not parent_task:
        raise HTTPException(status_code=404, detail="Оригинальная задача не найдена")
    if parent_task.status != TaskStatus.done:
        raise HTTPException(
            status_code=400,
            detail="Баг-фикс можно создать только по завершённой задаче",
        )

    assignee: User | None = None
    if parent_task.assignee_id:
        assignee_result = await db.execute(select(User).where(User.id == parent_task.assignee_id))
        assignee = assignee_result.scalar_one_or_none()

    from app.services.notifications import create_notification

    if assignee and assignee.is_active:
        # Автор доступен: 0Q, сразу в работу
        bugfix_task = Task(
            title=title,
            description=description,
            task_type=TaskType.bugfix,
            complexity=parent_task.complexity,
            estimated_q=Decimal("0"),
            priority=TaskPriority.critical,
            status=TaskStatus.in_progress,
            min_league=parent_task.min_league,
            assignee_id=assignee.id,
            estimator_id=reporter_id,
            validator_id=None,
            parent_task_id=parent_task.id,
        )
        db.add(bugfix_task)
        await db.flush()
        await db.refresh(bugfix_task)

        await create_notification(
            db,
            assignee.id,
            "bugfix_assigned",
            "Гарантийный баг-фикс",
            message=f"Гарантийный баг-фикс: «{title}» по задаче «{parent_task.title}»",
            link="/my-tasks",
        )
        return bugfix_task

    # Автор недоступен: задача в общую очередь, karma-бонус 50%
    estimated_q = Decimal(str(parent_task.estimated_q)) * Decimal("0.5")
    bugfix_task = Task(
        title=title,
        description=description,
        task_type=TaskType.bugfix,
        complexity=parent_task.complexity,
        estimated_q=estimated_q,
        priority=TaskPriority.critical,
        status=TaskStatus.in_queue,
        min_league=parent_task.min_league,
        assignee_id=None,
        estimator_id=reporter_id,
        validator_id=None,
        parent_task_id=parent_task.id,
    )
    db.add(bugfix_task)
    await db.flush()
    await db.refresh(bugfix_task)

    teamleads_result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.teamlead, UserRole.admin]),
            User.is_active.is_(True),
        )
    )
    for tl in teamleads_result.scalars().all():
        await create_notification(
            db,
            tl.id,
            "bugfix_orphan",
            "Гарантийный баг: автор недоступен",
            message=f"По задаче «{parent_task.title}» создан гарантийный баг-фикс и отправлен в очередь.",
            link="/queue",
        )

    return bugfix_task


async def check_overdue_tasks(db: AsyncSession) -> None:
    """
    Пометить просроченные задачи и уведомить тимлидов.
    Вызывается периодически (например, при запросах дашборда).
    """
    now = datetime.now(timezone.utc)
    stale_result = await db.execute(
        select(Task).where(
            Task.is_overdue.is_(True),
            (
                Task.due_date.is_(None)
                | ~Task.status.in_([TaskStatus.in_queue, TaskStatus.in_progress])
            ),
        )
    )
    for task in stale_result.scalars().all():
        task.is_overdue = False

    result = await db.execute(
        select(Task)
        .where(
            Task.due_date.is_not(None),
            Task.due_date < now,
            Task.is_overdue.is_(False),
            Task.status.in_([TaskStatus.in_queue, TaskStatus.in_progress]),
        )
        .options(selectinload(Task.assignee))
    )
    overdue_tasks = list(result.scalars().all())
    if not overdue_tasks:
        return

    from app.models.notification import Notification

    teamleads_result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.teamlead, UserRole.admin]),
            User.is_active.is_(True),
        )
    )
    teamleads = list(teamleads_result.scalars().all())

    for task in overdue_tasks:
        task.is_overdue = True
        assignee_name = task.assignee.full_name if getattr(task, "assignee", None) else "—"
        for tl in teamleads:
            db.add(
                Notification(
                    user_id=tl.id,
                    type="task_overdue",
                    title="⏰ Задача просрочена",
                    message=f"«{task.title}» просрочена у {assignee_name}",
                    link="/queue",
                )
            )


async def assign_task(
    db: AsyncSession,
    assigner_id: UUID,
    task_id: UUID,
    executor_id: UUID,
    comment: str | None = None,
) -> Task:
    """
    Тимлид назначает задачу на исполнителя. Админ может назначить на исполнителя или тимлида.
    Задача должна быть in_queue; non-critical назначается после 24ч в очереди.
    Исполнитель: league >= task.min_league, WIP свободен.
    """
    assigner_result = await db.execute(select(User).where(User.id == assigner_id))
    assigner = assigner_result.scalar_one_or_none()
    if not assigner or assigner.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(status_code=403, detail="Только тимлид или админ может назначать задачи")

    task_result = await db.execute(select(Task).where(Task.id == task_id).with_for_update())
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.in_queue:
        raise HTTPException(status_code=400, detail="Задача не в очереди")
    if task.priority != TaskPriority.critical and await _critical_queue_exists(db, exclude_task_id=task.id):
        raise HTTPException(status_code=400, detail=CRITICAL_BLOCK_REASON)

    hours_in_queue = (datetime.now(timezone.utc) - task.created_at).total_seconds() / 3600
    if task.priority != TaskPriority.critical and hours_in_queue < 24:
        raise HTTPException(
            status_code=400,
            detail="Назначить можно только задачу, которая в очереди более 24 часов",
        )

    executor_result = await db.execute(select(User).where(User.id == executor_id))
    executor = executor_result.scalar_one_or_none()
    if not executor:
        raise HTTPException(status_code=404, detail="Исполнитель не найден")
    allowed_executor_roles = (UserRole.executor,)
    if assigner.role == UserRole.admin:
        allowed_executor_roles = (UserRole.executor, UserRole.teamlead)
    if executor.role not in allowed_executor_roles:
        detail = "Админ может назначить задачу на исполнителя или тимлида"
        if assigner.role == UserRole.teamlead:
            detail = "Тимлид может назначить задачу только на исполнителя"
        raise HTTPException(status_code=400, detail=detail)
    if _LEAGUE_ORDER.get(executor.league, 0) < _LEAGUE_ORDER.get(task.min_league, 0):
        raise HTTPException(status_code=400, detail="У исполнителя недостаточный уровень лиги")

    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == executor_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    if wip_count >= executor.wip_limit:
        raise HTTPException(status_code=400, detail="У исполнителя исчерпан WIP-лимит")

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.in_progress
    task.assignee_id = executor_id
    task.assigned_by_id = assigner_id
    task.started_at = now

    if task.due_date is None:
        league_value = executor.league.value if hasattr(executor.league, "value") else str(executor.league)
        sla_multiplier = {"C": 3.0, "B": 2.0, "A": 1.5}.get(league_value, 3.0)
        est_q = float(task.estimated_q)
        sla_hours = int(est_q * sla_multiplier)
        task.sla_hours = sla_hours
        work_days_needed = max(1, sla_hours // 8)
        remaining_hours = sla_hours % 8
        task.due_date = now + timedelta(days=work_days_needed, hours=remaining_hours)

    await db.flush()

    await record_activity_event(
        db,
        assigner_id,
        "task_assigned",
        task_id=task.id,
        metadata={"executor_id": executor_id, "comment": comment, "estimated_q": float(task.estimated_q)},
        occurred_at=now,
    )

    from app.services.notifications import create_notification
    await create_notification(
        db,
        executor_id,
        "task_assigned",
        "Вам назначена задача",
        message=f"Вам назначена задача «{task.title}» тимлидом {assigner.full_name}",
        link="/my-tasks",
    )
    return task


async def get_assign_candidates(db: AsyncSession, task_id: UUID, assigner_id: UUID) -> list[dict]:
    """
    Список кандидатов для назначения задачи.
    Teamlead видит активных исполнителей, admin — исполнителей и тимлидов.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.in_queue:
        raise HTTPException(status_code=400, detail="Задача не в очереди")

    assigner_result = await db.execute(select(User).where(User.id == assigner_id))
    assigner = assigner_result.scalar_one_or_none()
    if not assigner or assigner.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(status_code=403, detail="Только тимлид или админ может назначать задачи")

    candidate_roles = [UserRole.executor]
    if assigner.role == UserRole.admin:
        candidate_roles.append(UserRole.teamlead)

    task_league_order = _LEAGUE_ORDER.get(task.min_league, 0)
    executors_result = await db.execute(
        select(User).where(
            User.role.in_(candidate_roles),
            User.is_active.is_(True),
        )
    )
    executors = list(executors_result.scalars().all())
    out = []
    for u in executors:
        if _LEAGUE_ORDER.get(u.league, 0) < task_league_order:
            continue
        wip_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.assignee_id == u.id,
                Task.status == TaskStatus.in_progress,
            )
        )
        wip_current = wip_result.scalar() or 0
        wip_limit = u.wip_limit or 2
        is_available = wip_current < wip_limit
        out.append({
            "id": u.id,
            "full_name": u.full_name,
            "role": u.role.value,
            "league": u.league.value,
            "wip_current": wip_current,
            "wip_limit": wip_limit,
            "is_available": is_available,
        })
    return out


async def check_stale_tasks(db: AsyncSession) -> None:
    """
    Задачи в очереди > 48ч — уведомить тимлидов.
    Не чаще 1 раза в 24ч на одну задачу.
    """
    from app.models.notification import Notification

    now = datetime.now(timezone.utc)
    since_48h = now - timedelta(hours=48)
    since_24h = now - timedelta(hours=24)
    result = await db.execute(
        select(Task).where(
            Task.status == TaskStatus.in_queue,
            Task.created_at < since_48h,
        )
    )
    stale_tasks = list(result.scalars().all())
    if not stale_tasks:
        return

    teamleads_result = await db.execute(
        select(User).where(
            User.role.in_([UserRole.teamlead, UserRole.admin]),
            User.is_active.is_(True),
        )
    )
    teamleads = list(teamleads_result.scalars().all())
    if not teamleads:
        return

    links_by_task_id = {task.id: f"/queue?stale={task.id}" for task in stale_tasks}
    stale_links = list(links_by_task_id.values())
    recent_result = await db.execute(
        select(Notification.link).where(
            Notification.type == "task_stale",
            Notification.link.in_(stale_links),
            Notification.created_at >= since_24h,
        )
    )
    recent_links = {link for link in recent_result.scalars().all() if link}

    for task in stale_tasks:
        hours = int((now - task.created_at).total_seconds() / 3600)
        link = links_by_task_id[task.id]
        if link in recent_links:
            continue
        for tl in teamleads:
            db.add(
                Notification(
                    user_id=tl.id,
                    type="task_stale",
                    title="⏳ Задача в очереди давно",
                    message=f"Задача «{task.title}» в очереди более {hours}ч, никто не берёт",
                    link=link,
                )
            )
    await db.flush()
