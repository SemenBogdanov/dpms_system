"""API for project stages, tasks, milestones, schedule, artifacts, and map."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_task_workspace_access
from app.models.user import User
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityStage,
    WorkEntityTask,
)
from app.schemas.work_entity import (
    WorkEntityArtifactCreate,
    WorkEntityArtifactRead,
    WorkEntityArtifactUpdate,
    WorkEntityEventRead,
    WorkEntityJournalEntryCreate,
    WorkEntityMapRead,
    WorkEntityMilestoneCreate,
    WorkEntityMilestoneRead,
    WorkEntityMilestoneReschedulePreviewRead,
    WorkEntityMilestoneRescheduleRequest,
    WorkEntityMilestoneUpdate,
    WorkEntityScheduleDependencyCreate,
    WorkEntityScheduleDependencyRead,
    WorkEntityScheduleDependencyWaiveRequest,
    WorkEntityStageCreate,
    WorkEntityStageRead,
    WorkEntityStageUpdate,
    WorkEntityTaskCreate,
    WorkEntityTaskRead,
    WorkEntityTaskUpdate,
    WorkEntityWorkspaceRead,
)
from app.services.work_entities import (
    get_entity_access,
    lock_entity_state,
    record_entity_event,
)
from app.services.work_entity_workspace import (
    AUTO_SHIFT_TASK_STATUSES,
    DEPENDENCY_GATED_TASK_STATUSES,
    build_project_map,
    build_workspace,
    dependency_columns,
    dependency_predecessor,
    dependency_successor,
    ensure_dependents_allow_reopen,
    ensure_predecessors_completed,
    ensure_workspace_mutable,
    lock_workspace_graph,
    milestone_display_status,
    milestone_ref,
    node_key,
    preview_milestone_reschedule,
    recalculate_project_forecast_due,
    serialize_dependency,
    task_ref,
    validate_assignee,
    validate_decision_owner,
    validate_milestone_baseline,
    validate_stage,
    validate_task_dates,
    would_create_dependency_cycle,
)

router = APIRouter()
PARTICIPANT_EXECUTION_FIELDS = {"status", "next_step", "waiting_for"}
PARTICIPANT_STATUSES = {"in_progress", "waiting", "blocked", "review", "done"}
SCHEDULE_FIELDS = {"forecast_starts_at", "forecast_due_at"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _change_rows(
    instance,
    changes: dict,
    before: dict,
    display_values: dict[str, tuple[object, object]] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for field in sorted(changes):
        before_value = before[field]
        after_value = getattr(instance, field)
        display = (display_values or {}).get(field)
        row = {
            "field": field,
            "from": jsonable_encoder(display[0] if display else before_value),
            "to": jsonable_encoder(display[1] if display else after_value),
        }
        if display:
            row["from_id"] = jsonable_encoder(before_value)
            row["to_id"] = jsonable_encoder(after_value)
        rows.append(row)
    return rows


async def _user_label(db: AsyncSession, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    return (
        await db.execute(select(User.full_name).where(User.id == user_id))
    ).scalar_one_or_none() or str(user_id)


async def _stage_label(
    db: AsyncSession,
    entity_id: UUID,
    stage_id: UUID | None,
) -> str | None:
    if stage_id is None:
        return None
    return (
        await db.execute(
            select(WorkEntityStage.title).where(
                WorkEntityStage.id == stage_id,
                WorkEntityStage.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none() or str(stage_id)


def _event_payload(
    object_type: str,
    object_id: UUID,
    object_ref: str | None,
    object_title: str,
    action: str,
    *,
    changes: list[dict] | None = None,
    reason: str | None = None,
    impact: dict | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "schema_version": 1,
        "object": {
            "type": object_type,
            "id": str(object_id),
            "ref": object_ref,
            "title": object_title,
        },
        "action": action,
        "changes": changes or [],
        "reason": reason,
        "impact": impact,
    }
    if extra:
        payload.update(extra)
    return payload


async def _entity_access_or_404(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> tuple[WorkEntity, str]:
    access = await get_entity_access(db, entity_id, user.id)
    if not access:
        raise HTTPException(status_code=404, detail="Проект или цель не найдены")
    return access


async def _editable_entity_or_404(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> tuple[WorkEntity, str]:
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    if access_role not in {"owner", "editor"}:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для планирования проекта",
        )
    ensure_workspace_mutable(entity)
    return entity, access_role


async def _task_or_404(
    db: AsyncSession,
    entity_id: UUID,
    task_id: UUID,
) -> WorkEntityTask:
    task = (
        await db.execute(
            select(WorkEntityTask).where(
                WorkEntityTask.id == task_id,
                WorkEntityTask.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Проектная задача не найдена")
    return task


async def _active_task_targets(
    db: AsyncSession,
    entity_id: UUID,
    task_id: UUID,
) -> list[WorkEntityScheduleDependency]:
    return list(
        (
            await db.execute(
                select(WorkEntityScheduleDependency).where(
                    WorkEntityScheduleDependency.entity_id == entity_id,
                    WorkEntityScheduleDependency.predecessor_task_id == task_id,
                    WorkEntityScheduleDependency.successor_milestone_id.is_not(None),
                    WorkEntityScheduleDependency.status == "active",
                )
            )
        ).scalars().all()
    )


async def _milestone_or_404(
    db: AsyncSession,
    entity_id: UUID,
    milestone_id: UUID,
) -> WorkEntityMilestone:
    milestone = (
        await db.execute(
            select(WorkEntityMilestone).where(
                WorkEntityMilestone.id == milestone_id,
                WorkEntityMilestone.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if not milestone:
        raise HTTPException(
            status_code=404,
            detail="Контрольная точка не найдена",
        )
    return milestone


async def _stage_or_404(
    db: AsyncSession,
    entity_id: UUID,
    stage_id: UUID,
) -> WorkEntityStage:
    stage = (
        await db.execute(
            select(WorkEntityStage).where(
                WorkEntityStage.id == stage_id,
                WorkEntityStage.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=404, detail="Этап проекта не найден")
    return stage


async def _artifact_or_404(
    db: AsyncSession,
    entity_id: UUID,
    artifact_id: UUID,
) -> WorkEntityArtifact:
    artifact = (
        await db.execute(
            select(WorkEntityArtifact).where(
                WorkEntityArtifact.id == artifact_id,
                WorkEntityArtifact.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Артефакт не найден")
    return artifact


async def _workspace_task_read(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    user: User,
    task_id: UUID,
) -> WorkEntityTaskRead:
    workspace = await build_workspace(db, entity, access_role, user)
    return next(item for item in workspace.tasks if item.id == task_id)


async def _workspace_milestone_read(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    user: User,
    milestone_id: UUID,
) -> WorkEntityMilestoneRead:
    workspace = await build_workspace(db, entity, access_role, user)
    return next(item for item in workspace.milestones if item.id == milestone_id)


async def _workspace_stage_read(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    user: User,
    stage_id: UUID,
) -> WorkEntityStageRead:
    workspace = await build_workspace(db, entity, access_role, user)
    return next(item for item in workspace.stages if item.id == stage_id)


async def _workspace_artifact_read(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
    user: User,
    artifact_id: UUID,
) -> WorkEntityArtifactRead:
    workspace = await build_workspace(db, entity, access_role, user)
    return next(item for item in workspace.artifacts if item.id == artifact_id)


@router.get("/{entity_id}/workspace", response_model=WorkEntityWorkspaceRead)
async def get_work_entity_workspace(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    return await build_workspace(db, entity, access_role, user)


@router.get("/{entity_id}/map", response_model=WorkEntityMapRead)
async def get_work_entity_map(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    return await build_project_map(db, entity, access_role, user)


@router.post(
    "/{entity_id}/stages",
    response_model=WorkEntityStageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_stage(
    entity_id: UUID,
    body: WorkEntityStageCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _editable_entity_or_404(db, entity_id, user)
    if body.source_type == "methodology" and not body.source_key:
        raise HTTPException(
            status_code=400,
            detail="Для этапа методологии нужен стабильный ключ источника",
        )
    stage = WorkEntityStage(
        entity_id=entity.id,
        title=body.title,
        description=body.description,
        completion_criteria=body.completion_criteria,
        guidance=body.guidance,
        status=body.status,
        source_type=body.source_type,
        source_key=body.source_key,
        source_snapshot=body.source_snapshot,
        position=body.position,
        created_by_id=user.id,
    )
    db.add(stage)
    await db.flush()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_stage_created",
        _event_payload(
            "stage",
            stage.id,
            None,
            stage.title,
            "created",
            changes=[
                {"field": "status", "from": None, "to": stage.status},
                {"field": "source_type", "from": None, "to": stage.source_type},
            ],
        ),
        object_type="stage",
        object_id=stage.id,
        object_title=stage.title,
        action="created",
    )
    await db.commit()
    return await _workspace_stage_read(
        db,
        entity,
        access_role,
        user,
        stage.id,
    )


@router.patch(
    "/{entity_id}/stages/{stage_id}",
    response_model=WorkEntityStageRead,
)
async def update_work_entity_stage(
    entity_id: UUID,
    stage_id: UUID,
    body: WorkEntityStageUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _editable_entity_or_404(db, entity_id, user)
    stage = await _stage_or_404(db, entity.id, stage_id)
    requested = body.model_dump(exclude_unset=True)
    changes = {
        field: value
        for field, value in requested.items()
        if getattr(stage, field) != value
    }
    if not changes:
        return await _workspace_stage_read(
            db,
            entity,
            access_role,
            user,
            stage.id,
        )
    if changes.get("status") in {"done", "cancelled"}:
        open_items = (
            await db.execute(
                select(
                    (
                        select(func.count(WorkEntityTask.id))
                        .where(
                            WorkEntityTask.stage_id == stage.id,
                            WorkEntityTask.status.not_in({"done", "cancelled"}),
                        )
                        .scalar_subquery()
                    )
                    + (
                        select(func.count(WorkEntityMilestone.id))
                        .where(
                            WorkEntityMilestone.stage_id == stage.id,
                            WorkEntityMilestone.status.not_in(
                                {"achieved", "cancelled"}
                            ),
                        )
                        .scalar_subquery()
                    )
                )
            )
        ).scalar_one()
        if open_items:
            raise HTTPException(
                status_code=409,
                detail="Сначала завершите или перенесите открытые элементы этапа",
            )
    before = {field: getattr(stage, field) for field in changes}
    for field, value in changes.items():
        setattr(stage, field, value)
    stage.updated_at = utc_now()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_stage_updated",
        _event_payload(
            "stage",
            stage.id,
            None,
            stage.title,
            "updated",
            changes=_change_rows(stage, changes, before),
        ),
        object_type="stage",
        object_id=stage.id,
        object_title=stage.title,
        action="updated",
    )
    await db.commit()
    return await _workspace_stage_read(
        db,
        entity,
        access_role,
        user,
        stage.id,
    )


@router.post(
    "/{entity_id}/tasks",
    response_model=WorkEntityTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_task(
    entity_id: UUID,
    body: WorkEntityTaskCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _editable_entity_or_404(db, entity_id, user)
    validate_task_dates(
        entity,
        body.baseline_starts_at,
        body.baseline_due_at,
        against_baseline=True,
    )
    await validate_stage(db, entity.id, body.stage_id)
    assignee = await validate_assignee(db, entity, body.assignee_id)
    if entity.entity_type == "project" and body.target_milestone_id is None:
        raise HTTPException(
            status_code=400,
            detail="Для проектной работы выберите контрольную точку",
        )
    target_milestone: WorkEntityMilestone | None = None
    if body.target_milestone_id is not None:
        target_milestone = await _milestone_or_404(
            db,
            entity.id,
            body.target_milestone_id,
        )
        if target_milestone.status != "planned":
            raise HTTPException(
                status_code=409,
                detail="Новая работа может готовить только запланированную точку",
            )
        if (
            body.baseline_due_at
            and body.baseline_due_at > target_milestone.forecast_at
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Работа должна завершиться не позже связанной "
                    "контрольной точки"
                ),
            )
    now = utc_now()
    task = WorkEntityTask(
        entity_id=entity.id,
        stage_id=body.stage_id,
        title=body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        assignee_id=body.assignee_id,
        created_by_id=user.id,
        acceptance_criteria=body.acceptance_criteria,
        next_step=body.next_step,
        waiting_for=body.waiting_for,
        baseline_starts_at=body.baseline_starts_at,
        baseline_due_at=body.baseline_due_at,
        forecast_starts_at=body.baseline_starts_at,
        forecast_due_at=body.baseline_due_at,
        actual_starts_at=(
            now
            if body.status
            in {"in_progress", "review", "done"}
            else None
        ),
        actual_due_at=now if body.status == "done" else None,
        introduced_after_baseline=entity.baseline_locked_at is not None,
        introduced_at_revision=(
            entity.schedule_revision + 1
            if entity.baseline_locked_at is not None
            else None
        ),
        position=body.position,
    )
    db.add(task)
    await db.flush()
    if target_milestone is not None:
        db.add(
            WorkEntityScheduleDependency(
                entity_id=entity.id,
                predecessor_task_id=task.id,
                successor_milestone_id=target_milestone.id,
                dependency_type="finish_to_start",
                lag_days=0,
                cascade_on_shift=True,
                status="active",
                created_by_id=user.id,
            )
        )
    entity.schedule_revision += 1
    await recalculate_project_forecast_due(db, entity)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_task_created",
        _event_payload(
            "task",
            task.id,
            task_ref(task),
            task.title,
            "created",
            changes=[
                {"field": "status", "from": None, "to": task.status},
                {"field": "priority", "from": None, "to": task.priority},
                {
                    "field": "assignee",
                    "from": None,
                    "to": assignee.full_name if assignee else None,
                },
                {
                    "field": "baseline_starts_at",
                    "from": None,
                    "to": jsonable_encoder(task.baseline_starts_at),
                },
                {
                    "field": "baseline_due_at",
                    "from": None,
                    "to": jsonable_encoder(task.baseline_due_at),
                },
                {
                    "field": "introduced_after_baseline",
                    "from": None,
                    "to": task.introduced_after_baseline,
                },
                {
                    "field": "introduced_at_revision",
                    "from": None,
                    "to": task.introduced_at_revision,
                },
            ],
            impact={
                "schedule_revision": entity.schedule_revision,
                "target_milestone_id": (
                    str(target_milestone.id) if target_milestone else None
                ),
                "target_milestone_title": (
                    target_milestone.title if target_milestone else None
                ),
            },
        ),
        object_type="task",
        object_id=task.id,
        object_ref=task_ref(task),
        object_title=task.title,
        action="created",
    )
    await db.commit()
    return await _workspace_task_read(db, entity, access_role, user, task.id)


@router.patch(
    "/{entity_id}/tasks/{task_id}",
    response_model=WorkEntityTaskRead,
)
async def update_work_entity_task(
    entity_id: UUID,
    task_id: UUID,
    body: WorkEntityTaskUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    ensure_workspace_mutable(entity)
    task = await _task_or_404(db, entity.id, task_id)
    requested = body.model_dump(exclude_unset=True)
    change_reason = requested.pop("change_reason", None)
    target_requested = "target_milestone_id" in requested
    requested_target_id = requested.get("target_milestone_id")
    can_manage = access_role in {"owner", "editor"}
    if not can_manage:
        if access_role != "participant" or task.assignee_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Изменять задачу может исполнитель или редактор",
            )
        forbidden_fields = set(requested) - PARTICIPANT_EXECUTION_FIELDS
        if forbidden_fields:
            raise HTTPException(
                status_code=403,
                detail="Исполнитель меняет только статус, следующий шаг и ожидание",
            )
        if (
            "status" in requested
            and requested["status"] not in PARTICIPANT_STATUSES
        ):
            raise HTTPException(
                status_code=403,
                detail="Этот статус может установить только редактор проекта",
            )
    requested.pop("target_milestone_id", None)
    changes = {
        field: value
        for field, value in requested.items()
        if getattr(task, field) != value
    }
    current_target_dependencies: list[WorkEntityScheduleDependency] = []
    current_target_id: UUID | None = None
    next_target: WorkEntityMilestone | None = None
    target_changed = False
    target_validation_required = (
        target_requested or "forecast_due_at" in changes
    )
    if target_validation_required:
        await lock_workspace_graph(db)
        current_target_dependencies = await _active_task_targets(
            db,
            entity.id,
            task.id,
        )
        if current_target_dependencies:
            current_target_id = current_target_dependencies[
                0
            ].successor_milestone_id
    if target_requested:
        if entity.entity_type == "project" and requested_target_id is None:
            raise HTTPException(
                status_code=400,
                detail="Проектная работа должна готовить контрольную точку",
            )
        target_changed = requested_target_id != current_target_id
        if requested_target_id is not None:
            next_target = await _milestone_or_404(
                db,
                entity.id,
                requested_target_id,
            )
            if target_changed and next_target.status != "planned":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Переназначить работу можно только на "
                        "запланированную контрольную точку"
                    ),
                )
    elif current_target_id is not None:
        next_target = await _milestone_or_404(
            db,
            entity.id,
            current_target_id,
        )
    next_due_at = changes.get("forecast_due_at", task.forecast_due_at)
    if (
        next_target is not None
        and next_due_at
        and next_due_at > next_target.forecast_at
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Работа должна завершиться не позже связанной "
                "контрольной точки"
            ),
        )
    if not changes and not target_changed:
        return await _workspace_task_read(db, entity, access_role, user, task.id)
    if (SCHEDULE_FIELDS & set(changes) or target_changed) and not change_reason:
        raise HTTPException(
            status_code=400,
            detail="Для изменения прогноза или маршрута укажите причину",
        )
    starts_at = changes.get("forecast_starts_at", task.forecast_starts_at)
    due_at = changes.get("forecast_due_at", task.forecast_due_at)
    validate_task_dates(
        entity,
        starts_at,
        due_at,
        against_baseline=False,
    )
    display_changes: dict[str, tuple[object, object]] = {}
    if "stage_id" in changes:
        next_stage = await validate_stage(db, entity.id, changes["stage_id"])
        display_changes["stage_id"] = (
            await _stage_label(db, entity.id, task.stage_id),
            next_stage.title if next_stage else None,
        )
    next_assignee = None
    if "assignee_id" in changes:
        next_assignee = await validate_assignee(
            db,
            entity,
            changes["assignee_id"],
        )
        display_changes["assignee_id"] = (
            await _user_label(db, task.assignee_id),
            next_assignee.full_name if next_assignee else None,
        )
    next_status = changes.get("status", task.status)
    if "status" in changes and next_status != task.status:
        await lock_workspace_graph(db)
        if (
            entity.entity_type == "project"
            and task.status == "cancelled"
            and next_status != "cancelled"
        ):
            if target_requested:
                effective_target = next_target
            else:
                current_target_dependencies = await _active_task_targets(
                    db,
                    entity.id,
                    task.id,
                )
                current_target_id = (
                    current_target_dependencies[0].successor_milestone_id
                    if len(current_target_dependencies) == 1
                    else None
                )
                effective_target = (
                    await _milestone_or_404(db, entity.id, current_target_id)
                    if current_target_id is not None
                    else None
                )
            route_will_be_replaced = target_requested and target_changed
            has_single_current_target = len(current_target_dependencies) == 1
            has_valid_target = (
                effective_target is not None
                and effective_target.status == "planned"
            )
            if (
                not (route_will_be_replaced or has_single_current_target)
                or not has_valid_target
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Чтобы вернуть работу, сначала переназначьте ее "
                        "на запланированную контрольную точку"
                    ),
                )
        if next_status in DEPENDENCY_GATED_TASK_STATUSES:
            await ensure_predecessors_completed(
                db,
                entity.id,
                node_key("task", task.id),
            )
        if task.status == "done" and next_status != "done":
            await ensure_dependents_allow_reopen(
                db,
                entity.id,
                node_key("task", task.id),
            )
    current_target_title = None
    if target_changed and current_target_id is not None:
        current_target_title = (
            await db.execute(
                select(WorkEntityMilestone.title).where(
                    WorkEntityMilestone.id == current_target_id,
                    WorkEntityMilestone.entity_id == entity.id,
                )
            )
        ).scalar_one_or_none()
    if target_changed:
        for dependency in current_target_dependencies:
            await db.delete(dependency)
        await db.flush()
        if next_target is not None:
            if await would_create_dependency_cycle(
                db,
                entity.id,
                node_key("task", task.id),
                node_key("milestone", next_target.id),
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Новая контрольная точка создаст цикл в маршруте",
                )
            db.add(
                WorkEntityScheduleDependency(
                    entity_id=entity.id,
                    predecessor_task_id=task.id,
                    successor_milestone_id=next_target.id,
                    dependency_type="finish_to_start",
                    lag_days=0,
                    cascade_on_shift=True,
                    status="active",
                    created_by_id=user.id,
                )
            )
    before = {field: getattr(task, field) for field in changes}
    for field, value in changes.items():
        setattr(task, field, value)
    now = utc_now()
    if "status" in changes:
        if task.status in {"in_progress", "review", "done"}:
            task.actual_starts_at = task.actual_starts_at or now
        if task.status == "done":
            task.actual_due_at = task.actual_due_at or now
        elif before["status"] == "done":
            task.actual_due_at = None
    if SCHEDULE_FIELDS & set(changes) or "status" in changes or target_changed:
        entity.schedule_revision += 1
        await recalculate_project_forecast_due(db, entity)
    task.updated_at = now
    event_changes = _change_rows(
        task,
        changes,
        before,
        display_changes,
    )
    if target_changed:
        event_changes.append(
            {
                "field": "target_milestone",
                "from": current_target_title,
                "to": next_target.title if next_target else None,
                "from_id": (
                    str(current_target_id) if current_target_id is not None else None
                ),
                "to_id": str(next_target.id) if next_target else None,
            }
        )
    event_extra = {
        "assignee_name": next_assignee.full_name if next_assignee else None,
    }
    if target_changed:
        event_extra.update(
            {
                "target_milestone_id": (
                    str(next_target.id) if next_target else None
                ),
                "target_milestone_title": (
                    next_target.title if next_target else None
                ),
            }
        )
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_task_updated",
        _event_payload(
            "task",
            task.id,
            task_ref(task),
            task.title,
            "updated",
            changes=event_changes,
            reason=change_reason,
            extra=event_extra,
        ),
        object_type="task",
        object_id=task.id,
        object_ref=task_ref(task),
        object_title=task.title,
        action="updated",
        reason=change_reason,
    )
    await db.commit()
    return await _workspace_task_read(db, entity, access_role, user, task.id)


@router.post(
    "/{entity_id}/tasks/{task_id}/journal",
    response_model=WorkEntityEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_work_entity_task_journal_entry(
    entity_id: UUID,
    task_id: UUID,
    body: WorkEntityJournalEntryCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    ensure_workspace_mutable(entity)
    task = await _task_or_404(db, entity.id, task_id)
    if access_role not in {"owner", "editor"} and not (
        access_role == "participant" and task.assignee_id == user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Запись может добавить исполнитель или редактор проекта",
        )
    payload = _event_payload(
        "task",
        task.id,
        task_ref(task),
        task.title,
        "journal_entry_added",
        extra={"entry_type": body.entry_type, "body": body.body},
    )
    event = record_entity_event(
        db,
        entity.id,
        user.id,
        "project_task_journal",
        payload,
        object_type="task",
        object_id=task.id,
        object_ref=task_ref(task),
        object_title=task.title,
        action="journal_entry_added",
    )
    await db.flush()
    await db.commit()
    return WorkEntityEventRead(
        id=event.id,
        entity_id=event.entity_id,
        actor_id=user.id,
        actor_name=user.full_name,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        object_ref=event.object_ref,
        object_title=event.object_title,
        action=event.action,
        reason=event.reason,
        correlation_id=event.correlation_id,
        payload=jsonable_encoder(event.payload),
        created_at=event.created_at,
    )


@router.post(
    "/{entity_id}/milestones",
    response_model=WorkEntityMilestoneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_milestone(
    entity_id: UUID,
    body: WorkEntityMilestoneCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _editable_entity_or_404(db, entity_id, user)
    if body.status != "planned":
        raise HTTPException(
            status_code=400,
            detail=(
                "Новая контрольная точка создается запланированной. "
                "Прохождение или отмена оформляются отдельным действием с причиной."
            ),
        )
    validate_milestone_baseline(entity, body.baseline_at)
    await validate_stage(db, entity.id, body.stage_id)
    decision_owner = await validate_decision_owner(
        db,
        entity,
        body.decision_owner_id,
    )
    now = utc_now()
    milestone = WorkEntityMilestone(
        entity_id=entity.id,
        stage_id=body.stage_id,
        title=body.title,
        description=body.description,
        status=body.status,
        criticality=body.criticality,
        criticality_reason=body.criticality_reason,
        acceptance_criteria=body.acceptance_criteria,
        decision_owner_id=body.decision_owner_id,
        created_by_id=user.id,
        baseline_at=body.baseline_at,
        forecast_at=body.baseline_at,
        actual_at=None,
        cancelled_at=None,
        introduced_after_baseline=entity.baseline_locked_at is not None,
        introduced_at_revision=(
            entity.schedule_revision + 1
            if entity.baseline_locked_at is not None
            else None
        ),
        position=body.position,
    )
    db.add(milestone)
    await db.flush()
    entity.schedule_revision += 1
    await recalculate_project_forecast_due(db, entity)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_milestone_created",
        _event_payload(
            "milestone",
            milestone.id,
            milestone_ref(milestone),
            milestone.title,
            "created",
            changes=[
                {"field": "status", "from": None, "to": milestone.status},
                {
                    "field": "criticality",
                    "from": None,
                    "to": milestone.criticality,
                },
                {
                    "field": "baseline_at",
                    "from": None,
                    "to": jsonable_encoder(milestone.baseline_at),
                },
                {
                    "field": "decision_owner",
                    "from": None,
                    "to": decision_owner.full_name if decision_owner else None,
                },
                {
                    "field": "introduced_after_baseline",
                    "from": None,
                    "to": milestone.introduced_after_baseline,
                },
                {
                    "field": "introduced_at_revision",
                    "from": None,
                    "to": milestone.introduced_at_revision,
                },
            ],
            reason=milestone.criticality_reason,
            impact={"schedule_revision": entity.schedule_revision},
        ),
        object_type="milestone",
        object_id=milestone.id,
        object_ref=milestone_ref(milestone),
        object_title=milestone.title,
        action="created",
        reason=milestone.criticality_reason,
    )
    await db.commit()
    return await _workspace_milestone_read(
        db,
        entity,
        access_role,
        user,
        milestone.id,
    )


@router.patch(
    "/{entity_id}/milestones/{milestone_id}",
    response_model=WorkEntityMilestoneRead,
)
async def update_work_entity_milestone(
    entity_id: UUID,
    milestone_id: UUID,
    body: WorkEntityMilestoneUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _editable_entity_or_404(db, entity_id, user)
    milestone = await _milestone_or_404(db, entity.id, milestone_id)
    requested = body.model_dump(exclude_unset=True)
    change_reason = requested.pop("change_reason", None)
    changes = {
        field: value
        for field, value in requested.items()
        if getattr(milestone, field) != value
    }
    if not changes:
        return await _workspace_milestone_read(
            db,
            entity,
            access_role,
            user,
            milestone.id,
        )
    next_criticality = changes.get("criticality", milestone.criticality)
    next_criticality_reason = changes.get(
        "criticality_reason",
        milestone.criticality_reason,
    )
    if next_criticality in {"key", "critical"} and not next_criticality_reason:
        raise HTTPException(
            status_code=400,
            detail="Обоснуйте ключевую или критическую контрольную точку",
        )
    display_changes: dict[str, tuple[object, object]] = {}
    if "stage_id" in changes:
        next_stage = await validate_stage(db, entity.id, changes["stage_id"])
        display_changes["stage_id"] = (
            await _stage_label(db, entity.id, milestone.stage_id),
            next_stage.title if next_stage else None,
        )
    if "decision_owner_id" in changes:
        next_decision_owner = await validate_decision_owner(
            db,
            entity,
            changes["decision_owner_id"],
        )
        display_changes["decision_owner_id"] = (
            await _user_label(db, milestone.decision_owner_id),
            next_decision_owner.full_name if next_decision_owner else None,
        )
    next_status = changes.get("status", milestone.status)
    if "status" in changes and next_status != milestone.status:
        await lock_workspace_graph(db)
        if next_status == "cancelled":
            linked_task = (
                await db.execute(
                    select(WorkEntityTask)
                    .join(
                        WorkEntityScheduleDependency,
                        and_(
                            WorkEntityScheduleDependency.entity_id
                            == WorkEntityTask.entity_id,
                            WorkEntityScheduleDependency.predecessor_task_id
                            == WorkEntityTask.id,
                        ),
                    )
                    .where(
                        WorkEntityTask.entity_id == entity.id,
                        WorkEntityTask.status != "cancelled",
                        WorkEntityScheduleDependency.successor_milestone_id
                        == milestone.id,
                        WorkEntityScheduleDependency.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if linked_task is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Сначала переназначьте или отмените связанную работу "
                        f"{task_ref(linked_task)} {linked_task.title}"
                    ),
                )
        if next_status == "achieved":
            await ensure_predecessors_completed(
                db,
                entity.id,
                node_key("milestone", milestone.id),
            )
        if milestone.status == "achieved" and next_status != "achieved":
            await ensure_dependents_allow_reopen(
                db,
                entity.id,
                node_key("milestone", milestone.id),
            )
        if not change_reason:
            raise HTTPException(
                status_code=400,
                detail="Для изменения статуса укажите причину",
            )
    before = {field: getattr(milestone, field) for field in changes}
    for field, value in changes.items():
        setattr(milestone, field, value)
    now = utc_now()
    if "status" in changes:
        if milestone.status == "achieved":
            milestone.actual_at = milestone.actual_at or now
            milestone.cancelled_at = None
        elif milestone.status == "cancelled":
            milestone.cancelled_at = now
            milestone.actual_at = None
        else:
            milestone.actual_at = None
            milestone.cancelled_at = None
        entity.schedule_revision += 1
        await recalculate_project_forecast_due(db, entity)
    milestone.updated_at = now
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_milestone_updated",
        _event_payload(
            "milestone",
            milestone.id,
            milestone_ref(milestone),
            milestone.title,
            "updated",
            changes=_change_rows(
                milestone,
                changes,
                before,
                display_changes,
            ),
            reason=change_reason,
        ),
        object_type="milestone",
        object_id=milestone.id,
        object_ref=milestone_ref(milestone),
        object_title=milestone.title,
        action="updated",
        reason=change_reason,
    )
    await db.commit()
    return await _workspace_milestone_read(
        db,
        entity,
        access_role,
        user,
        milestone.id,
    )


@router.post(
    "/{entity_id}/milestones/{milestone_id}/journal",
    response_model=WorkEntityEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_work_entity_milestone_journal_entry(
    entity_id: UUID,
    milestone_id: UUID,
    body: WorkEntityJournalEntryCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    ensure_workspace_mutable(entity)
    if access_role == "viewer":
        raise HTTPException(
            status_code=403,
            detail="Наблюдатель не может вести журнал проекта",
        )
    milestone = await _milestone_or_404(db, entity.id, milestone_id)
    payload = _event_payload(
        "milestone",
        milestone.id,
        milestone_ref(milestone),
        milestone.title,
        "journal_entry_added",
        extra={"entry_type": body.entry_type, "body": body.body},
    )
    event = record_entity_event(
        db,
        entity.id,
        user.id,
        "project_milestone_journal",
        payload,
        object_type="milestone",
        object_id=milestone.id,
        object_ref=milestone_ref(milestone),
        object_title=milestone.title,
        action="journal_entry_added",
    )
    await db.flush()
    await db.commit()
    return WorkEntityEventRead(
        id=event.id,
        entity_id=event.entity_id,
        actor_id=user.id,
        actor_name=user.full_name,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        object_ref=event.object_ref,
        object_title=event.object_title,
        action=event.action,
        reason=event.reason,
        correlation_id=event.correlation_id,
        payload=jsonable_encoder(event.payload),
        created_at=event.created_at,
    )


async def _load_schedule_nodes(
    db: AsyncSession,
    entity_id: UUID,
) -> tuple[dict[UUID, WorkEntityTask], dict[UUID, WorkEntityMilestone]]:
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
    return tasks, milestones


@router.post(
    "/{entity_id}/dependencies",
    response_model=WorkEntityScheduleDependencyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_dependency(
    entity_id: UUID,
    body: WorkEntityScheduleDependencyCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _editable_entity_or_404(db, entity_id, user)
    await lock_workspace_graph(db)
    tasks, milestones = await _load_schedule_nodes(db, entity.id)
    predecessor = node_key(body.predecessor_type, body.predecessor_id)
    successor = node_key(body.successor_type, body.successor_id)
    if (
        predecessor[1]
        not in (tasks if predecessor[0] == "task" else milestones)
        or successor[1]
        not in (tasks if successor[0] == "task" else milestones)
    ):
        raise HTTPException(
            status_code=404,
            detail="Один из элементов графика не найден в проекте",
        )
    if (
        entity.entity_type == "project"
        and predecessor[0] == "task"
        and successor[0] == "milestone"
    ):
        task = tasks[predecessor[1]]
        milestone = milestones[successor[1]]
        if task.status == "cancelled":
            raise HTTPException(
                status_code=409,
                detail="Отмененной работе нельзя назначить контрольную точку",
            )
        if milestone.status != "planned":
            raise HTTPException(
                status_code=409,
                detail="Работу можно направить только к запланированной точке",
            )
        existing_target = (
            await db.execute(
                select(WorkEntityScheduleDependency.id).where(
                    WorkEntityScheduleDependency.entity_id == entity.id,
                    WorkEntityScheduleDependency.predecessor_task_id == task.id,
                    WorkEntityScheduleDependency.successor_milestone_id.is_not(
                        None
                    ),
                    WorkEntityScheduleDependency.status == "active",
                )
            )
        ).scalar_one_or_none()
        if existing_target is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "У работы уже есть контрольная точка. "
                    "Измените ее в карточке работы с указанием причины."
                ),
            )
        if (
            task.forecast_due_at is not None
            and task.forecast_due_at > milestone.forecast_at
        ):
            raise HTTPException(
                status_code=400,
                detail="Работа завершается позже выбранной контрольной точки",
            )
    if await would_create_dependency_cycle(
        db,
        entity.id,
        predecessor,
        successor,
    ):
        raise HTTPException(
            status_code=409,
            detail="Эта зависимость создаст цикл в проекте",
        )
    columns = dependency_columns(
        body.predecessor_type,
        body.predecessor_id,
        body.successor_type,
        body.successor_id,
    )
    duplicate = (
        await db.execute(
            select(WorkEntityScheduleDependency.id).where(
                WorkEntityScheduleDependency.entity_id == entity.id,
                WorkEntityScheduleDependency.predecessor_task_id.is_(
                    columns["predecessor_task_id"]
                )
                if columns["predecessor_task_id"] is None
                else WorkEntityScheduleDependency.predecessor_task_id
                == columns["predecessor_task_id"],
                WorkEntityScheduleDependency.predecessor_milestone_id.is_(
                    columns["predecessor_milestone_id"]
                )
                if columns["predecessor_milestone_id"] is None
                else WorkEntityScheduleDependency.predecessor_milestone_id
                == columns["predecessor_milestone_id"],
                WorkEntityScheduleDependency.successor_task_id.is_(
                    columns["successor_task_id"]
                )
                if columns["successor_task_id"] is None
                else WorkEntityScheduleDependency.successor_task_id
                == columns["successor_task_id"],
                WorkEntityScheduleDependency.successor_milestone_id.is_(
                    columns["successor_milestone_id"]
                )
                if columns["successor_milestone_id"] is None
                else WorkEntityScheduleDependency.successor_milestone_id
                == columns["successor_milestone_id"],
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Такая зависимость уже существует")
    predecessor_complete = (
        tasks[predecessor[1]].status == "done"
        if predecessor[0] == "task"
        else milestones[predecessor[1]].status == "achieved"
    )
    successor_started = (
        successor[0] == "task"
        and tasks[successor[1]].status in DEPENDENCY_GATED_TASK_STATUSES
    ) or (
        successor[0] == "milestone"
        and milestones[successor[1]].status == "achieved"
    )
    successor_cancelled = (
        successor[0] == "task"
        and tasks[successor[1]].status == "cancelled"
    ) or (
        successor[0] == "milestone"
        and milestones[successor[1]].status == "cancelled"
    )
    if successor_cancelled:
        raise HTTPException(
            status_code=409,
            detail="Нельзя добавлять зависимость к отмененному элементу",
        )
    if successor_started and not predecessor_complete:
        raise HTTPException(
            status_code=409,
            detail=(
                "Нельзя добавить незавершенного предшественника к уже "
                "начатому или пройденному элементу"
            ),
        )
    dependency = WorkEntityScheduleDependency(
        entity_id=entity.id,
        **columns,
        dependency_type=body.dependency_type,
        lag_days=body.lag_days,
        cascade_on_shift=body.cascade_on_shift,
        status="active",
        created_by_id=user.id,
    )
    db.add(dependency)
    await db.flush()
    entity.schedule_revision += 1
    serialized = serialize_dependency(dependency, tasks, milestones)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_dependency_added",
        _event_payload(
            "dependency",
            dependency.id,
            None,
            (
                f"{serialized.predecessor_ref} → "
                f"{serialized.successor_ref}"
            ),
            "created",
            changes=[
                {
                    "field": "predecessor",
                    "from": None,
                    "to": (
                        f"{serialized.predecessor_ref} "
                        f"{serialized.predecessor_title}"
                    ),
                },
                {
                    "field": "successor",
                    "from": None,
                    "to": (
                        f"{serialized.successor_ref} "
                        f"{serialized.successor_title}"
                    ),
                },
                {"field": "lag_days", "from": None, "to": body.lag_days},
            ],
        ),
        object_type="dependency",
        object_id=dependency.id,
        object_title=(
            f"{serialized.predecessor_ref} → {serialized.successor_ref}"
        ),
        action="created",
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Такая зависимость уже существует",
        ) from exc
    return serialized


@router.post(
    "/{entity_id}/dependencies/{dependency_id}/waive",
    response_model=WorkEntityScheduleDependencyRead,
)
async def waive_work_entity_dependency(
    entity_id: UUID,
    dependency_id: UUID,
    body: WorkEntityScheduleDependencyWaiveRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _editable_entity_or_404(db, entity_id, user)
    await lock_workspace_graph(db)
    dependency = (
        await db.execute(
            select(WorkEntityScheduleDependency).where(
                WorkEntityScheduleDependency.id == dependency_id,
                WorkEntityScheduleDependency.entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    if not dependency:
        raise HTTPException(status_code=404, detail="Зависимость не найдена")
    if dependency.status == "waived":
        raise HTTPException(
            status_code=409,
            detail="Исключение для этой зависимости уже зафиксировано",
        )
    tasks, milestones = await _load_schedule_nodes(db, entity.id)
    predecessor = dependency_predecessor(dependency)
    predecessor_item = (
        tasks[predecessor[1]]
        if predecessor[0] == "task"
        else milestones[predecessor[1]]
    )
    if predecessor_item.status != "cancelled":
        raise HTTPException(
            status_code=409,
            detail=(
                "Снять блокировку можно только после отмены предшественника. "
                "Для обычного изменения последовательности удалите зависимость."
            ),
        )
    dependency.status = "waived"
    dependency.waiver_reason = body.reason
    dependency.waived_by_id = user.id
    dependency.waived_at = datetime.now(timezone.utc)
    entity.schedule_revision += 1
    serialized = serialize_dependency(dependency, tasks, milestones)
    serialized.waived_by_name = user.full_name or user.email
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_dependency_waived",
        _event_payload(
            "dependency",
            dependency.id,
            None,
            f"{serialized.predecessor_ref} → {serialized.successor_ref}",
            "waived",
            changes=[
                {"field": "status", "from": "active", "to": "waived"},
                {
                    "field": "waiver_reason",
                    "from": None,
                    "to": body.reason,
                },
            ],
            reason=body.reason,
        ),
        object_type="dependency",
        object_id=dependency.id,
        object_title=(
            f"{serialized.predecessor_ref} → {serialized.successor_ref}"
        ),
        action="waived",
        reason=body.reason,
    )
    await db.commit()
    return serialized


@router.delete(
    "/{entity_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_work_entity_dependency(
    entity_id: UUID,
    dependency_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _editable_entity_or_404(db, entity_id, user)
    await lock_workspace_graph(db)
    dependency = (
        await db.execute(
            select(WorkEntityScheduleDependency).where(
                WorkEntityScheduleDependency.id == dependency_id,
                WorkEntityScheduleDependency.entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    if not dependency:
        raise HTTPException(status_code=404, detail="Зависимость не найдена")
    tasks, milestones = await _load_schedule_nodes(db, entity.id)
    if (
        entity.entity_type == "project"
        and dependency.status == "active"
        and dependency.predecessor_task_id is not None
        and dependency.successor_milestone_id is not None
    ):
        task = tasks[dependency.predecessor_task_id]
        remaining_targets = (
            await db.execute(
                select(func.count(WorkEntityScheduleDependency.id)).where(
                    WorkEntityScheduleDependency.entity_id == entity.id,
                    WorkEntityScheduleDependency.predecessor_task_id == task.id,
                    WorkEntityScheduleDependency.successor_milestone_id.is_not(
                        None
                    ),
                    WorkEntityScheduleDependency.status == "active",
                    WorkEntityScheduleDependency.id != dependency.id,
                )
            )
        ).scalar_one()
        if task.status != "cancelled" and remaining_targets == 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Последнюю связь работы с контрольной точкой удалить нельзя. "
                    "Переназначьте точку в карточке работы или отмените работу."
                ),
            )
    serialized = serialize_dependency(dependency, tasks, milestones)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_dependency_removed",
        _event_payload(
            "dependency",
            dependency.id,
            None,
            f"{serialized.predecessor_ref} → {serialized.successor_ref}",
            "removed",
        ),
        object_type="dependency",
        object_id=dependency.id,
        object_title=(
            f"{serialized.predecessor_ref} → {serialized.successor_ref}"
        ),
        action="removed",
    )
    await db.delete(dependency)
    entity.schedule_revision += 1
    await db.commit()


@router.post(
    "/{entity_id}/milestones/{milestone_id}/reschedule/preview",
    response_model=WorkEntityMilestoneReschedulePreviewRead,
)
async def preview_work_entity_milestone_reschedule(
    entity_id: UUID,
    milestone_id: UUID,
    body: WorkEntityMilestoneRescheduleRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity, _ = await _editable_entity_or_404(db, entity_id, user)
    milestone = await _milestone_or_404(db, entity.id, milestone_id)
    if (
        body.expected_revision is not None
        and body.expected_revision != entity.schedule_revision
    ):
        raise HTTPException(
            status_code=409,
            detail="График уже изменился. Обновите данные и повторите расчет.",
        )
    return await preview_milestone_reschedule(
        db,
        entity,
        milestone,
        body.forecast_at,
        body.reason,
        body.cascade,
    )


@router.post(
    "/{entity_id}/milestones/{milestone_id}/reschedule/apply",
    response_model=WorkEntityMilestoneReschedulePreviewRead,
)
async def apply_work_entity_milestone_reschedule(
    entity_id: UUID,
    milestone_id: UUID,
    body: WorkEntityMilestoneRescheduleRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _editable_entity_or_404(db, entity_id, user)
    await lock_workspace_graph(db)
    milestone = await _milestone_or_404(db, entity.id, milestone_id)
    if body.expected_revision is None:
        raise HTTPException(
            status_code=400,
            detail="Перед применением выполните предварительный расчет",
        )
    if body.expected_revision != entity.schedule_revision:
        raise HTTPException(
            status_code=409,
            detail="График уже изменился. Обновите данные и повторите расчет.",
        )
    preview = await preview_milestone_reschedule(
        db,
        entity,
        milestone,
        body.forecast_at,
        body.reason,
        body.cascade,
    )
    if preview.conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Автоматический перенос остановлен: есть элементы, "
                    "требующие решения руководителя проекта."
                ),
                "conflicts": jsonable_encoder(preview.conflicts),
            },
        )
    tasks, milestones = await _load_schedule_nodes(db, entity.id)
    correlation_id = uuid4()
    for change in preview.changes:
        if change.node_type == "task":
            item = tasks[change.node_id]
            before = {
                "forecast_starts_at": item.forecast_starts_at,
                "forecast_due_at": item.forecast_due_at,
            }
            item.forecast_starts_at = change.forecast_start_after
            item.forecast_due_at = change.forecast_due_after
            item.updated_at = utc_now()
            object_ref = task_ref(item)
            object_type = "task"
        else:
            item = milestones[change.node_id]
            before = {"forecast_at": item.forecast_at}
            item.forecast_at = change.forecast_due_after
            item.reschedule_reason = body.reason
            item.reschedule_count += 1
            item.updated_at = utc_now()
            object_ref = milestone_ref(item)
            object_type = "milestone"
        field_changes = [
            {
                "field": field,
                "from": jsonable_encoder(value),
                "to": jsonable_encoder(getattr(item, field)),
            }
            for field, value in before.items()
        ]
        record_entity_event(
            db,
            entity.id,
            user.id,
            "project_schedule_item_shifted",
            _event_payload(
                object_type,
                item.id,
                object_ref,
                item.title,
                "forecast_shifted",
                changes=field_changes,
                reason=body.reason,
                impact={
                    "shift_days": change.shift_days,
                    "source_milestone_id": str(milestone.id),
                    "cascade": body.cascade,
                },
            ),
            object_type=object_type,
            object_id=item.id,
            object_ref=object_ref,
            object_title=item.title,
            action="forecast_shifted",
            reason=body.reason,
            correlation_id=correlation_id,
        )
    entity.forecast_due_at = preview.project_forecast_due_after
    entity.schedule_revision += 1
    entity.updated_at = utc_now()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_schedule_rescheduled",
        _event_payload(
            "milestone",
            milestone.id,
            milestone_ref(milestone),
            milestone.title,
            "schedule_rescheduled",
            reason=body.reason,
            impact={
                "affected_count": len(preview.changes),
                "cascade": body.cascade,
                "project_forecast_due_before": jsonable_encoder(
                    preview.project_forecast_due_before
                ),
                "project_forecast_due_after": jsonable_encoder(
                    preview.project_forecast_due_after
                ),
            },
        ),
        object_type="milestone",
        object_id=milestone.id,
        object_ref=milestone_ref(milestone),
        object_title=milestone.title,
        action="schedule_rescheduled",
        reason=body.reason,
        correlation_id=correlation_id,
    )
    await db.commit()
    return preview.model_copy(
        update={"schedule_revision": entity.schedule_revision}
    )


async def _validate_artifact_parent(
    db: AsyncSession,
    entity_id: UUID,
    task_id: UUID | None,
    milestone_id: UUID | None,
) -> None:
    if task_id and milestone_id:
        raise HTTPException(
            status_code=400,
            detail="Артефакт привязывается к одному элементу графика",
        )
    if task_id:
        await _task_or_404(db, entity_id, task_id)
    if milestone_id:
        await _milestone_or_404(db, entity_id, milestone_id)


def _validate_artifact_semantics(
    artifact_type: str,
    task_id: UUID | None,
    milestone_id: UUID | None,
) -> None:
    if artifact_type == "evidence" and (
        milestone_id is None or task_id is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Подтверждение должно быть привязано к контрольной точке",
        )


@router.post(
    "/{entity_id}/artifacts",
    response_model=WorkEntityArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_artifact(
    entity_id: UUID,
    body: WorkEntityArtifactCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    ensure_workspace_mutable(entity)
    if access_role == "viewer":
        raise HTTPException(
            status_code=403,
            detail="Наблюдатель не может добавлять артефакты",
        )
    await _validate_artifact_parent(
        db,
        entity.id,
        body.task_id,
        body.milestone_id,
    )
    _validate_artifact_semantics(
        body.artifact_type,
        body.task_id,
        body.milestone_id,
    )
    artifact = WorkEntityArtifact(
        entity_id=entity.id,
        task_id=body.task_id,
        milestone_id=body.milestone_id,
        artifact_type=body.artifact_type,
        title=body.title,
        body=body.body,
        url=body.url,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(artifact)
    await db.flush()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_artifact_created",
        _event_payload(
            "artifact",
            artifact.id,
            None,
            artifact.title,
            "created",
            changes=[
                {
                    "field": "artifact_type",
                    "from": None,
                    "to": artifact.artifact_type,
                }
            ],
            extra={
                "task_id": str(artifact.task_id) if artifact.task_id else None,
                "milestone_id": (
                    str(artifact.milestone_id)
                    if artifact.milestone_id
                    else None
                ),
            },
        ),
        object_type="artifact",
        object_id=artifact.id,
        object_title=artifact.title,
        action="created",
    )
    await db.commit()
    return await _workspace_artifact_read(
        db,
        entity,
        access_role,
        user,
        artifact.id,
    )


@router.patch(
    "/{entity_id}/artifacts/{artifact_id}",
    response_model=WorkEntityArtifactRead,
)
async def update_work_entity_artifact(
    entity_id: UUID,
    artifact_id: UUID,
    body: WorkEntityArtifactUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _entity_access_or_404(db, entity_id, user)
    ensure_workspace_mutable(entity)
    artifact = await _artifact_or_404(db, entity.id, artifact_id)
    can_manage = access_role in {"owner", "editor"}
    if not can_manage and not (
        access_role == "participant" and artifact.created_by_id == user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Изменять артефакт может автор или редактор проекта",
        )
    requested = body.model_dump(exclude_unset=True)
    changes = {
        field: value
        for field, value in requested.items()
        if getattr(artifact, field) != value
    }
    if not changes:
        return await _workspace_artifact_read(
            db,
            entity,
            access_role,
            user,
            artifact.id,
        )
    next_task_id = changes.get("task_id", artifact.task_id)
    next_milestone_id = changes.get("milestone_id", artifact.milestone_id)
    next_artifact_type = changes.get(
        "artifact_type",
        artifact.artifact_type,
    )
    next_body = changes.get("body", artifact.body)
    next_url = changes.get("url", artifact.url)
    if not next_body and not next_url:
        raise HTTPException(
            status_code=400,
            detail="Добавьте текст или ссылку",
        )
    if next_url and not next_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="Ссылка должна начинаться с http:// или https://",
        )
    await _validate_artifact_parent(
        db,
        entity.id,
        next_task_id,
        next_milestone_id,
    )
    _validate_artifact_semantics(
        next_artifact_type,
        next_task_id,
        next_milestone_id,
    )
    before = {field: getattr(artifact, field) for field in changes}
    for field, value in changes.items():
        setattr(artifact, field, value)
    artifact.updated_by_id = user.id
    artifact.updated_at = utc_now()
    if artifact.status == "archived":
        artifact.archived_at = artifact.archived_at or utc_now()
    else:
        artifact.archived_at = None
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_artifact_updated",
        _event_payload(
            "artifact",
            artifact.id,
            None,
            artifact.title,
            "updated",
            changes=_change_rows(artifact, changes, before),
        ),
        object_type="artifact",
        object_id=artifact.id,
        object_title=artifact.title,
        action="updated",
    )
    await db.commit()
    return await _workspace_artifact_read(
        db,
        entity,
        access_role,
        user,
        artifact.id,
    )
