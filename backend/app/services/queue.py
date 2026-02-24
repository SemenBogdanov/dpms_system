"""Очередь: список с can_pull/locked, pull (FOR UPDATE), submit, validate."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskStatus, TaskType, TaskPriority
from app.models.user import User, League, UserRole
from app.models.transaction import QTransaction, WalletType
from app.schemas.queue import QueueTaskResponse
from app.schemas.task import compute_deadline_zone
from app.services.wallet import credit_q

_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}


async def get_available_tasks(
    db: AsyncSession,
    user_id: UUID,
    category: str | None = None,
) -> list[QueueTaskResponse]:
    """
    Все задачи in_queue. category: "proactive" — только проактивные,
    "!proactive" — только обычные, None — все.
    """
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

    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    user_league_order = _LEAGUE_ORDER.get(user.league, 0)
    can_pull_by_wip = wip_count < user.wip_limit

    estimator_ids = {t.estimator_id for t in tasks if t.estimator_id}
    estimator_map: dict[UUID, str] = {}
    if estimator_ids:
        est_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(estimator_ids))
        )
        estimator_map = {row.id: row.full_name for row in est_result.all()}

    out: list[QueueTaskResponse] = []
    for task in tasks:
        task_league_order = _LEAGUE_ORDER.get(task.min_league, 0)
        league_ok = user_league_order >= task_league_order
        if not league_ok:
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

        estimator_name = estimator_map.get(task.estimator_id) if task.estimator_id else None

        is_proactive = task.task_type == TaskType.proactive or getattr(task, "is_proactive", False)
        out.append(
            QueueTaskResponse(
                id=task.id,
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

    await db.flush()
    return task


async def submit_for_review(
    db: AsyncSession,
    user_id: UUID,
    task_id: UUID,
    result_url: str | None = None,
    comment: str | None = None,
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

    task.status = TaskStatus.review
    task.completed_at = datetime.now(timezone.utc)
    if result_url is not None:
        task.result_url = result_url
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
        return task

    # Принятие задачи
    task.status = TaskStatus.done
    task.validator_id = validator_id
    task.validated_at = datetime.now(timezone.utc)
    task.rejection_comment = None

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
    result = await db.execute(
        select(Task)
        .where(
            Task.due_date.is_not(None),
            Task.due_date < now,
            Task.is_overdue.is_(False),
            Task.status.in_([TaskStatus.in_progress, TaskStatus.review]),
        )
        .options(selectinload(Task.assignee))
    )
    overdue_tasks = list(result.scalars().all())
    if not overdue_tasks:
        return

    from app.services.notifications import create_notification

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
            await create_notification(
                db,
                tl.id,
                "task_overdue",
                "⏰ Задача просрочена",
                message=f"«{task.title}» просрочена у {assignee_name}",
                link="/queue",
            )