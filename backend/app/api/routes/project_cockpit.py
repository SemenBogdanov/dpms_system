"""Guided project creation and project-level management commands."""
import math
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_task_workspace_access
from app.models.contact import Contact
from app.models.user import User
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityTask,
)
from app.schemas.project_cockpit import (
    GuidedProjectCreate,
    GuidedProjectCreated,
    ProjectCharterChangePreview,
    ProjectCharterChangeRequest,
    ProjectCharterFieldChange,
    ProjectDeadlineChangePreview,
    ProjectDeadlineChangeRequest,
    ProjectDeadlineConflict,
    ProjectDecisionCreate,
    ProjectWorkCreate,
    ProjectWorkCreated,
)
from app.services.work_entities import (
    get_entity_access,
    lock_entity_state,
    record_entity_event,
)
from app.services.work_entity_workspace import (
    recalculate_project_forecast_due,
    validate_assignee,
    validate_decision_owner,
    validate_task_dates,
)

router = APIRouter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _shift_days(before: datetime | None, after: datetime) -> int:
    if before is None:
        return 0
    days = (after - before).total_seconds() / 86400
    if days == 0:
        return 0
    return math.ceil(days) if days > 0 else math.floor(days)


async def _editable_entity(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> WorkEntity:
    access = await get_entity_access(db, entity_id, user.id)
    if not access:
        raise HTTPException(status_code=404, detail="Проект не найден")
    entity, role = access
    if role not in {"owner", "editor"}:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для управления проектом",
        )
    if entity.status not in {"draft", "active", "paused"}:
        raise HTTPException(
            status_code=409,
            detail="Завершенный или архивный проект нельзя изменять",
        )
    return entity


async def _validate_guided_members(
    db: AsyncSession,
    owner: User,
    member_ids: set[UUID],
) -> dict[UUID, User]:
    if owner.id in member_ids:
        raise HTTPException(
            status_code=400,
            detail="Владелец уже входит в команду проекта",
        )
    if not member_ids:
        return {}
    users = list(
        (
            await db.execute(
                select(User).where(
                    User.id.in_(member_ids),
                    User.is_active.is_(True),
                )
            )
        ).scalars().all()
    )
    if len(users) != len(member_ids):
        raise HTTPException(
            status_code=400,
            detail="Один из выбранных участников недоступен",
        )
    accepted_rows = (
        await db.execute(
            select(Contact.requester_id, Contact.recipient_id).where(
                Contact.status == "accepted",
                or_(
                    and_(
                        Contact.requester_id == owner.id,
                        Contact.recipient_id.in_(member_ids),
                    ),
                    and_(
                        Contact.recipient_id == owner.id,
                        Contact.requester_id.in_(member_ids),
                    ),
                ),
            )
        )
    ).all()
    accepted_ids = {
        recipient_id if requester_id == owner.id else requester_id
        for requester_id, recipient_id in accepted_rows
    }
    if accepted_ids != member_ids:
        raise HTTPException(
            status_code=403,
            detail=(
                "В команду можно добавить только принятые контакты. "
                "Сначала подтвердите контакт в разделе «Контакты»."
            ),
        )
    return {user.id: user for user in users}


