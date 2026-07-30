"""Project workspace, typed schedule graph, and controlled forecast changes."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityLink,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityStage,
    WorkEntityTask,
)
from app.schemas.work_entity import (
    WorkEntityArtifactRead,
    WorkEntityMapEdge,
    WorkEntityMapNode,
    WorkEntityMapRead,
    WorkEntityMilestoneRead,
    WorkEntityMilestoneReschedulePreviewRead,
    WorkEntityParticipantRead,
    WorkEntityScheduleChangeRead,
    WorkEntityScheduleConflictRead,
    WorkEntityScheduleDependencyRead,
    WorkEntityStageRead,
    WorkEntityTaskRead,
    WorkEntityWorkspaceRead,
)
from app.services.work_entities import serialize_links

WORKSPACE_GRAPH_ADVISORY_LOCK_KEY = 460047
TERMINAL_TASK_STATUSES = {"done", "cancelled"}
TERMINAL_MILESTONE_STATUSES = {"achieved", "cancelled"}
ASSIGNABLE_MEMBER_ROLES = {"participant", "editor"}
DEPENDENCY_GATED_TASK_STATUSES = {"in_progress", "review", "done"}
AUTO_SHIFT_TASK_STATUSES = {"planned", "waiting", "blocked"}
NodeKey = tuple[str, UUID]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_workspace_mutable(entity: WorkEntity) -> None:
    if entity.status in {"done", "archived"}:
        raise HTTPException(
            status_code=409,
            detail="Завершенный или архивный проект нельзя изменять",
        )


def _days_between(before: datetime, after: datetime) -> int:
    seconds = (after - before).total_seconds()
    if seconds == 0:
        return 0
    return ceil(seconds / 86400) if seconds > 0 else -ceil(abs(seconds) / 86400)


def milestone_display_status(milestone: WorkEntityMilestone) -> str:
    if milestone.status == "achieved":
        return "achieved"
    if milestone.status == "cancelled":
        return "cancelled"
    if milestone.forecast_at < utc_now():
        return "overdue"
    if milestone.forecast_at != milestone.baseline_at:
        return "rescheduled"
    return "planned"


def task_ref(task: WorkEntityTask) -> str:
    return f"PRJ-{task.task_number}"


def milestone_ref(milestone: WorkEntityMilestone) -> str:
    return f"КТ-{milestone.milestone_number}"


def node_key(node_type: str, node_id: UUID) -> NodeKey:
    return node_type, node_id


def dependency_predecessor(
    dependency: WorkEntityScheduleDependency,
) -> NodeKey:
    if dependency.predecessor_task_id is not None:
        return node_key("task", dependency.predecessor_task_id)
    return node_key("milestone", dependency.predecessor_milestone_id)


def dependency_successor(
    dependency: WorkEntityScheduleDependency,
) -> NodeKey:
    if dependency.successor_task_id is not None:
        return node_key("task", dependency.successor_task_id)
    return node_key("milestone", dependency.successor_milestone_id)


def dependency_columns(
    predecessor_type: str,
    predecessor_id: UUID,
    successor_type: str,
    successor_id: UUID,
) -> dict:
    return {
        "predecessor_task_id": (
            predecessor_id if predecessor_type == "task" else None
        ),
        "predecessor_milestone_id": (
            predecessor_id if predecessor_type == "milestone" else None
        ),
        "successor_task_id": (
            successor_id if successor_type == "task" else None
        ),
        "successor_milestone_id": (
            successor_id if successor_type == "milestone" else None
        ),
    }


def validate_task_dates(
    entity: WorkEntity,
    starts_at: datetime | None,
    due_at: datetime | None,
    *,
    against_baseline: bool,
) -> None:
    if starts_at and due_at and due_at <= starts_at:
        raise HTTPException(
            status_code=400,
            detail="Срок задачи должен быть позже даты начала",
        )
    if not against_baseline:
        return
    is_new_scope = entity.baseline_locked_at is not None
    if entity.starts_at:
        if starts_at and starts_at < entity.starts_at:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Дата новой работы не может быть раньше начала проекта"
                    if is_new_scope
                    else "Базовая дата задачи не может быть раньше начала проекта"
                ),
            )
        if due_at and due_at < entity.starts_at:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Срок новой работы не может быть раньше начала проекта"
                    if is_new_scope
                    else "Базовый срок задачи не может быть раньше начала проекта"
                ),
            )
    project_limit = (
        entity.target_due_at or entity.due_at
        if is_new_scope
        else entity.due_at
    )
    if project_limit:
        if starts_at and starts_at > project_limit:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Дата новой работы не может быть позже текущей цели проекта"
                    if is_new_scope
                    else "Базовая дата задачи не может быть позже срока проекта"
                ),
            )
        if due_at and due_at > project_limit:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Срок новой работы не может выходить за текущую цель проекта"
                    if is_new_scope
                    else "Базовый срок задачи не может выходить за срок проекта"
                ),
            )


def validate_milestone_baseline(
    entity: WorkEntity,
    baseline_at: datetime,
) -> None:
    if entity.starts_at and baseline_at < entity.starts_at:
        raise HTTPException(
            status_code=400,
            detail="Контрольная точка не может быть раньше начала проекта",
        )
    project_limit = (
        entity.target_due_at or entity.due_at
        if entity.baseline_locked_at is not None
        else entity.due_at
    )
    if project_limit and baseline_at > project_limit:
        raise HTTPException(
            status_code=400,
            detail=(
                "Новая контрольная точка не может быть позже текущей цели проекта"
                if entity.baseline_locked_at is not None
                else "Контрольная точка не может быть позже базового срока проекта"
            ),
        )


async def validate_stage(
    db: AsyncSession,
    entity_id: UUID,
    stage_id: UUID | None,
) -> WorkEntityStage | None:
    if stage_id is None:
        return None
    stage = (
        await db.execute(
            select(WorkEntityStage).where(
                WorkEntityStage.id == stage_id,
                WorkEntityStage.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=400, detail="Этап не относится к проекту")
    if stage.status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Нельзя добавить работу в отмененный этап",
        )
    return stage


async def validate_assignee(
    db: AsyncSession,
    entity: WorkEntity,
    assignee_id: UUID | None,
) -> User | None:
    if assignee_id is None:
        return None
    user = (
        await db.execute(
            select(User).where(User.id == assignee_id, User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Исполнитель не найден")
    if assignee_id == entity.owner_id:
        return user
    member_role = (
        await db.execute(
            select(WorkEntityMember.role).where(
                WorkEntityMember.entity_id == entity.id,
                WorkEntityMember.user_id == assignee_id,
            )
        )
    ).scalar_one_or_none()
    if member_role not in ASSIGNABLE_MEMBER_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Исполнителем может быть владелец, участник или редактор проекта",
        )
    return user


async def validate_decision_owner(
    db: AsyncSession,
    entity: WorkEntity,
    user_id: UUID | None,
) -> User | None:
    if user_id is None:
        return None
    return await validate_assignee(db, entity, user_id)


async def lock_workspace_graph(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": WORKSPACE_GRAPH_ADVISORY_LOCK_KEY},
    )


async def _schedule_rows(
    db: AsyncSession,
    entity_id: UUID,
) -> tuple[
    dict[UUID, WorkEntityTask],
    dict[UUID, WorkEntityMilestone],
    list[WorkEntityScheduleDependency],
]:
    tasks = {
        item.id: item
        for item in (
            await db.execute(
                select(WorkEntityTask).where(WorkEntityTask.entity_id == entity_id)
            )
        ).scalars().all()
    }
    milestones = {
        item.id: item
        for item in (
            await db.execute(
                select(WorkEntityMilestone).where(
                    WorkEntityMilestone.entity_id == entity_id
                )
            )
        ).scalars().all()
    }
    dependencies = list(
        (
            await db.execute(
                select(WorkEntityScheduleDependency).where(
                    WorkEntityScheduleDependency.entity_id == entity_id,
                    WorkEntityScheduleDependency.status == "active",
                )
            )
        ).scalars().all()
    )
    return tasks, milestones, dependencies


def _node_exists(
    key: NodeKey,
    tasks: dict[UUID, WorkEntityTask],
    milestones: dict[UUID, WorkEntityMilestone],
) -> bool:
    return key[1] in (tasks if key[0] == "task" else milestones)


async def would_create_dependency_cycle(
    db: AsyncSession,
    entity_id: UUID,
    predecessor: NodeKey,
    successor: NodeKey,
) -> bool:
    _, _, dependencies = await _schedule_rows(db, entity_id)
    adjacency: dict[NodeKey, set[NodeKey]] = defaultdict(set)
    for dependency in dependencies:
        adjacency[dependency_predecessor(dependency)].add(
            dependency_successor(dependency)
        )
    adjacency[predecessor].add(successor)

    visiting: set[NodeKey] = set()
    visited: set[NodeKey] = set()

    def visit(current: NodeKey) -> bool:
        if current in visiting:
            return True
        if current in visited:
            return False
        visiting.add(current)
        if any(visit(next_key) for next_key in adjacency.get(current, set())):
            return True
        visiting.remove(current)
        visited.add(current)
        return False

    return any(visit(current) for current in list(adjacency))


def _node_is_complete(
    key: NodeKey,
    tasks: dict[UUID, WorkEntityTask],
    milestones: dict[UUID, WorkEntityMilestone],
) -> bool:
    if key[0] == "task":
        return tasks[key[1]].status == "done"
    return milestones[key[1]].status == "achieved"


def _node_label(
    key: NodeKey,
    tasks: dict[UUID, WorkEntityTask],
    milestones: dict[UUID, WorkEntityMilestone],
) -> str:
    if key[0] == "task":
        item = tasks[key[1]]
        return f"{task_ref(item)} {item.title}"
    item = milestones[key[1]]
    return f"{milestone_ref(item)} {item.title}"


async def ensure_predecessors_completed(
    db: AsyncSession,
    entity_id: UUID,
    successor: NodeKey,
) -> None:
    tasks, milestones, dependencies = await _schedule_rows(db, entity_id)
    incomplete = [
        dependency_predecessor(item)
        for item in dependencies
        if dependency_successor(item) == successor
        and not _node_is_complete(
            dependency_predecessor(item),
            tasks,
            milestones,
        )
    ]
    if incomplete:
        labels = ", ".join(
            _node_label(item, tasks, milestones) for item in incomplete[:3]
        )
        raise HTTPException(
            status_code=409,
            detail=f"Сначала завершите предшествующие элементы: {labels}",
        )


async def ensure_dependents_allow_reopen(
    db: AsyncSession,
    entity_id: UUID,
    predecessor: NodeKey,
) -> None:
    tasks, milestones, dependencies = await _schedule_rows(db, entity_id)
    affected: list[NodeKey] = []
    for dependency in dependencies:
        if dependency_predecessor(dependency) != predecessor:
            continue
        successor = dependency_successor(dependency)
        if successor[0] == "task":
            if tasks[successor[1]].status in DEPENDENCY_GATED_TASK_STATUSES:
                affected.append(successor)
        elif milestones[successor[1]].status == "achieved":
            affected.append(successor)
    if affected:
        labels = ", ".join(
            _node_label(item, tasks, milestones) for item in affected[:3]
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Сначала верните зависимые элементы в плановое состояние: "
                f"{labels}"
            ),
        )


async def count_open_assigned_tasks(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
) -> int:
    return int(
        (
            await db.execute(
                select(func.count(WorkEntityTask.id)).where(
                    WorkEntityTask.entity_id == entity_id,
                    WorkEntityTask.assignee_id == user_id,
                    WorkEntityTask.status.not_in(TERMINAL_TASK_STATUSES),
                )
            )
        ).scalar_one()
    )


async def recalculate_project_forecast_due(
    db: AsyncSession,
    entity: WorkEntity,
) -> datetime | None:
    """Roll up the current schedule without overwriting the project baseline."""
    await db.flush()
    task_due = (
        await db.execute(
            select(func.max(WorkEntityTask.forecast_due_at)).where(
                WorkEntityTask.entity_id == entity.id,
                WorkEntityTask.status != "cancelled",
            )
        )
    ).scalar_one()
    milestone_due = (
        await db.execute(
            select(func.max(WorkEntityMilestone.forecast_at)).where(
                WorkEntityMilestone.entity_id == entity.id,
                WorkEntityMilestone.status != "cancelled",
            )
        )
    ).scalar_one()
    schedule_dates = [
        value for value in (task_due, milestone_due) if value is not None
    ]
    entity.forecast_due_at = max(
        schedule_dates,
        default=entity.due_at,
    )
    return entity.forecast_due_at


async def _workspace_rows(db: AsyncSession, entity: WorkEntity):
    member_rows = (
        await db.execute(
            select(WorkEntityMember, User)
            .join(User, User.id == WorkEntityMember.user_id)
            .where(WorkEntityMember.entity_id == entity.id)
            .order_by(User.full_name, User.email)
        )
    ).all()
    owner = (
        await db.execute(select(User).where(User.id == entity.owner_id))
    ).scalar_one()
    stages = list(
        (
            await db.execute(
                select(WorkEntityStage)
                .where(WorkEntityStage.entity_id == entity.id)
                .order_by(WorkEntityStage.position, WorkEntityStage.created_at)
            )
        ).scalars().all()
    )
    tasks = list(
        (
            await db.execute(
                select(WorkEntityTask)
                .where(WorkEntityTask.entity_id == entity.id)
                .order_by(
                    WorkEntityTask.position,
                    WorkEntityTask.forecast_due_at.is_(None),
                    WorkEntityTask.forecast_due_at,
                    WorkEntityTask.created_at,
                )
            )
        ).scalars().all()
    )
    milestones = list(
        (
            await db.execute(
                select(WorkEntityMilestone)
                .where(WorkEntityMilestone.entity_id == entity.id)
                .order_by(
                    WorkEntityMilestone.position,
                    WorkEntityMilestone.forecast_at,
                    WorkEntityMilestone.created_at,
                )
            )
        ).scalars().all()
    )
    dependencies = list(
        (
            await db.execute(
                select(WorkEntityScheduleDependency)
                .where(WorkEntityScheduleDependency.entity_id == entity.id)
                .order_by(WorkEntityScheduleDependency.created_at)
            )
        ).scalars().all()
    )
    artifacts = list(
        (
            await db.execute(
                select(WorkEntityArtifact)
                .where(WorkEntityArtifact.entity_id == entity.id)
                .order_by(
                    WorkEntityArtifact.status == "archived",
                    WorkEntityArtifact.updated_at.desc(),
                )
            )
        ).scalars().all()
    )
    user_ids = {
        user_id
        for item in tasks
        for user_id in (item.assignee_id, item.created_by_id)
        if user_id is not None
    }
    user_ids.update(
        user_id
        for item in milestones
        for user_id in (item.decision_owner_id, item.created_by_id)
        if user_id is not None
    )
    user_ids.update(
        user_id
        for item in artifacts
        for user_id in (item.created_by_id, item.updated_by_id)
        if user_id is not None
    )
    user_ids.update(
        user_id
        for item in dependencies
        for user_id in (item.created_by_id, item.waived_by_id)
        if user_id is not None
    )
    user_ids.add(owner.id)
    user_ids.update(member.user_id for member, _ in member_rows)
    users = (
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()
    user_map = {item.id: item for item in users}
    return (
        owner,
        member_rows,
        stages,
        tasks,
        milestones,
        dependencies,
        artifacts,
        user_map,
    )


async def build_workspace(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    current_user: User,
) -> WorkEntityWorkspaceRead:
    (
        owner,
        member_rows,
        stages,
        tasks,
        milestones,
        dependencies,
        artifacts,
        user_map,
    ) = await _workspace_rows(db, entity)
    open_counts = dict(
        (
            await db.execute(
                select(WorkEntityTask.assignee_id, func.count(WorkEntityTask.id))
                .where(
                    WorkEntityTask.entity_id == entity.id,
                    WorkEntityTask.assignee_id.is_not(None),
                    WorkEntityTask.status.not_in(TERMINAL_TASK_STATUSES),
                )
                .group_by(WorkEntityTask.assignee_id)
            )
        ).all()
    )
    participants = [
        WorkEntityParticipantRead(
            user_id=owner.id,
            user_name=owner.full_name,
            user_email=(
                owner.email
                if access_role == "owner" or owner.id == current_user.id
                else None
            ),
            role="owner",
            can_be_assigned=True,
            open_tasks=int(open_counts.get(owner.id, 0)),
        )
    ]
    participants.extend(
        WorkEntityParticipantRead(
            user_id=member.user_id,
            user_name=member_user.full_name,
            user_email=(
                member_user.email
                if access_role == "owner" or member.user_id == current_user.id
                else None
            ),
            role=member.role,
            can_be_assigned=member.role in ASSIGNABLE_MEMBER_ROLES,
            open_tasks=int(open_counts.get(member.user_id, 0)),
        )
        for member, member_user in member_rows
    )

    can_manage = access_role in {"owner", "editor"}
    stage_map = {item.id: item for item in stages}
    task_map = {item.id: item for item in tasks}
    milestone_map = {item.id: item for item in milestones}
    predecessor_ids: dict[NodeKey, list[str]] = defaultdict(list)
    target_milestone_ids: dict[UUID, UUID] = {}
    for dependency in dependencies:
        if dependency.status != "active":
            continue
        predecessor = dependency_predecessor(dependency)
        successor = dependency_successor(dependency)
        predecessor_ids[successor].append(f"{predecessor[0]}:{predecessor[1]}")
        if predecessor[0] == "task" and successor[0] == "milestone":
            target_milestone_ids[predecessor[1]] = successor[1]

    stage_task_counts: dict[UUID, int] = defaultdict(int)
    stage_milestone_counts: dict[UUID, int] = defaultdict(int)
    for task in tasks:
        if task.stage_id:
            stage_task_counts[task.stage_id] += 1
    for milestone in milestones:
        if milestone.stage_id:
            stage_milestone_counts[milestone.stage_id] += 1

    stage_reads = [
        WorkEntityStageRead(
            id=stage.id,
            entity_id=stage.entity_id,
            title=stage.title,
            description=stage.description,
            completion_criteria=stage.completion_criteria,
            guidance=stage.guidance,
            status=stage.status,
            source_type=stage.source_type,
            source_key=stage.source_key,
            source_snapshot=stage.source_snapshot,
            position=stage.position,
            tasks_count=stage_task_counts.get(stage.id, 0),
            milestones_count=stage_milestone_counts.get(stage.id, 0),
            can_manage=can_manage,
            created_at=stage.created_at,
            updated_at=stage.updated_at,
        )
        for stage in stages
    ]
    task_reads = [
        WorkEntityTaskRead(
            id=task.id,
            task_number=task.task_number,
            entity_id=task.entity_id,
            stage_id=task.stage_id,
            stage_title=(
                stage_map[task.stage_id].title if task.stage_id in stage_map else None
            ),
            target_milestone_id=target_milestone_ids.get(task.id),
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            assignee_id=task.assignee_id,
            assignee_name=(
                user_map[task.assignee_id].full_name
                if task.assignee_id in user_map
                else None
            ),
            assignee_email=(
                user_map[task.assignee_id].email
                if task.assignee_id in user_map
                and (
                    access_role == "owner"
                    or task.assignee_id == current_user.id
                )
                else None
            ),
            created_by_id=task.created_by_id,
            created_by_name=(
                user_map[task.created_by_id].full_name
                if task.created_by_id in user_map
                else None
            ),
            acceptance_criteria=task.acceptance_criteria,
            next_step=task.next_step,
            waiting_for=task.waiting_for,
            baseline_starts_at=task.baseline_starts_at,
            baseline_due_at=task.baseline_due_at,
            forecast_starts_at=task.forecast_starts_at,
            forecast_due_at=task.forecast_due_at,
            actual_starts_at=task.actual_starts_at,
            actual_due_at=task.actual_due_at,
            introduced_after_baseline=task.introduced_after_baseline,
            introduced_at_revision=task.introduced_at_revision,
            variance_days=(
                _days_between(task.baseline_due_at, task.forecast_due_at)
                if task.baseline_due_at and task.forecast_due_at
                else None
            ),
            position=task.position,
            predecessor_ids=predecessor_ids.get(node_key("task", task.id), []),
            can_manage=can_manage,
            can_execute=can_manage
            or (
                access_role == "participant"
                and task.assignee_id == current_user.id
            ),
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]
    milestone_reads = [
        WorkEntityMilestoneRead(
            id=milestone.id,
            milestone_number=milestone.milestone_number,
            entity_id=milestone.entity_id,
            stage_id=milestone.stage_id,
            stage_title=(
                stage_map[milestone.stage_id].title
                if milestone.stage_id in stage_map
                else None
            ),
            title=milestone.title,
            description=milestone.description,
            status=milestone.status,
            display_status=milestone_display_status(milestone),
            criticality=milestone.criticality,
            criticality_reason=milestone.criticality_reason,
            acceptance_criteria=milestone.acceptance_criteria,
            decision_owner_id=milestone.decision_owner_id,
            decision_owner_name=(
                user_map[milestone.decision_owner_id].full_name
                if milestone.decision_owner_id in user_map
                else None
            ),
            created_by_id=milestone.created_by_id,
            created_by_name=(
                user_map[milestone.created_by_id].full_name
                if milestone.created_by_id in user_map
                else None
            ),
            baseline_at=milestone.baseline_at,
            forecast_at=milestone.forecast_at,
            actual_at=milestone.actual_at,
            cancelled_at=milestone.cancelled_at,
            variance_days=_days_between(
                milestone.baseline_at,
                milestone.forecast_at,
            ),
            reschedule_reason=milestone.reschedule_reason,
            reschedule_count=milestone.reschedule_count,
            introduced_after_baseline=milestone.introduced_after_baseline,
            introduced_at_revision=milestone.introduced_at_revision,
            position=milestone.position,
            predecessor_ids=predecessor_ids.get(
                node_key("milestone", milestone.id),
                [],
            ),
            can_manage=can_manage,
            created_at=milestone.created_at,
            updated_at=milestone.updated_at,
        )
        for milestone in milestones
    ]
    dependency_reads = []
    for item in dependencies:
        serialized = serialize_dependency(item, task_map, milestone_map)
        serialized.waived_by_name = (
            user_map[item.waived_by_id].full_name
            if item.waived_by_id in user_map
            else None
        )
        dependency_reads.append(serialized)
    artifact_reads = [
        WorkEntityArtifactRead(
            id=artifact.id,
            entity_id=artifact.entity_id,
            task_id=artifact.task_id,
            task_title=(
                task_map[artifact.task_id].title
                if artifact.task_id in task_map
                else None
            ),
            milestone_id=artifact.milestone_id,
            milestone_title=(
                milestone_map[artifact.milestone_id].title
                if artifact.milestone_id in milestone_map
                else None
            ),
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            body=artifact.body,
            url=artifact.url,
            status=artifact.status,
            created_by_id=artifact.created_by_id,
            created_by_name=(
                user_map[artifact.created_by_id].full_name
                if artifact.created_by_id in user_map
                else None
            ),
            updated_by_id=artifact.updated_by_id,
            updated_by_name=(
                user_map[artifact.updated_by_id].full_name
                if artifact.updated_by_id in user_map
                else None
            ),
            archived_at=artifact.archived_at,
            can_edit=can_manage
            or (
                access_role == "participant"
                and artifact.created_by_id == current_user.id
            ),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )
        for artifact in artifacts
    ]
    return WorkEntityWorkspaceRead(
        entity_id=entity.id,
        current_access_role=access_role,
        participants=participants,
        stages=stage_reads,
        tasks=task_reads,
        milestones=milestone_reads,
        dependencies=dependency_reads,
        artifacts=artifact_reads,
    )


def serialize_dependency(
    dependency: WorkEntityScheduleDependency,
    tasks: dict[UUID, WorkEntityTask],
    milestones: dict[UUID, WorkEntityMilestone],
) -> WorkEntityScheduleDependencyRead:
    predecessor = dependency_predecessor(dependency)
    successor = dependency_successor(dependency)
    if predecessor[0] == "task":
        predecessor_item = tasks[predecessor[1]]
        predecessor_ref = task_ref(predecessor_item)
    else:
        predecessor_item = milestones[predecessor[1]]
        predecessor_ref = milestone_ref(predecessor_item)
    if successor[0] == "task":
        successor_item = tasks[successor[1]]
        successor_ref = task_ref(successor_item)
    else:
        successor_item = milestones[successor[1]]
        successor_ref = milestone_ref(successor_item)
    return WorkEntityScheduleDependencyRead(
        id=dependency.id,
        entity_id=dependency.entity_id,
        predecessor_type=predecessor[0],
        predecessor_id=predecessor[1],
        predecessor_ref=predecessor_ref,
        predecessor_title=predecessor_item.title,
        successor_type=successor[0],
        successor_id=successor[1],
        successor_ref=successor_ref,
        successor_title=successor_item.title,
        dependency_type=dependency.dependency_type,
        lag_days=dependency.lag_days,
        cascade_on_shift=dependency.cascade_on_shift,
        status=dependency.status,
        waiver_reason=dependency.waiver_reason,
        waived_by_id=dependency.waived_by_id,
        waived_by_name=None,
        waived_at=dependency.waived_at,
        created_by_id=dependency.created_by_id,
        created_at=dependency.created_at,
    )


def _node_forecast_finish(
    key: NodeKey,
    tasks: dict[UUID, WorkEntityTask],
    milestones: dict[UUID, WorkEntityMilestone],
    proposed_task_dates: dict[UUID, tuple[datetime, datetime]],
    proposed_milestone_dates: dict[UUID, datetime],
) -> datetime | None:
    if key[0] == "task":
        if key[1] in proposed_task_dates:
            return proposed_task_dates[key[1]][1]
        return tasks[key[1]].forecast_due_at
    return proposed_milestone_dates.get(
        key[1],
        milestones[key[1]].forecast_at,
    )


def _topological_reachable(
    source: NodeKey,
    dependencies: list[WorkEntityScheduleDependency],
) -> list[NodeKey]:
    outgoing: dict[NodeKey, list[NodeKey]] = defaultdict(list)
    incoming_count: dict[NodeKey, int] = defaultdict(int)
    reachable = {source}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for dependency in dependencies:
            if (
                dependency.status != "active"
                or not dependency.cascade_on_shift
            ):
                continue
            if dependency_predecessor(dependency) != current:
                continue
            successor = dependency_successor(dependency)
            outgoing[current].append(successor)
            if successor not in reachable:
                reachable.add(successor)
                queue.append(successor)
    for dependency in dependencies:
        predecessor = dependency_predecessor(dependency)
        successor = dependency_successor(dependency)
        if (
            dependency.cascade_on_shift
            and predecessor in reachable
            and successor in reachable
        ):
            incoming_count[successor] += 1
    topo_queue = deque(
        item for item in reachable if incoming_count.get(item, 0) == 0
    )
    ordered: list[NodeKey] = []
    while topo_queue:
        current = topo_queue.popleft()
        ordered.append(current)
        for successor in outgoing.get(current, []):
            incoming_count[successor] -= 1
            if incoming_count[successor] == 0:
                topo_queue.append(successor)
    return ordered


async def preview_milestone_reschedule(
    db: AsyncSession,
    entity: WorkEntity,
    milestone: WorkEntityMilestone,
    forecast_at: datetime,
    reason: str,
    cascade: bool,
) -> WorkEntityMilestoneReschedulePreviewRead:
    if milestone.status != "planned":
        raise HTTPException(
            status_code=409,
            detail="Переносить можно только непройденную контрольную точку",
        )
    if forecast_at == milestone.forecast_at:
        raise HTTPException(
            status_code=400,
            detail="Новая дата совпадает с текущим прогнозом",
        )
    if entity.starts_at and forecast_at < entity.starts_at:
        raise HTTPException(
            status_code=400,
            detail="Контрольная точка не может быть раньше начала проекта",
        )
    tasks, milestones, dependencies = await _schedule_rows(db, entity.id)
    source = node_key("milestone", milestone.id)
    is_acceleration = forecast_at < milestone.forecast_at
    proposed_task_dates: dict[UUID, tuple[datetime, datetime]] = {}
    proposed_milestone_dates: dict[UUID, datetime] = {
        milestone.id: forecast_at
    }
    changes: list[WorkEntityScheduleChangeRead] = [
        WorkEntityScheduleChangeRead(
            node_type="milestone",
            node_id=milestone.id,
            node_ref=milestone_ref(milestone),
            node_title=milestone.title,
            status=milestone_display_status(milestone),
            criticality=milestone.criticality,
            baseline_due_at=milestone.baseline_at,
            forecast_due_before=milestone.forecast_at,
            forecast_due_after=forecast_at,
            shift_days=_days_between(milestone.forecast_at, forecast_at),
        )
    ]
    conflicts: list[WorkEntityScheduleConflictRead] = []
    relevant_dependencies = [
        item for item in dependencies if item.cascade_on_shift
    ]
    if is_acceleration:
        for dependency in relevant_dependencies:
            if dependency_successor(dependency) != source:
                continue
            predecessor = dependency_predecessor(dependency)
            predecessor_finish = _node_forecast_finish(
                predecessor,
                tasks,
                milestones,
                proposed_task_dates,
                proposed_milestone_dates,
            )
            if predecessor_finish is None or predecessor_finish <= forecast_at:
                continue
            if predecessor[0] == "task":
                item = tasks[predecessor[1]]
                item_ref = task_ref(item)
                item_title = item.title
            else:
                item = milestones[predecessor[1]]
                item_ref = milestone_ref(item)
                item_title = item.title
            conflicts.append(
                WorkEntityScheduleConflictRead(
                    node_type=predecessor[0],
                    node_id=predecessor[1],
                    node_ref=item_ref,
                    node_title=item_title,
                    code="predecessor_after_accelerated_milestone",
                    message=(
                        "Предшествующий элемент заканчивается позже новой "
                        "даты. Сначала сократите или перепланируйте его прогноз."
                    ),
                )
            )
    ordered = (
        _topological_reachable(source, relevant_dependencies)
        if cascade and not is_acceleration
        else [source]
    )
    for current in ordered:
        if current == source:
            continue
        incoming = [
            item
            for item in relevant_dependencies
            if dependency_successor(item) == current
            and dependency_predecessor(item) in set(ordered)
        ]
        required_dates: list[datetime] = []
        for dependency in incoming:
            predecessor_finish = _node_forecast_finish(
                dependency_predecessor(dependency),
                tasks,
                milestones,
                proposed_task_dates,
                proposed_milestone_dates,
            )
            if predecessor_finish is not None:
                required_dates.append(
                    predecessor_finish + timedelta(days=dependency.lag_days)
                )
        if not required_dates:
            continue
        required_at = max(required_dates)
        if current[0] == "task":
            task = tasks[current[1]]
            if (
                task.forecast_starts_at is None
                or task.forecast_due_at is None
            ):
                conflicts.append(
                    WorkEntityScheduleConflictRead(
                        node_type="task",
                        node_id=task.id,
                        node_ref=task_ref(task),
                        node_title=task.title,
                        code="missing_schedule",
                        message=(
                            "Для автоматического переноса задаче нужны "
                            "прогнозные даты начала и окончания."
                        ),
                    )
                )
                continue
            if task.forecast_starts_at >= required_at:
                continue
            if task.status not in AUTO_SHIFT_TASK_STATUSES:
                conflicts.append(
                    WorkEntityScheduleConflictRead(
                        node_type="task",
                        node_id=task.id,
                        node_ref=task_ref(task),
                        node_title=task.title,
                        code="work_already_started",
                        message=(
                            "Задача уже выполняется или завершена; ее срок "
                            "руководитель должен скорректировать вручную."
                        ),
                    )
                )
                continue
            delta = required_at - task.forecast_starts_at
            next_start = required_at
            next_due = task.forecast_due_at + delta
            proposed_task_dates[task.id] = (next_start, next_due)
            changes.append(
                WorkEntityScheduleChangeRead(
                    node_type="task",
                    node_id=task.id,
                    node_ref=task_ref(task),
                    node_title=task.title,
                    status=task.status,
                    baseline_start_at=task.baseline_starts_at,
                    baseline_due_at=task.baseline_due_at,
                    forecast_start_before=task.forecast_starts_at,
                    forecast_start_after=next_start,
                    forecast_due_before=task.forecast_due_at,
                    forecast_due_after=next_due,
                    shift_days=_days_between(task.forecast_starts_at, next_start),
                )
            )
        else:
            next_milestone = milestones[current[1]]
            if next_milestone.forecast_at >= required_at:
                continue
            if next_milestone.status != "planned":
                conflicts.append(
                    WorkEntityScheduleConflictRead(
                        node_type="milestone",
                        node_id=next_milestone.id,
                        node_ref=milestone_ref(next_milestone),
                        node_title=next_milestone.title,
                        code="milestone_closed",
                        message=(
                            "Пройденная или отмененная контрольная точка "
                            "не переносится автоматически."
                        ),
                    )
                )
                continue
            proposed_milestone_dates[next_milestone.id] = required_at
            changes.append(
                WorkEntityScheduleChangeRead(
                    node_type="milestone",
                    node_id=next_milestone.id,
                    node_ref=milestone_ref(next_milestone),
                    node_title=next_milestone.title,
                    status=milestone_display_status(next_milestone),
                    criticality=next_milestone.criticality,
                    baseline_due_at=next_milestone.baseline_at,
                    forecast_due_before=next_milestone.forecast_at,
                    forecast_due_after=required_at,
                    shift_days=_days_between(
                        next_milestone.forecast_at,
                        required_at,
                    ),
                )
            )

    current_schedule_dates = [
        task.forecast_due_at
        for task in tasks.values()
        if task.status != "cancelled" and task.forecast_due_at is not None
    ] + [
        item.forecast_at
        for item in milestones.values()
        if item.status != "cancelled"
    ]
    proposed_schedule_dates = [
        proposed_task_dates.get(
            task.id,
            (task.forecast_starts_at, task.forecast_due_at),
        )[1]
        for task in tasks.values()
        if task.status != "cancelled"
        and (
            proposed_task_dates.get(
                task.id,
                (task.forecast_starts_at, task.forecast_due_at),
            )[1]
            is not None
        )
    ] + [
        proposed_milestone_dates.get(item.id, item.forecast_at)
        for item in milestones.values()
        if item.status != "cancelled"
    ]
    project_before = max(
        current_schedule_dates,
        default=entity.due_at,
    )
    project_after = max(
        proposed_schedule_dates,
        default=entity.due_at,
    )
    return WorkEntityMilestoneReschedulePreviewRead(
        entity_id=entity.id,
        milestone_id=milestone.id,
        schedule_revision=entity.schedule_revision,
        shift_days=_days_between(milestone.forecast_at, forecast_at),
        reason=reason,
        changes=changes,
        conflicts=conflicts,
        project_forecast_due_before=project_before,
        project_forecast_due_after=project_after,
        requires_confirmation=True,
    )


async def build_project_map(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    current_user: User,
) -> WorkEntityMapRead:
    workspace = await build_workspace(db, entity, access_role, current_user)
    stage_map = {stage.id: stage for stage in workspace.stages}
    links = list(
        (
            await db.execute(
                select(WorkEntityLink)
                .where(WorkEntityLink.entity_id == entity.id)
                .order_by(WorkEntityLink.position, WorkEntityLink.created_at)
            )
        ).scalars().all()
    )
    serialized_links = await serialize_links(db, links, current_user)
    root_id = f"entity:{entity.id}"
    root_start = (
        entity.forecast_starts_at
        or entity.starts_at
        or entity.created_at
    )
    nodes = [
        WorkEntityMapNode(
            id=root_id,
            node_type="entity",
            title=entity.title,
            status=entity.status,
            baseline_starts_at=entity.starts_at,
            baseline_due_at=entity.due_at,
            forecast_starts_at=entity.forecast_starts_at,
            forecast_due_at=entity.forecast_due_at,
            actual_at=entity.actual_due_at,
            starts_at=entity.forecast_starts_at,
            due_at=entity.forecast_due_at,
            occurred_at=root_start,
        )
    ]
    edges: list[WorkEntityMapEdge] = []
    for task in workspace.tasks:
        node_id = f"task:{task.id}"
        nodes.append(
            WorkEntityMapNode(
                id=node_id,
                node_type="task",
                ref=f"PRJ-{task.task_number}",
                title=task.title,
                status=task.status,
                baseline_starts_at=task.baseline_starts_at,
                baseline_due_at=task.baseline_due_at,
                forecast_starts_at=task.forecast_starts_at,
                forecast_due_at=task.forecast_due_at,
                actual_at=task.actual_due_at,
                stage_title=task.stage_title,
                stage_position=(
                    stage_map[task.stage_id].position
                    if task.stage_id in stage_map
                    else None
                ),
                starts_at=task.forecast_starts_at,
                due_at=task.forecast_due_at,
                occurred_at=task.created_at,
                assignee_name=task.assignee_name,
                parent_id=root_id,
            )
        )
    for milestone in workspace.milestones:
        node_id = f"milestone:{milestone.id}"
        nodes.append(
            WorkEntityMapNode(
                id=node_id,
                node_type="milestone",
                ref=f"КТ-{milestone.milestone_number}",
                title=milestone.title,
                status=milestone.display_status,
                criticality=milestone.criticality,
                baseline_due_at=milestone.baseline_at,
                forecast_due_at=milestone.forecast_at,
                actual_at=milestone.actual_at,
                stage_title=milestone.stage_title,
                stage_position=(
                    stage_map[milestone.stage_id].position
                    if milestone.stage_id in stage_map
                    else None
                ),
                due_at=milestone.forecast_at,
                occurred_at=milestone.created_at,
                assignee_name=milestone.decision_owner_name,
                parent_id=root_id,
            )
        )
    for dependency in workspace.dependencies:
        if dependency.status != "active":
            continue
        edges.append(
            WorkEntityMapEdge(
                id=f"dependency:{dependency.id}",
                edge_type="dependency",
                from_node_id=(
                    f"{dependency.predecessor_type}:{dependency.predecessor_id}"
                ),
                to_node_id=(
                    f"{dependency.successor_type}:{dependency.successor_id}"
                ),
            )
        )
    for artifact in workspace.artifacts:
        node_id = f"artifact:{artifact.id}"
        if artifact.task_id:
            parent_id = f"task:{artifact.task_id}"
        elif artifact.milestone_id:
            parent_id = f"milestone:{artifact.milestone_id}"
        else:
            parent_id = root_id
        nodes.append(
            WorkEntityMapNode(
                id=node_id,
                node_type="artifact",
                title=artifact.title,
                status=artifact.status,
                occurred_at=artifact.updated_at,
                parent_id=parent_id,
            )
        )
        edges.append(
            WorkEntityMapEdge(
                id=f"artifact:{artifact.id}",
                edge_type="artifact",
                from_node_id=parent_id,
                to_node_id=node_id,
            )
        )
    for link in serialized_links:
        node_id = f"link:{link.id}"
        nodes.append(
            WorkEntityMapNode(
                id=node_id,
                node_type="linked_object",
                title=link.target_title or "Ограниченный объект",
                status=link.target_status,
                forecast_starts_at=link.target_starts_at,
                forecast_due_at=link.target_due_at,
                starts_at=link.target_starts_at,
                due_at=link.target_due_at,
                occurred_at=link.created_at,
                parent_id=root_id,
                accessible=link.target_accessible,
            )
        )
        edges.append(
            WorkEntityMapEdge(
                id=f"link:{link.id}",
                edge_type="link",
                from_node_id=root_id,
                to_node_id=node_id,
            )
        )

    date_values: list[datetime] = [
        root_start,
        entity.forecast_due_at or entity.due_at or entity.updated_at,
    ]
    for node in nodes:
        date_values.extend(
            date_value
            for date_value in (
                node.baseline_starts_at,
                node.baseline_due_at,
                node.forecast_starts_at,
                node.forecast_due_at,
                node.actual_at,
                node.occurred_at,
            )
            if date_value is not None
        )
    range_start = min(date_values)
    range_end = max(date_values)
    if range_end <= range_start:
        range_end = range_start + timedelta(days=1)
    return WorkEntityMapRead(
        entity_id=entity.id,
        range_start=range_start,
        range_end=range_end,
        nodes=nodes,
        edges=edges,
        generated_at=utc_now(),
    )
