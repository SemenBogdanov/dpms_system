"""Lifecycle and read projection for project operation Q execution contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_contract import WorkEntityExecutionContract
from app.models.task import (
    Task,
    TaskAcceptanceCriterion,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from app.models.user import User, UserRole
from app.models.work_entity import WorkEntity, WorkEntityTask
from app.schemas.work_entity import (
    WorkEntityExecutionContractCreateRequest,
    WorkEntityExecutionContractRead,
    WorkEntityExecutionContractTaskOption,
)
from app.services.activity import record_activity_event
from app.services.task_acceptance import initialize_acceptance_plan
from app.services.task_policy import ensure_critical_priority_allowed
from app.services.work_entities import lock_entity_state, record_entity_event


LINKABLE_TASK_STATUSES = {
    TaskStatus.new,
    TaskStatus.estimated,
    TaskStatus.in_queue,
}
TERMINAL_OPERATION_STATUSES = {"done", "cancelled"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_contract_manager(user: User, access_role: str) -> None:
    if access_role not in {"owner", "editor"}:
        raise HTTPException(
            status_code=403,
            detail="Управлять Q-контрактом может владелец или редактор проекта",
        )
    if not user.can_link_queue_tasks_to_projects:
        raise HTTPException(
            status_code=403,
            detail="Администратор не выдал право связывать Q-задачи с проектами",
        )


def ensure_operation_contractable(operation: WorkEntityTask) -> None:
    if operation.status in TERMINAL_OPERATION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Завершенную или отмененную операцию нельзя публиковать в Q-пул",
        )


def ensure_project_execution_started(entity: WorkEntity) -> None:
    if entity.status != "active" or entity.baseline_locked_at is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_not_active_for_q_publication",
                "message": (
                    "Q-задачи можно публиковать и связывать только после "
                    "активации проекта и фиксации базового плана"
                ),
            },
        )


def _task_visibility_filter(user: User):
    if (
        user.role in {UserRole.admin, UserRole.teamlead}
        or user.can_link_queue_tasks_to_projects
    ):
        return True
    return Task.assignee_id == user.id


def _task_is_prestart(task: Task) -> bool:
    return (
        task.status in LINKABLE_TASK_STATUSES
        and task.assignee_id is None
        and task.started_at is None
        and task.due_date is not None
    )


def _task_is_releasable(task: Task) -> bool:
    return (
        task.status in LINKABLE_TASK_STATUSES | {TaskStatus.cancelled}
        and task.assignee_id is None
        and task.started_at is None
    )


def _request_fingerprint(body: WorkEntityExecutionContractCreateRequest) -> str:
    payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope_snapshot(operation: WorkEntityTask) -> dict:
    return jsonable_encoder(
        {
            "schema_version": 1,
            "operation_id": operation.id,
            "operation_ref": f"PRJ-{operation.task_number}",
            "title": operation.title,
            "description": operation.description,
            "acceptance_criteria": operation.acceptance_criteria,
            "priority": operation.priority,
            "assignee_id": operation.assignee_id,
            "forecast_starts_at": operation.forecast_starts_at,
            "forecast_due_at": operation.forecast_due_at,
            "captured_at": utc_now(),
        }
    )


async def _acceptance_snapshot(db: AsyncSession, task: Task) -> dict:
    criteria = list(
        (
            await db.execute(
                select(TaskAcceptanceCriterion)
                .where(TaskAcceptanceCriterion.task_id == task.id)
                .order_by(TaskAcceptanceCriterion.position)
            )
        ).scalars().all()
    )
    return jsonable_encoder(
        {
            "schema_version": 1,
            "acceptance_owner_id": task.acceptance_owner_id,
            "mode": task.acceptance_mode,
            "revision": task.acceptance_revision,
            "criteria": [
                {
                    "id": item.id,
                    "position": item.position,
                    "title": item.title,
                    "description": item.description,
                    "kind": item.kind,
                    "baseline_revision": item.baseline_revision,
                }
                for item in criteria
            ],
            "captured_at": utc_now(),
        }
    )


def _can_release(contract: WorkEntityExecutionContract, task: Task, can_manage: bool) -> bool:
    return can_manage and contract.status == "active" and _task_is_releasable(task)


def serialize_execution_contract(
    contract: WorkEntityExecutionContract,
    task: Task,
    assignee_name: str | None,
    *,
    can_manage: bool,
) -> WorkEntityExecutionContractRead:
    return WorkEntityExecutionContractRead(
        id=contract.id,
        entity_id=contract.entity_id,
        operation_id=contract.operation_id,
        task_id=task.id,
        task_number=task.task_number,
        source=contract.source,
        status=contract.status,
        task_title=task.title,
        task_status=task.status,
        estimated_q=task.estimated_q,
        priority=task.priority,
        assignee_id=task.assignee_id,
        assignee_name=assignee_name,
        planned_starts_at=contract.planned_starts_at,
        planned_due_at=contract.planned_due_at,
        due_date=task.due_date,
        acceptance_mode=task.acceptance_mode,
        acceptance_state=task.acceptance_state,
        acceptance_total_count=task.acceptance_total_count,
        acceptance_accepted_count=task.acceptance_accepted_count,
        acceptance_required_count=task.acceptance_required_count,
        acceptance_required_accepted_count=task.acceptance_required_accepted_count,
        result_url=task.result_url,
        result_comment=task.result_comment,
        created_at=contract.created_at,
        can_release=_can_release(contract, task, can_manage),
    )


async def load_active_execution_contracts(
    db: AsyncSession,
    entity_id: UUID,
    *,
    can_manage: bool,
) -> dict[UUID, WorkEntityExecutionContractRead]:
    assignee = User.__table__.alias("execution_contract_assignee")
    rows = (
        await db.execute(
            select(
                WorkEntityExecutionContract,
                Task,
                assignee.c.full_name,
            )
            .join(Task, Task.id == WorkEntityExecutionContract.task_id)
            .outerjoin(assignee, assignee.c.id == Task.assignee_id)
            .where(
                WorkEntityExecutionContract.entity_id == entity_id,
                WorkEntityExecutionContract.status == "active",
            )
        )
    ).all()
    return {
        contract.operation_id: serialize_execution_contract(
            contract,
            task,
            assignee_name,
            can_manage=can_manage,
        )
        for contract, task, assignee_name in rows
    }


async def list_execution_contract_options(
    db: AsyncSession,
    *,
    entity: WorkEntity,
    operation: WorkEntityTask,
    user: User,
    access_role: str,
    search: str | None,
    limit: int,
) -> list[WorkEntityExecutionContractTaskOption]:
    ensure_contract_manager(user, access_role)
    ensure_project_execution_started(entity)
    ensure_operation_contractable(operation)
    active_contract_exists = (
        await db.execute(
            select(WorkEntityExecutionContract.id).where(
                WorkEntityExecutionContract.operation_id == operation.id,
                WorkEntityExecutionContract.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active_contract_exists:
        return []

    contracted_task_ids = select(WorkEntityExecutionContract.task_id).where(
        WorkEntityExecutionContract.status == "active"
    )
    stmt = select(Task).where(
        _task_visibility_filter(user),
        Task.status.in_(LINKABLE_TASK_STATUSES),
        Task.assignee_id.is_(None),
        Task.started_at.is_(None),
        Task.due_date.is_not(None),
        Task.id.not_in(contracted_task_ids),
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Task.title.ilike(pattern),
                Task.description.ilike(pattern),
            )
        )
    tasks = list(
        (
            await db.execute(
                stmt.order_by(Task.updated_at.desc()).limit(min(max(limit, 1), 100))
            )
        ).scalars().all()
    )
    return [
        WorkEntityExecutionContractTaskOption(
            task_id=task.id,
            task_number=task.task_number,
            title=task.title,
            status=task.status,
            estimated_q=task.estimated_q,
            priority=task.priority,
            due_date=task.due_date,
            acceptance_mode=task.acceptance_mode,
            acceptance_state=task.acceptance_state,
            assignee_name=None,
        )
        for task in tasks
    ]


async def _load_contract_read(
    db: AsyncSession,
    contract: WorkEntityExecutionContract,
    *,
    can_manage: bool,
) -> WorkEntityExecutionContractRead:
    row = (
        await db.execute(
            select(Task, User.full_name)
            .outerjoin(User, User.id == Task.assignee_id)
            .where(Task.id == contract.task_id)
        )
    ).one()
    task, assignee_name = row
    return serialize_execution_contract(
        contract,
        task,
        assignee_name,
        can_manage=can_manage,
    )


async def create_execution_contract(
    db: AsyncSession,
    *,
    entity: WorkEntity,
    operation_id: UUID,
    body: WorkEntityExecutionContractCreateRequest,
    user: User,
    access_role: str,
) -> WorkEntityExecutionContractRead:
    ensure_contract_manager(user, access_role)
    await lock_entity_state(db)
    await db.refresh(entity, attribute_names=["status", "baseline_locked_at"])
    ensure_project_execution_started(entity)
    operation = (
        await db.execute(
            select(WorkEntityTask)
            .where(
                WorkEntityTask.id == operation_id,
                WorkEntityTask.entity_id == entity.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Операция проекта не найдена")
    ensure_operation_contractable(operation)

    fingerprint = _request_fingerprint(body)
    replay = (
        await db.execute(
            select(WorkEntityExecutionContract).where(
                WorkEntityExecutionContract.idempotency_key == body.idempotency_key
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        if (
            replay.entity_id != entity.id
            or replay.operation_id != operation.id
            or replay.request_fingerprint != fingerprint
        ):
            raise HTTPException(
                status_code=409,
                detail="Ключ повторного запроса уже использован для другой публикации",
            )
        return await _load_contract_read(
            db,
            replay,
            can_manage=True,
        )

    active_operation_contract = (
        await db.execute(
            select(WorkEntityExecutionContract.id).where(
                WorkEntityExecutionContract.operation_id == operation.id,
                WorkEntityExecutionContract.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active_operation_contract:
        raise HTTPException(
            status_code=409,
            detail="У операции уже есть активная Q-задача",
        )

    if body.mode == "link":
        task = (
            await db.execute(
                select(Task)
                .where(
                    Task.id == body.task_id,
                    _task_visibility_filter(user),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Q-задача не найдена")
        if not _task_is_prestart(task):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Привязать можно только неназначенную Q-задачу со сроком, "
                    "которая еще не взята в работу"
                ),
            )
        source = "linked_existing"
    else:
        ensure_critical_priority_allowed(user, body.priority)
        if body.task_type == TaskType.proactive and body.priority in {
            TaskPriority.high,
            TaskPriority.critical,
        }:
            raise HTTPException(
                status_code=400,
                detail="Проактивные задачи не могут иметь приоритет выше medium",
            )
        task = Task(
            title=body.title,
            description=body.description or operation.description,
            task_type=body.task_type,
            complexity=body.complexity,
            estimated_q=body.estimated_q,
            priority=body.priority,
            status=TaskStatus.in_queue,
            min_league=body.min_league,
            assignee_id=None,
            estimator_id=user.id,
            acceptance_owner_id=user.id,
            acceptance_mode=body.acceptance_mode,
            estimation_details={
                "source": "project_operation",
                "entity_id": str(entity.id),
                "operation_id": str(operation.id),
                "operation_ref": f"PRJ-{operation.task_number}",
                "published_at": utc_now().isoformat(),
            },
            due_date=body.due_date,
            tags=body.tags,
        )
        db.add(task)
        await db.flush()
        await initialize_acceptance_plan(
            db,
            task,
            owner_id=user.id,
            mode=body.acceptance_mode,
            criteria=body.acceptance_criteria,
        )
        source = "created_from_operation"

    active_task_contract = (
        await db.execute(
            select(WorkEntityExecutionContract.id).where(
                WorkEntityExecutionContract.task_id == task.id,
                WorkEntityExecutionContract.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active_task_contract:
        raise HTTPException(
            status_code=409,
            detail="Эта Q-задача уже исполняет другую операцию",
        )

    contract = WorkEntityExecutionContract(
        entity_id=entity.id,
        operation_id=operation.id,
        task_id=task.id,
        status="active",
        source=source,
        idempotency_key=body.idempotency_key,
        request_fingerprint=fingerprint,
        scope_snapshot=_scope_snapshot(operation),
        acceptance_snapshot=await _acceptance_snapshot(db, task),
        planned_starts_at=operation.forecast_starts_at or operation.baseline_starts_at,
        planned_due_at=operation.forecast_due_at or operation.baseline_due_at,
        created_by_id=user.id,
    )
    db.add(contract)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        replay = (
            await db.execute(
                select(WorkEntityExecutionContract).where(
                    WorkEntityExecutionContract.idempotency_key == body.idempotency_key
                )
            )
        ).scalar_one_or_none()
        if (
            replay is not None
            and replay.entity_id == entity.id
            and replay.operation_id == operation.id
            and replay.request_fingerprint == fingerprint
        ):
            return await _load_contract_read(db, replay, can_manage=True)
        raise HTTPException(
            status_code=409,
            detail="Операция или Q-задача уже связана другим контрактом",
        ) from error

    event_type = (
        "execution_contract_published"
        if source == "created_from_operation"
        else "execution_contract_linked"
    )
    event_payload = {
        "schema_version": 1,
        "contract_id": str(contract.id),
        "source": source,
        "operation_id": str(operation.id),
        "operation_ref": f"PRJ-{operation.task_number}",
        "q_task_id": str(task.id),
        "q_task_number": task.task_number,
        "estimated_q": float(task.estimated_q),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "impact": {
            "q_task_number": task.task_number,
            "estimated_q": float(task.estimated_q),
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "contract_source": source,
        },
    }
    record_entity_event(
        db,
        entity.id,
        user.id,
        event_type,
        event_payload,
        object_type="task",
        object_id=operation.id,
        object_ref=f"PRJ-{operation.task_number}",
        object_title=operation.title,
        action="published" if source == "created_from_operation" else "linked",
    )
    await record_activity_event(
        db,
        user.id,
        event_type,
        task_id=task.id,
        metadata=event_payload,
    )
    await db.flush()
    return await _load_contract_read(db, contract, can_manage=True)


async def release_execution_contract(
    db: AsyncSession,
    *,
    entity: WorkEntity,
    operation_id: UUID,
    reason: str,
    user: User,
    access_role: str,
) -> WorkEntityExecutionContractRead:
    ensure_contract_manager(user, access_role)
    await lock_entity_state(db)
    operation = (
        await db.execute(
            select(WorkEntityTask)
            .where(
                WorkEntityTask.id == operation_id,
                WorkEntityTask.entity_id == entity.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Операция проекта не найдена")
    contract = (
        await db.execute(
            select(WorkEntityExecutionContract)
            .where(
                WorkEntityExecutionContract.operation_id == operation.id,
                WorkEntityExecutionContract.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail="Активный Q-контракт не найден")
    task = (
        await db.execute(
            select(Task).where(Task.id == contract.task_id).with_for_update()
        )
    ).scalar_one()
    if not _task_is_releasable(task):
        raise HTTPException(
            status_code=409,
            detail="Нельзя освободить контракт после назначения или начала Q-задачи",
        )

    now = utc_now()
    contract.status = "released"
    contract.released_by_id = user.id
    contract.release_reason = reason
    contract.released_at = now
    contract.updated_at = now
    if contract.source == "created_from_operation":
        task.status = TaskStatus.cancelled

    event_payload = {
        "schema_version": 1,
        "contract_id": str(contract.id),
        "source": contract.source,
        "operation_id": str(operation.id),
        "operation_ref": f"PRJ-{operation.task_number}",
        "q_task_id": str(task.id),
        "q_task_number": task.task_number,
        "created_task_cancelled": contract.source == "created_from_operation",
        "reason": reason,
        "impact": {
            "q_task_number": task.task_number,
            "created_task_cancelled": contract.source == "created_from_operation",
        },
    }
    record_entity_event(
        db,
        entity.id,
        user.id,
        "execution_contract_released",
        event_payload,
        object_type="task",
        object_id=operation.id,
        object_ref=f"PRJ-{operation.task_number}",
        object_title=operation.title,
        action="released",
        reason=reason,
    )
    await record_activity_event(
        db,
        user.id,
        "execution_contract_released",
        task_id=task.id,
        metadata=event_payload,
    )
    await db.flush()
    return await _load_contract_read(db, contract, can_manage=False)