@router.post(
    "/projects",
    response_model=GuidedProjectCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_guided_project(
    body: GuidedProjectCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Create a complete draft atomically from an outcome-oriented plan."""
    member_roles = {member.user_id: member.role for member in body.members}
    member_users = await _validate_guided_members(
        db,
        user,
        set(member_roles),
    )
    assignable_people = {
        user.id,
        *(
            member_id
            for member_id, role in member_roles.items()
            if role in {"participant", "editor"}
        ),
    }
    referenced_people = {
        person_id
        for person_id in [
            *(item.decision_owner_id for item in body.milestones),
            *(item.assignee_id for item in body.tasks),
        ]
        if person_id is not None
    }
    if not referenced_people.issubset(assignable_people):
        raise HTTPException(
            status_code=400,
            detail="Исполнитель или владелец решения не входит в команду проекта",
        )

    correlation_id = uuid.uuid4()
    entity = WorkEntity(
        owner_id=user.id,
        entity_type="project",
        title=body.title,
        description=None,
        outcome_statement=body.outcome_statement,
        success_criteria=body.success_criteria,
        constraints=(body.constraints or "").strip() or None,
        status="draft",
        visibility="shared" if body.members else "private",
        starts_at=body.starts_at,
        due_at=body.due_at,
        target_due_at=body.due_at,
        forecast_starts_at=body.starts_at,
        forecast_due_at=body.due_at,
        actual_starts_at=None,
        actual_due_at=None,
        planning_mode="free",
        baseline_locked_at=None,
        baseline_locked_by_id=None,
        schedule_revision=1,
        tags=[],
        details_json={"creation_flow": "guided_outcome_v1"},
    )
    db.add(entity)
    await db.flush()

    for member in body.members:
        db.add(
            WorkEntityMember(
                entity_id=entity.id,
                user_id=member.user_id,
                role=member.role,
                created_by_id=user.id,
            )
        )

    milestones: list[WorkEntityMilestone] = []
    for position, draft in enumerate(body.milestones):
        milestone = WorkEntityMilestone(
            entity_id=entity.id,
            stage_id=None,
            title=draft.title,
            description=None,
            status="planned",
            criticality=draft.criticality,
            criticality_reason=(
                (draft.criticality_reason or "").strip() or None
            ),
            acceptance_criteria=draft.acceptance_criteria,
            decision_owner_id=draft.decision_owner_id,
            created_by_id=user.id,
            baseline_at=draft.baseline_at,
            forecast_at=draft.baseline_at,
            actual_at=None,
            cancelled_at=None,
            introduced_after_baseline=False,
            introduced_at_revision=None,
            position=position,
        )
        db.add(milestone)
        milestones.append(milestone)
    await db.flush()

    tasks: list[tuple[WorkEntityTask, int]] = []
    for position, draft in enumerate(body.tasks):
        task = WorkEntityTask(
            entity_id=entity.id,
            stage_id=None,
            title=draft.title,
            description=None,
            status="planned",
            priority=draft.priority,
            assignee_id=draft.assignee_id,
            created_by_id=user.id,
            acceptance_criteria=draft.acceptance_criteria,
            next_step=None,
            waiting_for=None,
            baseline_starts_at=draft.baseline_starts_at,
            baseline_due_at=draft.baseline_due_at,
            forecast_starts_at=draft.baseline_starts_at,
            forecast_due_at=draft.baseline_due_at,
            actual_starts_at=None,
            actual_due_at=None,
            introduced_after_baseline=False,
            introduced_at_revision=None,
            position=position,
        )
        db.add(task)
        tasks.append((task, draft.target_milestone_index))
    await db.flush()

    for index in range(1, len(milestones)):
        db.add(
            WorkEntityScheduleDependency(
                entity_id=entity.id,
                predecessor_milestone_id=milestones[index - 1].id,
                successor_milestone_id=milestones[index].id,
                dependency_type="finish_to_start",
                lag_days=0,
                cascade_on_shift=True,
                status="active",
                created_by_id=user.id,
            )
        )
    for task, milestone_index in tasks:
        db.add(
            WorkEntityScheduleDependency(
                entity_id=entity.id,
                predecessor_task_id=task.id,
                successor_milestone_id=milestones[milestone_index].id,
                dependency_type="finish_to_start",
                lag_days=0,
                cascade_on_shift=True,
                status="active",
                created_by_id=user.id,
            )
        )

    record_entity_event(
        db,
        entity.id,
        user.id,
        "guided_project_created",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "title": entity.title,
            },
            "action": "created",
            "changes": [
                {
                    "field": "outcome_statement",
                    "from": None,
                    "to": entity.outcome_statement,
                },
                {
                    "field": "success_criteria",
                    "from": None,
                    "to": entity.success_criteria,
                },
                {
                    "field": "due_at",
                    "from": None,
                    "to": jsonable_encoder(entity.due_at),
                },
            ],
            "impact": {
                "members": len(body.members),
                "milestones": len(milestones),
                "tasks": len(tasks),
            },
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="created",
        correlation_id=correlation_id,
    )
    for milestone in milestones:
        record_entity_event(
            db,
            entity.id,
            user.id,
            "project_milestone_created",
            {
                "schema_version": 1,
                "object": {
                    "type": "milestone",
                    "id": str(milestone.id),
                    "title": milestone.title,
                },
                "action": "created",
                "changes": [
                    {
                        "field": "baseline_at",
                        "from": None,
                        "to": jsonable_encoder(milestone.baseline_at),
                    }
                ],
            },
            object_type="milestone",
            object_id=milestone.id,
            object_title=milestone.title,
            action="created",
            correlation_id=correlation_id,
        )
    for task, _ in tasks:
        record_entity_event(
            db,
            entity.id,
            user.id,
            "project_task_created",
            {
                "schema_version": 1,
                "object": {
                    "type": "task",
                    "id": str(task.id),
                    "title": task.title,
                },
                "action": "created",
                "changes": [
                    {
                        "field": "baseline_due_at",
                        "from": None,
                        "to": jsonable_encoder(task.baseline_due_at),
                    }
                ],
            },
            object_type="task",
            object_id=task.id,
            object_title=task.title,
            action="created",
            correlation_id=correlation_id,
        )

    await db.commit()
    return GuidedProjectCreated(
        entity_id=entity.id,
        schedule_revision=entity.schedule_revision,
    )


@router.post(
    "/{entity_id}/work",
    response_model=ProjectWorkCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_work(
    entity_id: UUID,
    body: ProjectWorkCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Add one work item and its checkpoint link in a single transaction."""
    await lock_entity_state(db)
    entity = await _editable_entity(db, entity_id, user)
    validate_task_dates(
        entity,
        body.baseline_starts_at,
        body.baseline_due_at,
        against_baseline=True,
    )
    await validate_assignee(db, entity, body.assignee_id)
    milestone = (
        await db.execute(
            select(WorkEntityMilestone).where(
                WorkEntityMilestone.id == body.target_milestone_id,
                WorkEntityMilestone.entity_id == entity.id,
                WorkEntityMilestone.status == "planned",
            )
        )
    ).scalar_one_or_none()
    if not milestone:
        raise HTTPException(
            status_code=400,
            detail="Выберите запланированную контрольную точку",
        )
    if body.baseline_due_at > milestone.forecast_at:
        raise HTTPException(
            status_code=400,
            detail=(
                "Работа должна завершиться не позже связанной "
                "контрольной точки"
            ),
        )
    task = WorkEntityTask(
        entity_id=entity.id,
        stage_id=None,
        title=body.title,
        description=None,
        status="planned",
        priority=body.priority,
        assignee_id=body.assignee_id,
        created_by_id=user.id,
        acceptance_criteria=body.acceptance_criteria,
        next_step=None,
        waiting_for=None,
        baseline_starts_at=body.baseline_starts_at,
        baseline_due_at=body.baseline_due_at,
        forecast_starts_at=body.baseline_starts_at,
        forecast_due_at=body.baseline_due_at,
        actual_starts_at=None,
        actual_due_at=None,
        introduced_after_baseline=entity.baseline_locked_at is not None,
        introduced_at_revision=(
            entity.schedule_revision + 1
            if entity.baseline_locked_at is not None
            else None
        ),
        position=0,
    )
    db.add(task)
    await db.flush()
    db.add(
        WorkEntityScheduleDependency(
            entity_id=entity.id,
            predecessor_task_id=task.id,
            successor_milestone_id=milestone.id,
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
        {
            "schema_version": 1,
            "object": {
                "type": "task",
                "id": str(task.id),
                "title": task.title,
            },
            "action": "created",
            "changes": [
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
            "impact": {
                "schedule_revision": entity.schedule_revision,
                "target_milestone_id": str(milestone.id),
                "target_milestone_title": milestone.title,
            },
        },
        object_type="task",
        object_id=task.id,
        object_title=task.title,
        action="created",
    )
    await db.commit()
    return ProjectWorkCreated(
        task_id=task.id,
        schedule_revision=entity.schedule_revision,
    )


async def _deadline_preview(
    db: AsyncSession,
    entity: WorkEntity,
    body: ProjectDeadlineChangeRequest,
) -> ProjectDeadlineChangePreview:
    if entity.status == "draft":
        raise HTTPException(
            status_code=409,
            detail="В черновике измените базовый срок в параметрах проекта",
        )
    if entity.status in {"done", "archived"}:
        raise HTTPException(
            status_code=409,
            detail="Срок завершенного или архивного проекта менять нельзя",
        )
    if entity.starts_at and body.target_due_at <= entity.starts_at:
        raise HTTPException(
            status_code=400,
            detail="Целевая дата должна быть позже даты начала проекта",
        )
    if body.expected_revision != entity.schedule_revision:
        raise HTTPException(
            status_code=409,
            detail=(
                "График изменился. Обновите проект и повторите предварительный "
                "расчет."
            ),
        )
    tasks = list(
        (
            await db.execute(
                select(WorkEntityTask).where(
                    WorkEntityTask.entity_id == entity.id,
                    WorkEntityTask.status.not_in({"done", "cancelled"}),
                    WorkEntityTask.forecast_due_at > body.target_due_at,
                )
            )
        ).scalars().all()
    )
    milestones = list(
        (
            await db.execute(
                select(WorkEntityMilestone).where(
                    WorkEntityMilestone.entity_id == entity.id,
                    WorkEntityMilestone.status.not_in({"achieved", "cancelled"}),
                    WorkEntityMilestone.forecast_at > body.target_due_at,
                )
            )
        ).scalars().all()
    )
    conflicts = [
        ProjectDeadlineConflict(
            node_type="task",
            node_id=task.id,
            node_ref=f"PRJ-{task.task_number}",
            title=task.title,
            forecast_due_at=task.forecast_due_at,
            message="Текущий прогноз работы выходит за новую целевую дату.",
        )
        for task in tasks
        if task.forecast_due_at is not None
    ]
    conflicts.extend(
        ProjectDeadlineConflict(
            node_type="milestone",
            node_id=milestone.id,
            node_ref=f"КТ-{milestone.milestone_number}",
            title=milestone.title,
            forecast_due_at=milestone.forecast_at,
            message="Контрольная точка запланирована позже новой целевой даты.",
        )
        for milestone in milestones
    )
    current_target = entity.target_due_at or entity.due_at
    return ProjectDeadlineChangePreview(
        entity_id=entity.id,
        schedule_revision=entity.schedule_revision,
        baseline_due_at=entity.due_at,
        target_due_before=current_target,
        target_due_after=body.target_due_at,
        forecast_due_at=entity.forecast_due_at,
        shift_days=_shift_days(current_target, body.target_due_at),
        conflicts=conflicts,
        can_apply=True,
    )


@router.post(
    "/{entity_id}/deadline-change/preview",
    response_model=ProjectDeadlineChangePreview,
)
async def preview_project_deadline_change(
    entity_id: UUID,
    body: ProjectDeadlineChangeRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity = await _editable_entity(db, entity_id, user)
    return await _deadline_preview(db, entity, body)


@router.post(
    "/{entity_id}/deadline-change/apply",
    response_model=ProjectDeadlineChangePreview,
)
async def apply_project_deadline_change(
    entity_id: UUID,
    body: ProjectDeadlineChangeRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _editable_entity(db, entity_id, user)
    preview = await _deadline_preview(db, entity, body)
    before = entity.target_due_at or entity.due_at
    entity.target_due_at = body.target_due_at
    entity.schedule_revision += 1
    entity.updated_at = _utc_now()
    correlation_id = uuid.uuid4()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_target_deadline_changed",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "title": entity.title,
            },
            "action": "target_deadline_changed",
            "changes": [
                {
                    "field": "target_due_at",
                    "from": jsonable_encoder(before),
                    "to": jsonable_encoder(body.target_due_at),
                }
            ],
            "reason": body.reason,
            "impact": {
                "shift_days": preview.shift_days,
                "conflicts": len(preview.conflicts),
                "baseline_due_at": jsonable_encoder(entity.due_at),
                "forecast_due_at": jsonable_encoder(entity.forecast_due_at),
            },
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="target_deadline_changed",
        reason=body.reason,
        correlation_id=correlation_id,
    )
    await db.commit()
    preview.schedule_revision = entity.schedule_revision
    return preview


def _charter_preview(
    entity: WorkEntity,
    body: ProjectCharterChangeRequest,
) -> ProjectCharterChangePreview:
    if entity.baseline_locked_at is None:
        raise HTTPException(
            status_code=409,
            detail="В черновике измените результат в параметрах проекта",
        )
    if body.expected_revision != entity.schedule_revision:
        raise HTTPException(
            status_code=409,
            detail="Проект уже изменился. Обновите данные и повторите расчет.",
        )
    requested = body.model_dump(
        exclude_unset=True,
        exclude={"reason", "expected_revision"},
    )
    changes = [
        ProjectCharterFieldChange(
            field=field,
            before=getattr(entity, field),
            after=value,
        )
        for field, value in requested.items()
        if getattr(entity, field) != value
    ]
    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Паспорт проекта не изменился",
        )
    return ProjectCharterChangePreview(
        entity_id=entity.id,
        schedule_revision=entity.schedule_revision,
        baseline_outcome_statement=entity.baseline_outcome_statement,
        baseline_success_criteria=entity.baseline_success_criteria,
        baseline_constraints=entity.baseline_constraints,
        changes=changes,
        can_apply=True,
    )


@router.post(
    "/{entity_id}/charter-change/preview",
    response_model=ProjectCharterChangePreview,
)
async def preview_project_charter_change(
    entity_id: UUID,
    body: ProjectCharterChangeRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity = await _editable_entity(db, entity_id, user)
    return _charter_preview(entity, body)


@router.post(
    "/{entity_id}/charter-change/apply",
    response_model=ProjectCharterChangePreview,
)
async def apply_project_charter_change(
    entity_id: UUID,
    body: ProjectCharterChangeRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _editable_entity(db, entity_id, user)
    preview = _charter_preview(entity, body)
    for change in preview.changes:
        setattr(entity, change.field, change.after)
    entity.schedule_revision += 1
    entity.updated_at = _utc_now()
    correlation_id = uuid.uuid4()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_charter_changed",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "title": entity.title,
            },
            "action": "charter_changed",
            "changes": [
                {
                    "field": change.field,
                    "from": change.before,
                    "to": change.after,
                }
                for change in preview.changes
            ],
            "reason": body.reason,
            "impact": {
                "schedule_revision": entity.schedule_revision,
                "baseline_preserved": True,
            },
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="charter_changed",
        reason=body.reason,
        correlation_id=correlation_id,
    )
    await db.commit()
    return preview.model_copy(
        update={"schedule_revision": entity.schedule_revision}
    )


@router.post(
    "/{entity_id}/decisions",
    status_code=status.HTTP_201_CREATED,
)
async def record_project_decision(
    entity_id: UUID,
    body: ProjectDecisionCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity = await _editable_entity(db, entity_id, user)
    owner = await validate_decision_owner(db, entity, body.owner_id)
    owner_name = owner.full_name if owner else None
    sections = [
        f"Дата решения: {body.decided_at.isoformat()}",
        f"Решение: {body.decision}",
    ]
    if body.reason:
        sections.append(f"Основание: {body.reason.strip()}")
    if body.participants:
        sections.append(f"Участники: {body.participants.strip()}")
    if body.follow_up:
        sections.append(f"Следующее действие: {body.follow_up.strip()}")
    if owner_name:
        sections.append(f"Ответственный: {owner_name}")
    if body.due_at:
        sections.append(f"Срок действия: {body.due_at.isoformat()}")
    artifact = WorkEntityArtifact(
        entity_id=entity.id,
        task_id=None,
        milestone_id=None,
        artifact_type="decision",
        title=body.title,
        body="\n\n".join(sections),
        url=None,
        status="active",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(artifact)
    await db.flush()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "project_decision_recorded",
        {
            "schema_version": 1,
            "object": {
                "type": "artifact",
                "id": str(artifact.id),
                "title": artifact.title,
            },
            "action": "decision_recorded",
            "entry_type": "decision",
            "body": body.decision,
            "reason": body.reason,
            "impact": {
                "owner": owner_name,
                "due_at": jsonable_encoder(body.due_at),
                "participants": body.participants,
            },
        },
        object_type="artifact",
        object_id=artifact.id,
        object_title=artifact.title,
        action="decision_recorded",
        reason=(body.reason or "").strip() or None,
    )
    await db.commit()
    return {"id": str(artifact.id)}
