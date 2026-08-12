"""API for projects, goals, members, typed links, and direct summaries."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_task_workspace_access
from app.api.routes.contacts import has_accepted_contact
from app.models.quick_note import QuickNote
from app.models.user import User
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityEvent,
    WorkEntityLink,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityStage,
    WorkEntityTask,
)
from app.schemas.work_entity import (
    WorkEntityCreate,
    WorkEntityEventRead,
    WorkEntityLinkCreate,
    WorkEntityLinkOption,
    WorkEntityLinkRead,
    WorkEntityLinkUpdate,
    WorkEntityMemberCreate,
    WorkEntityMemberRead,
    WorkEntityMemberUpdate,
    WorkEntityRead,
    WorkEntityReadinessIssue,
    WorkEntityReadinessRead,
    WorkEntityReverseLinkRead,
    WorkEntityStatus,
    WorkEntitySummary,
    WorkEntityTargetType,
    WorkEntityType,
    WorkEntityUpdate,
)
from app.services.work_entities import (
    build_entity_summary,
    get_entity_access,
    link_target_type,
    list_accessible_entities,
    list_link_options,
    lock_entity_graph,
    lock_entity_state,
    redact_entity_event_payload,
    record_entity_event,
    serialize_links,
    target_column_values,
    target_is_accessible,
    would_create_structural_cycle,
)

router = APIRouter()

ENTITY_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "archived"},
    "active": {"paused", "done", "archived"},
    "paused": {"active", "done", "archived"},
    "done": {"archived"},
    "archived": set(),
}


async def _require_owned_quick_note_link_target(
    db: AsyncSession,
    target_type: WorkEntityTargetType,
    target_id: UUID,
    user_id: UUID,
) -> None:
    """Only a note creator may mutate project links for that note."""
    if target_type != "quick_note":
        return
    owned_note_id = (
        await db.execute(
            select(QuickNote.id).where(
                QuickNote.id == target_id,
                QuickNote.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if owned_note_id is None:
        raise HTTPException(
            status_code=403,
            detail="Только создатель заметки может изменять её связи",
        )


async def _get_entity_or_404(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> tuple[WorkEntity, str]:
    access = await get_entity_access(db, entity_id, user.id)
    if not access:
        raise HTTPException(status_code=404, detail="Проект или цель не найдены")
    return access


async def _get_editable_entity_or_404(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> tuple[WorkEntity, str]:
    entity, access_role = await _get_entity_or_404(db, entity_id, user)
    if access_role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения сущности")
    return entity, access_role


async def _get_owned_entity_or_404(
    db: AsyncSession,
    entity_id: UUID,
    user: User,
) -> WorkEntity:
    entity, access_role = await _get_entity_or_404(db, entity_id, user)
    if access_role != "owner":
        raise HTTPException(status_code=403, detail="Только владелец может изменить доступ")
    return entity


async def _entity_reads(
    db: AsyncSession,
    rows: list[tuple[WorkEntity, str]],
) -> list[WorkEntityRead]:
    if not rows:
        return []
    entity_ids = [entity.id for entity, _ in rows]
    owner_ids = {entity.owner_id for entity, _ in rows}
    owners = (
        await db.execute(select(User).where(User.id.in_(owner_ids)))
    ).scalars().all()
    owner_map = {owner.id: owner for owner in owners}
    member_counts = dict(
        (
            await db.execute(
                select(WorkEntityMember.entity_id, func.count(WorkEntityMember.id))
                .where(WorkEntityMember.entity_id.in_(entity_ids))
                .group_by(WorkEntityMember.entity_id)
            )
        ).all()
    )
    link_counts = dict(
        (
            await db.execute(
                select(WorkEntityLink.entity_id, func.count(WorkEntityLink.id))
                .where(WorkEntityLink.entity_id.in_(entity_ids))
                .group_by(WorkEntityLink.entity_id)
            )
        ).all()
    )
    task_counts = dict(
        (
            await db.execute(
                select(WorkEntityTask.entity_id, func.count(WorkEntityTask.id))
                .where(
                    WorkEntityTask.entity_id.in_(entity_ids),
                    WorkEntityTask.status != "cancelled",
                )
                .group_by(WorkEntityTask.entity_id)
            )
        ).all()
    )
    milestone_counts = dict(
        (
            await db.execute(
                select(
                    WorkEntityMilestone.entity_id,
                    func.count(WorkEntityMilestone.id),
                )
                .where(
                    WorkEntityMilestone.entity_id.in_(entity_ids),
                    WorkEntityMilestone.status != "cancelled",
                )
                .group_by(WorkEntityMilestone.entity_id)
            )
        ).all()
    )
    stage_counts = dict(
        (
            await db.execute(
                select(WorkEntityStage.entity_id, func.count(WorkEntityStage.id))
                .where(
                    WorkEntityStage.entity_id.in_(entity_ids),
                    WorkEntityStage.status != "cancelled",
                )
                .group_by(WorkEntityStage.entity_id)
            )
        ).all()
    )
    artifact_counts = dict(
        (
            await db.execute(
                select(WorkEntityArtifact.entity_id, func.count(WorkEntityArtifact.id))
                .where(
                    WorkEntityArtifact.entity_id.in_(entity_ids),
                    WorkEntityArtifact.status != "archived",
                )
                .group_by(WorkEntityArtifact.entity_id)
            )
        ).all()
    )
    result: list[WorkEntityRead] = []
    for entity, access_role in rows:
        owner = owner_map[entity.owner_id]
        result.append(
            WorkEntityRead(
                id=entity.id,
                owner_id=entity.owner_id,
                owner_name=owner.full_name,
                owner_email=owner.email if access_role == "owner" else None,
                entity_type=entity.entity_type,
                title=entity.title,
                description=entity.description,
                outcome_statement=entity.outcome_statement,
                success_criteria=entity.success_criteria,
                constraints=entity.constraints,
                baseline_outcome_statement=entity.baseline_outcome_statement,
                baseline_success_criteria=entity.baseline_success_criteria,
                baseline_constraints=entity.baseline_constraints,
                status=entity.status,
                visibility=entity.visibility,
                starts_at=entity.starts_at,
                due_at=entity.due_at,
                target_due_at=entity.target_due_at,
                forecast_starts_at=entity.forecast_starts_at,
                forecast_due_at=entity.forecast_due_at,
                actual_starts_at=entity.actual_starts_at,
                actual_due_at=entity.actual_due_at,
                planning_mode=entity.planning_mode,
                methodology_title=entity.methodology_title,
                methodology_version=entity.methodology_version,
                methodology_snapshot=entity.methodology_snapshot,
                baseline_locked_at=entity.baseline_locked_at,
                baseline_locked_by_id=entity.baseline_locked_by_id,
                schedule_revision=entity.schedule_revision,
                tags=entity.tags or [],
                details_json=entity.details_json,
                archived_at=entity.archived_at,
                access_role=access_role,
                members_count=int(member_counts.get(entity.id, 0)),
                links_count=int(link_counts.get(entity.id, 0)),
                stages_count=int(stage_counts.get(entity.id, 0)),
                tasks_count=int(task_counts.get(entity.id, 0)),
                milestones_count=int(milestone_counts.get(entity.id, 0)),
                artifacts_count=int(artifact_counts.get(entity.id, 0)),
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
    return result


async def _entity_read(
    db: AsyncSession,
    entity: WorkEntity,
    access_role: str,
) -> WorkEntityRead:
    return (await _entity_reads(db, [(entity, access_role)]))[0]


async def _member_open_responsibilities(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
) -> tuple[int, int]:
    open_tasks = (
        await db.execute(
            select(func.count(WorkEntityTask.id)).where(
                WorkEntityTask.entity_id == entity_id,
                WorkEntityTask.assignee_id == user_id,
                WorkEntityTask.status.not_in({"done", "cancelled"}),
            )
        )
    ).scalar_one()
    open_milestones = (
        await db.execute(
            select(func.count(WorkEntityMilestone.id)).where(
                WorkEntityMilestone.entity_id == entity_id,
                WorkEntityMilestone.decision_owner_id == user_id,
                WorkEntityMilestone.status == "planned",
            )
        )
    ).scalar_one()
    return int(open_tasks), int(open_milestones)


def _ensure_member_can_lose_participant_role(
    open_tasks: int,
    open_milestones: int,
) -> None:
    if open_tasks or open_milestones:
        parts = []
        if open_tasks:
            parts.append(f"открытые задачи: {open_tasks}")
        if open_milestones:
            parts.append(f"контрольные точки: {open_milestones}")
        raise HTTPException(
            status_code=409,
            detail=(
                "Сначала завершите или переназначьте ответственность ("
                + ", ".join(parts)
                + ")"
            ),
        )


def _validate_dates(starts_at: datetime | None, due_at: datetime | None) -> None:
    if starts_at and due_at and due_at <= starts_at:
        raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала")


def _methodology_snapshot_problem(snapshot: dict) -> str | None:
    schema_version = snapshot.get("schemaVersion", snapshot.get("schema_version"))
    if schema_version in {None, ""}:
        return "В snapshot отсутствует версия схемы."
    stages = snapshot.get("stages")
    if not isinstance(stages, list) or not stages:
        return "В snapshot отсутствует непустой список этапов."
    seen_keys: set[str] = set()
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            return f"Этап {index} должен быть объектом."
        stage_key = str(stage.get("id") or stage.get("key") or "").strip()
        stage_title = str(
            stage.get("name") or stage.get("title") or ""
        ).strip()
        if not stage_key or not stage_title:
            return f"Для этапа {index} нужны стабильный id и название."
        if stage_key in seen_keys:
            return f"Идентификатор этапа «{stage_key}» повторяется."
        seen_keys.add(stage_key)
    return None


def _methodology_snapshot_stage_index(snapshot: dict) -> dict[str, dict]:
    return {
        str(stage.get("id") or stage.get("key")).strip(): stage
        for stage in snapshot.get("stages", [])
        if isinstance(stage, dict)
        and str(stage.get("id") or stage.get("key") or "").strip()
    }


async def _build_readiness(
    db: AsyncSession,
    entity: WorkEntity,
    *,
    overrides: dict[str, Any] | None = None,
) -> WorkEntityReadinessRead:
    proposed = overrides or {}
    project_start = proposed.get("starts_at", entity.starts_at)
    project_due = proposed.get("due_at", entity.due_at)
    outcome_statement = proposed.get(
        "outcome_statement",
        entity.outcome_statement,
    )
    success_criteria = proposed.get(
        "success_criteria",
        entity.success_criteria,
    )
    mode = proposed.get("planning_mode", entity.planning_mode)
    method_title = proposed.get("methodology_title", entity.methodology_title)
    method_version = proposed.get("methodology_version", entity.methodology_version)
    method_snapshot = proposed.get(
        "methodology_snapshot",
        entity.methodology_snapshot,
    )
    methodology_stage_index: dict[str, dict] = {}
    stages = list(
        (
            await db.execute(
                select(WorkEntityStage).where(
                    WorkEntityStage.entity_id == entity.id,
                    WorkEntityStage.status != "cancelled",
                )
            )
        ).scalars().all()
    )
    tasks = list(
        (
            await db.execute(
                select(WorkEntityTask).where(
                    WorkEntityTask.entity_id == entity.id,
                    WorkEntityTask.status != "cancelled",
                )
            )
        ).scalars().all()
    )
    milestones = list(
        (
            await db.execute(
                select(WorkEntityMilestone).where(
                    WorkEntityMilestone.entity_id == entity.id,
                    WorkEntityMilestone.status != "cancelled",
                )
            )
        ).scalars().all()
    )
    dependencies = list(
        (
            await db.execute(
                select(WorkEntityScheduleDependency).where(
                    WorkEntityScheduleDependency.entity_id == entity.id,
                    WorkEntityScheduleDependency.status == "active",
                )
            )
        ).scalars().all()
    )
    issues: list[WorkEntityReadinessIssue] = []

    def add(
        severity: str,
        code: str,
        scope_type: str,
        scope_id: UUID,
        scope_ref: str | None,
        scope_title: str,
        field: str | None,
        message: str,
        guidance: str,
    ) -> None:
        issues.append(
            WorkEntityReadinessIssue(
                severity=severity,
                code=code,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_ref=scope_ref,
                scope_title=scope_title,
                field=field,
                message=message,
                guidance=guidance,
            )
        )

    if not outcome_statement:
        add(
            "blocking",
            "project_outcome_missing",
            "entity",
            entity.id,
            None,
            entity.title,
            "outcome_statement",
            "Не сформулирован проверяемый результат проекта.",
            "Опишите, что именно должно стать истинным к конечному сроку.",
        )
    if not success_criteria:
        add(
            "blocking",
            "project_success_criteria_missing",
            "entity",
            entity.id,
            None,
            entity.title,
            "success_criteria",
            "Не указано, как подтвердить достижение результата.",
            "Добавьте наблюдаемые критерии успеха или доказательства приемки.",
        )
    if project_start is None or project_due is None:
        add(
            "blocking",
            "project_schedule_missing",
            "entity",
            entity.id,
            None,
            entity.title,
            "starts_at" if project_start is None else "due_at",
            "Не задан полный базовый период проекта.",
            "Укажите дату начала и базовый срок завершения.",
        )
    if entity.entity_type == "project" and not tasks:
        add(
            "blocking",
            "project_work_missing",
            "entity",
            entity.id,
            None,
            entity.title,
            None,
            "В проекте нет исполнимых работ.",
            "Добавьте хотя бы одну работу с исполнителем, сроком и результатом.",
        )
    if entity.entity_type == "project" and not milestones:
        add(
            "blocking",
            "project_milestones_missing",
            "entity",
            entity.id,
            None,
            entity.title,
            None,
            "В проекте нет контрольной точки приемки.",
            "Добавьте хотя бы одну точку, в которой результат будет проверен.",
        )
    if entity.entity_type != "project" and not tasks and not milestones:
        add(
            "blocking",
            "scope_empty",
            "entity",
            entity.id,
            None,
            entity.title,
            None,
            "Не сформирован исполнимый scope.",
            "Добавьте работу или контрольную точку до активации.",
        )
    if mode == "methodology":
        if not method_title or not method_version or not method_snapshot:
            add(
                "blocking",
                "methodology_snapshot_missing",
                "entity",
                entity.id,
                None,
                entity.title,
                "methodology_snapshot",
                "Не зафиксирована применяемая версия методологии.",
                (
                    "Выберите импортированную версию и сохраните snapshot, "
                    "чтобы будущие обновления не меняли действующий проект."
                ),
            )
        elif snapshot_problem := _methodology_snapshot_problem(method_snapshot):
            add(
                "blocking",
                "methodology_snapshot_invalid",
                "entity",
                entity.id,
                None,
                entity.title,
                "methodology_snapshot",
                f"Snapshot методологии некорректен: {snapshot_problem}",
                "Повторите импорт проверенной версии методологии в admin.",
            )
        else:
            methodology_stage_index = _methodology_snapshot_stage_index(
                method_snapshot
            )
            if declared_version := (
                method_snapshot.get("methodologyVersion")
                or method_snapshot.get("version")
            ):
                normalized_declared = (
                    str(declared_version).strip().lower().removeprefix("v.")
                )
                normalized_selected = (
                    str(method_version).strip().lower().removeprefix("v.")
                )
                if normalized_declared != normalized_selected:
                    add(
                        "blocking",
                        "methodology_version_mismatch",
                        "entity",
                        entity.id,
                        None,
                        entity.title,
                        "methodology_version",
                        "Выбранная версия не совпадает с версией snapshot.",
                        (
                            "Повторно выберите версию методологии и создайте "
                            "новый snapshot."
                        ),
                    )
        methodology_stages = [
            stage for stage in stages if stage.source_type == "methodology"
        ]
        if not methodology_stages:
            add(
                "blocking",
                "methodology_stages_missing",
                "entity",
                entity.id,
                None,
                entity.title,
                "planning_mode",
                "Методология не развернута в этапы проекта.",
                "Примените маршрут методологии или вернитесь в свободный режим.",
            )
    for stage in stages:
        if stage.source_type == "methodology":
            if mode != "methodology":
                add(
                    "blocking",
                    "stage_methodology_mode_mismatch",
                    "stage",
                    stage.id,
                    stage.source_key,
                    stage.title,
                    "source_type",
                    "Этап методологии находится в проекте со свободным планированием.",
                    "Выберите методологию проекта или замените этап ручным.",
                )
            if not stage.source_key or not stage.source_snapshot:
                add(
                    "blocking",
                    "stage_source_snapshot_missing",
                    "stage",
                    stage.id,
                    stage.source_key,
                    stage.title,
                    "source_snapshot",
                    "Этап потерял связь с исходной версией методологии.",
                    "Повторно примените маршрут из проверенного snapshot.",
                )
            elif stage.source_key not in methodology_stage_index:
                add(
                    "blocking",
                    "stage_source_key_mismatch",
                    "stage",
                    stage.id,
                    stage.source_key,
                    stage.title,
                    "source_key",
                    "Этап отсутствует в зафиксированной версии методологии.",
                    "Повторно разверните этапы из snapshot выбранной версии.",
                )
            elif stage.source_snapshot != methodology_stage_index[stage.source_key]:
                add(
                    "blocking",
                    "stage_source_snapshot_mismatch",
                    "stage",
                    stage.id,
                    stage.source_key,
                    stage.title,
                    "source_snapshot",
                    (
                        "Содержимое этапа не совпадает с его исходником "
                        "в зафиксированной версии методологии."
                    ),
                    (
                        "Восстановите этап из snapshot; изменения процесса "
                        "оформляйте новой версией методологии."
                    ),
                )
            if not stage.completion_criteria:
                add(
                    "blocking",
                    "stage_completion_criteria_missing",
                    "stage",
                    stage.id,
                    stage.source_key,
                    stage.title,
                    "completion_criteria",
                    "Для этапа методологии не задан критерий завершения.",
                    "Заполните критерий или обновите snapshot методологии.",
    )
    stage_ids = {stage.id for stage in stages}
    milestone_ids = {milestone.id for milestone in milestones}
    milestone_bound_task_ids = {
        dependency.predecessor_task_id
        for dependency in dependencies
        if dependency.predecessor_task_id is not None
        and dependency.successor_milestone_id is not None
        and dependency.successor_milestone_id in milestone_ids
    }
    for task in tasks:
        ref = f"PRJ-{task.task_number}"
        if task.assignee_id is None:
            add(
                "blocking",
                "task_assignee_missing",
                "task",
                task.id,
                ref,
                task.title,
                "assignee_id",
                "У задачи нет исполнителя.",
                "Назначьте участника проекта, который отвечает за результат.",
            )
        if not task.acceptance_criteria:
            add(
                "blocking",
                "task_acceptance_missing",
                "task",
                task.id,
                ref,
                task.title,
                "acceptance_criteria",
                "Не определен проверяемый критерий приемки задачи.",
                "Опишите наблюдаемый результат, по которому задача принимается.",
            )
        if task.baseline_starts_at is None or task.baseline_due_at is None:
            add(
                "blocking",
                "task_baseline_missing",
                "task",
                task.id,
                ref,
                task.title,
                "baseline_starts_at",
                "У задачи нет полного базового интервала.",
                "Укажите дату начала и дату окончания задачи.",
            )
        elif (
            (project_start and task.baseline_starts_at < project_start)
            or (project_due and task.baseline_due_at > project_due)
        ):
            add(
                "blocking",
                "task_outside_project_baseline",
                "task",
                task.id,
                ref,
                task.title,
                "baseline_due_at",
                "Базовый интервал задачи выходит за границы проекта.",
                "Согласуйте базовые сроки задачи и проекта до активации.",
            )
        if mode == "methodology" and task.stage_id not in stage_ids:
            add(
                "blocking",
                "task_stage_missing",
                "task",
                task.id,
                ref,
                task.title,
                "stage_id",
                "Задача не отнесена к этапу методологии.",
                "Выберите этап, который формирует контекст и критерии работы.",
            )
        if (
            entity.entity_type == "project"
            and task.id not in milestone_bound_task_ids
        ):
            add(
                "blocking",
                "task_milestone_missing",
                "task",
                task.id,
                ref,
                task.title,
                "target_milestone_id",
                "Работа не привязана к контрольной точке.",
                "Укажите, какую проверку или решение подготавливает эта работа.",
            )
    for milestone in milestones:
        ref = f"КТ-{milestone.milestone_number}"
        if milestone.decision_owner_id is None:
            add(
                "blocking",
                "milestone_decision_owner_missing",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "decision_owner_id",
                "Не указан ответственный за подтверждение контрольной точки.",
                "Назначьте участника, который зафиксирует факт прохождения.",
            )
        if not milestone.acceptance_criteria:
            add(
                "blocking",
                "milestone_acceptance_missing",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "acceptance_criteria",
                "Не определен проверяемый критерий прохождения контрольной точки.",
                "Опишите решение, результат или набор условий, подтверждающих прохождение.",
            )
        if milestone.baseline_at is None:
            add(
                "blocking",
                "milestone_baseline_missing",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "baseline_at",
                "У контрольной точки нет базовой даты.",
                "Укажите одну дату события: контрольная точка не имеет длительности.",
            )
        elif (
            (project_start and milestone.baseline_at < project_start)
            or (project_due and milestone.baseline_at > project_due)
        ):
            add(
                "blocking",
                "milestone_outside_project_baseline",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "baseline_at",
                "Базовая дата контрольной точки выходит за границы проекта.",
                "Согласуйте базовую дату точки и границы проекта до активации.",
            )
        if (
            milestone.criticality in {"key", "critical"}
            and not milestone.criticality_reason
        ):
            add(
                "blocking",
                "milestone_criticality_reason_missing",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "criticality_reason",
                "Не объяснено, почему точка ключевая или критическая.",
                "Укажите обязательство, решение или зависимость, которую она контролирует.",
            )
        if mode == "methodology" and milestone.stage_id not in stage_ids:
            add(
                "blocking",
                "milestone_stage_missing",
                "milestone",
                milestone.id,
                ref,
                milestone.title,
                "stage_id",
                "Контрольная точка не отнесена к этапу методологии.",
                "Выберите этап и проверьте его критерии перехода.",
            )
    blocking_count = sum(item.severity == "blocking" for item in issues)
    warning_count = sum(item.severity == "warning" for item in issues)
    return WorkEntityReadinessRead(
        entity_id=entity.id,
        can_activate=blocking_count == 0,
        blocking_count=blocking_count,
        warning_count=warning_count,
        issues=issues,
    )


def _target_filter(target_type: WorkEntityTargetType, target_id: UUID):
    column = {
        "entity": WorkEntityLink.target_entity_id,
        "task": WorkEntityLink.task_id,
        "personal_task": WorkEntityLink.personal_task_id,
        "quick_note": WorkEntityLink.quick_note_id,
        "deadline_tracker": WorkEntityLink.deadline_tracker_id,
    }[target_type]
    return column == target_id


@router.get("/link-options", response_model=list[WorkEntityLinkOption])
async def link_options(
    target_type: WorkEntityTargetType,
    search: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=100),
    exclude_entity_id: UUID | None = None,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Search only objects the current user can already access."""
    if target_type == "task" and not user.can_link_queue_tasks_to_projects:
        raise HTTPException(
            status_code=403,
            detail="Администратор не выдал право связывать Q-задачи с проектами",
        )
    return await list_link_options(
        db,
        target_type,
        user,
        search,
        limit,
        exclude_entity_id=exclude_entity_id,
    )


@router.get("/links/by-target", response_model=list[WorkEntityReverseLinkRead])
async def links_by_target(
    target_type: WorkEntityTargetType,
    target_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """List accessible entities connected to an object without granting new access."""
    if not await target_is_accessible(db, target_type, target_id, user):
        raise HTTPException(status_code=404, detail="Связанный объект не найден")
    links = (
        await db.execute(
            select(WorkEntityLink).where(_target_filter(target_type, target_id))
        )
    ).scalars().all()
    result: list[WorkEntityReverseLinkRead] = []
    for link in links:
        access = await get_entity_access(db, link.entity_id, user.id)
        if not access:
            continue
        entity, access_role = access
        result.append(
            WorkEntityReverseLinkRead(
                link_id=link.id,
                entity_id=entity.id,
                entity_type=entity.entity_type,
                entity_title=entity.title,
                entity_status=entity.status,
                relation_type=link.relation_type,
                access_role=access_role,
            )
        )
    return result


@router.get("", response_model=list[WorkEntityRead])
async def list_work_entities(
    entity_type: WorkEntityType | None = None,
    status_filter: WorkEntityStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=120),
    include_archived: bool = False,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """List current user's owned and explicitly shared entities."""
    rows = await list_accessible_entities(db, user.id)
    normalized_search = search.strip().lower() if search and search.strip() else None
    filtered = [
        (entity, access_role)
        for entity, access_role in rows
        if (include_archived or entity.status != "archived")
        and (entity_type is None or entity.entity_type == entity_type)
        and (status_filter is None or entity.status == status_filter)
        and (
            normalized_search is None
            or normalized_search in entity.title.lower()
            or normalized_search in (entity.description or "").lower()
            or any(normalized_search in tag.lower() for tag in (entity.tags or []))
        )
    ]
    return await _entity_reads(db, filtered)


@router.post("", response_model=WorkEntityRead, status_code=status.HTTP_201_CREATED)
async def create_work_entity(
    body: WorkEntityCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Create a private-by-default project, goal, system, KPI context, or initiative."""
    if body.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=(
                "Новая сущность создается как черновик. Сначала сформируйте scope "
                "и устраните замечания проверки готовности."
            ),
        )
    entity = WorkEntity(
        owner_id=user.id,
        entity_type=body.entity_type,
        title=body.title,
        description=body.description,
        outcome_statement=body.outcome_statement,
        success_criteria=body.success_criteria,
        constraints=body.constraints,
        status=body.status,
        visibility=body.visibility,
        starts_at=body.starts_at,
        due_at=body.due_at,
        target_due_at=body.due_at,
        forecast_starts_at=body.starts_at,
        forecast_due_at=body.due_at,
        actual_starts_at=None,
        actual_due_at=None,
        planning_mode=body.planning_mode,
        methodology_title=body.methodology_title,
        methodology_version=body.methodology_version,
        methodology_snapshot=body.methodology_snapshot,
        baseline_locked_at=None,
        baseline_locked_by_id=None,
        tags=body.tags,
        details_json=body.details_json,
        archived_at=datetime.now(timezone.utc) if body.status == "archived" else None,
    )
    db.add(entity)
    await db.flush()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "entity_created",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "ref": None,
                "title": entity.title,
            },
            "action": "created",
            "changes": [
                {"field": "entity_type", "from": None, "to": entity.entity_type},
                {"field": "status", "from": None, "to": entity.status},
                {"field": "planning_mode", "from": None, "to": entity.planning_mode},
            ],
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="created",
    )
    await db.commit()
    await db.refresh(entity)
    return await _entity_read(db, entity, "owner")


@router.get("/{entity_id}", response_model=WorkEntityRead)
async def get_work_entity(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity, access_role = await _get_entity_or_404(db, entity_id, user)
    return await _entity_read(db, entity, access_role)


@router.get("/{entity_id}/readiness", response_model=WorkEntityReadinessRead)
async def get_work_entity_readiness(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    entity, _ = await _get_entity_or_404(db, entity_id, user)
    return await _build_readiness(db, entity)


@router.patch("/{entity_id}", response_model=WorkEntityRead)
async def update_work_entity(
    entity_id: UUID,
    body: WorkEntityUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, access_role = await _get_editable_entity_or_404(db, entity_id, user)
    requested_changes = body.model_dump(exclude_unset=True)
    if "visibility" in requested_changes and access_role != "owner":
        raise HTTPException(status_code=403, detail="Только владелец может изменить доступ")
    if access_role != "owner" and (
        entity.status == "archived"
        or requested_changes.get("status") == "archived"
    ):
        raise HTTPException(
            status_code=403,
            detail="Только владелец может архивировать или восстанавливать сущность",
        )
    changes = {
        field: value
        for field, value in requested_changes.items()
        if getattr(entity, field) != value
    }
    if not changes:
        return await _entity_read(db, entity, access_role)
    if "entity_type" in changes and entity.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                "Тип сущности фиксируется при запуске. "
                "Для преобразования создайте новый черновик."
            ),
        )
    if (
        "status" in changes
        and changes["status"] not in ENTITY_STATUS_TRANSITIONS[entity.status]
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Переход из статуса «{entity.status}» "
                f"в статус «{changes['status']}» не допускается."
            ),
        )
    locked_fields = {
        "entity_type",
        "starts_at",
        "due_at",
        "outcome_statement",
        "success_criteria",
        "constraints",
        "planning_mode",
        "methodology_title",
        "methodology_version",
        "methodology_snapshot",
    }
    if entity.baseline_locked_at and locked_fields & set(changes):
        raise HTTPException(
            status_code=409,
            detail=(
                "Базовый график и версия методологии уже зафиксированы. "
                "Изменяйте прогноз через управляемый перенос или создайте "
                "новую утверждаемую версию базового плана."
            ),
        )
    starts_at = changes.get("starts_at", entity.starts_at)
    due_at = changes.get("due_at", entity.due_at)
    _validate_dates(starts_at, due_at)
    if changes.get("visibility") == "private":
        members_count = (
            await db.execute(
                select(func.count(WorkEntityMember.id)).where(
                    WorkEntityMember.entity_id == entity.id
                )
            )
        ).scalar_one()
        if members_count:
            raise HTTPException(
                status_code=409,
                detail="Сначала удалите участников проекта",
            )
    if "starts_at" in changes or "due_at" in changes:
        project_tasks = list(
            (
                await db.execute(
                    select(WorkEntityTask).where(
                        WorkEntityTask.entity_id == entity.id,
                        WorkEntityTask.status != "cancelled",
                    )
                )
            ).scalars().all()
        )
        invalid_tasks = [
            task
            for task in project_tasks
            if (
                starts_at
                and (
                    (
                        task.baseline_starts_at
                        and task.baseline_starts_at < starts_at
                    )
                    or (
                        task.baseline_due_at
                        and task.baseline_due_at < starts_at
                    )
                )
            )
            or (
                due_at
                and (
                    (
                        task.baseline_starts_at
                        and task.baseline_starts_at > due_at
                    )
                    or (
                        task.baseline_due_at
                        and task.baseline_due_at > due_at
                    )
                )
            )
        ]
        if invalid_tasks:
            sample = ", ".join(
                f"PRJ-{task.task_number} {task.title}"
                for task in invalid_tasks[:3]
            )
            raise HTTPException(
                status_code=409,
                detail=f"Новые сроки не включают проектные задачи: {sample}",
            )
        project_milestones = list(
            (
                await db.execute(
                    select(WorkEntityMilestone).where(
                        WorkEntityMilestone.entity_id == entity.id,
                        WorkEntityMilestone.status != "cancelled",
                    )
                )
            ).scalars().all()
        )
        invalid_milestones = [
            milestone
            for milestone in project_milestones
            if milestone.baseline_at
            and (
                (starts_at and milestone.baseline_at < starts_at)
                or (due_at and milestone.baseline_at > due_at)
            )
        ]
        if invalid_milestones:
            sample = ", ".join(
                f"КТ-{milestone.milestone_number} {milestone.title}"
                for milestone in invalid_milestones[:3]
            )
            raise HTTPException(
                status_code=409,
                detail=f"Новые сроки не включают контрольные точки: {sample}",
            )
    previous_status = entity.status
    previous_starts_at = entity.starts_at
    previous_due_at = entity.due_at
    previous_values = {
        field: jsonable_encoder(getattr(entity, field))
        for field in changes
    }
    if (
        previous_status == "draft"
        and "status" in changes
        and changes["status"] != "draft"
    ):
        if changes["status"] != "active":
            raise HTTPException(
                status_code=409,
                detail="Черновик можно сначала перевести только в активный статус.",
            )
        readiness = await _build_readiness(db, entity, overrides=changes)
        if not readiness.can_activate:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "entity_not_ready",
                    "message": (
                        "Проект нельзя активировать, пока не устранены "
                        "обязательные замечания."
                    ),
                    "readiness": readiness.model_dump(mode="json"),
                },
            )
    if changes.get("status") == "done":
        incomplete_tasks = list(
            (
                await db.execute(
                    select(WorkEntityTask).where(
                        WorkEntityTask.entity_id == entity.id,
                        WorkEntityTask.status.not_in({"done", "cancelled"}),
                    )
                )
            ).scalars().all()
        )
        incomplete_milestones = list(
            (
                await db.execute(
                    select(WorkEntityMilestone).where(
                        WorkEntityMilestone.entity_id == entity.id,
                        WorkEntityMilestone.status.not_in(
                            {"achieved", "cancelled"}
                        ),
                    )
                )
            ).scalars().all()
        )
        achieved_milestone_ids = list(
            (
                await db.execute(
                    select(WorkEntityMilestone.id).where(
                        WorkEntityMilestone.entity_id == entity.id,
                        WorkEntityMilestone.status == "achieved",
                    )
                )
            ).scalars().all()
        )
        evidenced_milestone_ids = set(
            (
                await db.execute(
                    select(WorkEntityArtifact.milestone_id).where(
                        WorkEntityArtifact.entity_id == entity.id,
                        WorkEntityArtifact.milestone_id.in_(
                            achieved_milestone_ids
                        ),
                        WorkEntityArtifact.artifact_type == "evidence",
                        WorkEntityArtifact.status == "active",
                    )
                )
            ).scalars().all()
        )
        missing_evidence_ids = (
            set(achieved_milestone_ids) - evidenced_milestone_ids
        )
        project_task_ids: set[UUID] = set()
        project_milestone_ids: set[UUID] = set()
        tasks_without_target_ids: set[UUID] = set()
        route_scope_missing = False
        if entity.entity_type == "project":
            project_task_ids = set(
                (
                    await db.execute(
                        select(WorkEntityTask.id).where(
                            WorkEntityTask.entity_id == entity.id,
                            WorkEntityTask.status != "cancelled",
                        )
                    )
                ).scalars().all()
            )
            project_milestone_ids = set(
                (
                    await db.execute(
                        select(WorkEntityMilestone.id).where(
                            WorkEntityMilestone.entity_id == entity.id,
                            WorkEntityMilestone.status != "cancelled",
                        )
                    )
                ).scalars().all()
            )
            bound_task_ids = set(
                (
                    await db.execute(
                        select(
                            WorkEntityScheduleDependency.predecessor_task_id
                        ).where(
                            WorkEntityScheduleDependency.entity_id == entity.id,
                            WorkEntityScheduleDependency.status == "active",
                            WorkEntityScheduleDependency.predecessor_task_id.in_(
                                project_task_ids
                            ),
                            WorkEntityScheduleDependency.successor_milestone_id.in_(
                                project_milestone_ids
                            ),
                        )
                    )
                ).scalars().all()
            )
            tasks_without_target_ids = project_task_ids - bound_task_ids
            route_scope_missing = (
                not project_task_ids or not project_milestone_ids
            )
        if (
            incomplete_tasks
            or incomplete_milestones
            or missing_evidence_ids
            or tasks_without_target_ids
            or route_scope_missing
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "project_completion_blocked",
                    "message": (
                        "Проект нельзя завершить, пока работа не принята "
                        "и прохождение контрольных точек не подтверждено."
                    ),
                    "incomplete_tasks": len(incomplete_tasks),
                    "incomplete_milestones": len(incomplete_milestones),
                    "milestones_without_evidence": len(
                        missing_evidence_ids
                    ),
                    "tasks_without_target": len(tasks_without_target_ids),
                    "route_scope_missing": route_scope_missing,
                },
            )
    for field, value in changes.items():
        setattr(entity, field, value)
    if "starts_at" in changes:
        entity.forecast_starts_at = entity.starts_at
    if "due_at" in changes:
        entity.forecast_due_at = entity.due_at
        entity.target_due_at = entity.due_at
    if {"starts_at", "due_at"} & changes.keys():
        entity.schedule_revision += 1
    if (
        "status" in changes
        and previous_status == "draft"
        and entity.status in {"active", "paused", "done"}
    ):
        entity.baseline_locked_at = datetime.now(timezone.utc)
        entity.baseline_locked_by_id = user.id
        entity.baseline_outcome_statement = entity.outcome_statement
        entity.baseline_success_criteria = entity.success_criteria
        entity.baseline_constraints = entity.constraints
        entity.actual_starts_at = entity.actual_starts_at or datetime.now(timezone.utc)
    if "status" in changes and entity.status == "done":
        entity.actual_due_at = entity.actual_due_at or datetime.now(timezone.utc)
    if entity.status == "archived" and previous_status != "archived":
        entity.archived_at = datetime.now(timezone.utc)
    elif entity.status != "archived":
        entity.archived_at = None
    entity.updated_at = datetime.now(timezone.utc)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "entity_updated",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "ref": None,
                "title": entity.title,
            },
            "action": "updated",
            "changes": [
                {
                    "field": field,
                    "from": previous_values[field],
                    "to": jsonable_encoder(getattr(entity, field)),
                }
                for field in sorted(changes)
            ],
            "fields": sorted(changes.keys()),
            "from_status": previous_status if "status" in changes else None,
            "to_status": entity.status if "status" in changes else None,
            "from_starts_at": (
                jsonable_encoder(previous_starts_at)
                if "starts_at" in changes
                else None
            ),
            "to_starts_at": (
                jsonable_encoder(entity.starts_at)
                if "starts_at" in changes
                else None
            ),
            "from_due_at": (
                jsonable_encoder(previous_due_at)
                if "due_at" in changes
                else None
            ),
            "to_due_at": (
                jsonable_encoder(entity.due_at)
                if "due_at" in changes
                else None
            ),
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="updated",
    )
    await db.commit()
    await db.refresh(entity)
    return await _entity_read(db, entity, access_role)


@router.post("/{entity_id}/archive", response_model=WorkEntityRead)
async def archive_work_entity(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _get_owned_entity_or_404(db, entity_id, user)
    entity.status = "archived"
    entity.archived_at = datetime.now(timezone.utc)
    entity.updated_at = datetime.now(timezone.utc)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "entity_archived",
        {
            "schema_version": 1,
            "object": {
                "type": "entity",
                "id": str(entity.id),
                "ref": None,
                "title": entity.title,
            },
            "action": "archived",
            "changes": [
                {"field": "status", "from": None, "to": "archived"}
            ],
        },
        object_type="entity",
        object_id=entity.id,
        object_title=entity.title,
        action="archived",
    )
    await db.commit()
    await db.refresh(entity)
    return await _entity_read(db, entity, "owner")


@router.get("/{entity_id}/summary", response_model=WorkEntitySummary)
async def get_work_entity_summary(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await _get_entity_or_404(db, entity_id, user)
    links = (
        await db.execute(
            select(WorkEntityLink)
            .where(WorkEntityLink.entity_id == entity_id)
            .order_by(WorkEntityLink.position, WorkEntityLink.created_at)
        )
    ).scalars().all()
    return await build_entity_summary(db, entity_id, list(links), user)


@router.get("/{entity_id}/links", response_model=list[WorkEntityLinkRead])
async def list_work_entity_links(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await _get_entity_or_404(db, entity_id, user)
    links = (
        await db.execute(
            select(WorkEntityLink)
            .where(WorkEntityLink.entity_id == entity_id)
            .order_by(WorkEntityLink.position, WorkEntityLink.created_at)
        )
    ).scalars().all()
    return await serialize_links(db, list(links), user)


@router.post(
    "/{entity_id}/links",
    response_model=WorkEntityLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_entity_link(
    entity_id: UUID,
    body: WorkEntityLinkCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _get_editable_entity_or_404(db, entity_id, user)
    if body.target_type == "task" and not user.can_link_queue_tasks_to_projects:
        raise HTTPException(
            status_code=403,
            detail="Администратор не выдал право связывать Q-задачи с проектами",
        )
    if entity.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный проект нельзя изменять")
    if body.target_type == "entity" and body.target_id == entity.id:
        raise HTTPException(status_code=400, detail="Нельзя связать сущность с самой собой")
    if not await target_is_accessible(db, body.target_type, body.target_id, user):
        raise HTTPException(status_code=404, detail="Связанный объект не найден или недоступен")
    await _require_owned_quick_note_link_target(
        db,
        body.target_type,
        body.target_id,
        user.id,
    )
    if body.target_type == "entity" and body.relation_type != "related":
        await lock_entity_graph(db)
    if (
        body.target_type == "entity"
        and await would_create_structural_cycle(
            db,
            entity.id,
            body.target_id,
            body.relation_type,
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="Эта связь создаст цикл в структуре проектов и целей",
        )
    existing = (
        await db.execute(
            select(WorkEntityLink).where(
                WorkEntityLink.entity_id == entity.id,
                _target_filter(body.target_type, body.target_id),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Объект уже связан с этой сущностью")
    link = WorkEntityLink(
        entity_id=entity.id,
        relation_type=body.relation_type,
        notes=body.notes,
        position=body.position,
        created_by_id=user.id,
        **target_column_values(body.target_type, body.target_id),
    )
    db.add(link)
    await db.flush()
    serialized_link = (await serialize_links(db, [link], user))[0]
    target_label = serialized_link.target_title or (
        f"{body.target_type}:{body.target_id}"
    )
    record_entity_event(
        db,
        entity.id,
        user.id,
        "link_added",
        {
            "schema_version": 1,
            "object": {
                "type": "link",
                "id": str(link.id),
                "ref": None,
                "title": target_label,
            },
            "action": "created",
            "changes": [
                {
                    "field": "target",
                    "from": None,
                    "to": target_label,
                },
                {
                    "field": "relation_type",
                    "from": None,
                    "to": body.relation_type,
                },
            ],
            "target_type": body.target_type,
            "target_id": str(body.target_id),
        },
        object_type="link",
        object_id=link.id,
        object_title=target_label,
        action="created",
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Связь уже существует") from exc
    await db.refresh(link)
    return (await serialize_links(db, [link], user))[0]


@router.patch("/{entity_id}/links/{link_id}", response_model=WorkEntityLinkRead)
async def update_work_entity_link(
    entity_id: UUID,
    link_id: UUID,
    body: WorkEntityLinkUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _get_editable_entity_or_404(db, entity_id, user)
    if entity.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный проект нельзя изменять")
    link = (
        await db.execute(
            select(WorkEntityLink).where(
                WorkEntityLink.id == link_id,
                WorkEntityLink.entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Связь не найдена")
    if link.quick_note_id is not None:
        await _require_owned_quick_note_link_target(
            db,
            "quick_note",
            link.quick_note_id,
            user.id,
        )
    requested_changes = body.model_dump(exclude_unset=True)
    changes = {
        field: value
        for field, value in requested_changes.items()
        if getattr(link, field) != value
    }
    if not changes:
        return (await serialize_links(db, [link], user))[0]
    next_relation = changes.get("relation_type", link.relation_type)
    if link.target_entity_id is not None:
        await lock_entity_graph(db)
    if (
        link.target_entity_id is not None
        and await would_create_structural_cycle(
            db,
            entity.id,
            link.target_entity_id,
            next_relation,
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="Эта связь создаст цикл в структуре проектов и целей",
        )
    before = {field: getattr(link, field) for field in changes}
    for field, value in changes.items():
        setattr(link, field, value)
    link.updated_at = datetime.now(timezone.utc)
    serialized_link = (await serialize_links(db, [link], user))[0]
    target_label = serialized_link.target_title or f"Связь {link.id}"
    record_entity_event(
        db,
        entity.id,
        user.id,
        "link_updated",
        {
            "schema_version": 1,
            "object": {
                "type": "link",
                "id": str(link.id),
                "ref": None,
                "title": target_label,
            },
            "action": "updated",
            "changes": [
                {
                    "field": field,
                    "from": jsonable_encoder(before[field]),
                    "to": jsonable_encoder(getattr(link, field)),
                }
                for field in sorted(changes)
            ],
        },
        object_type="link",
        object_id=link.id,
        object_title=target_label,
        action="updated",
    )
    await db.commit()
    await db.refresh(link)
    return (await serialize_links(db, [link], user))[0]


@router.delete("/{entity_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_entity_link(
    entity_id: UUID,
    link_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity, _ = await _get_editable_entity_or_404(db, entity_id, user)
    if entity.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный проект нельзя изменять")
    link = (
        await db.execute(
            select(WorkEntityLink).where(
                WorkEntityLink.id == link_id,
                WorkEntityLink.entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Связь не найдена")
    if link.quick_note_id is not None:
        await _require_owned_quick_note_link_target(
            db,
            "quick_note",
            link.quick_note_id,
            user.id,
        )
    if link.target_entity_id is not None:
        await lock_entity_graph(db)
    serialized_link = (await serialize_links(db, [link], user))[0]
    target_label = serialized_link.target_title or f"Связь {link.id}"
    record_entity_event(
        db,
        entity.id,
        user.id,
        "link_removed",
        {
            "schema_version": 1,
            "object": {
                "type": "link",
                "id": str(link.id),
                "ref": None,
                "title": target_label,
            },
            "action": "removed",
            "changes": [],
            "target_type": link_target_type(link),
        },
        object_type="link",
        object_id=link.id,
        object_title=target_label,
        action="removed",
    )
    await db.delete(link)
    await db.commit()


@router.get("/{entity_id}/members", response_model=list[WorkEntityMemberRead])
async def list_work_entity_members(
    entity_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    _, access_role = await _get_entity_or_404(db, entity_id, user)
    rows = (
        await db.execute(
            select(WorkEntityMember, User)
            .join(User, User.id == WorkEntityMember.user_id)
            .where(WorkEntityMember.entity_id == entity_id)
            .order_by(User.full_name)
        )
    ).all()
    return [
        WorkEntityMemberRead(
            id=member.id,
            entity_id=member.entity_id,
            user_id=member.user_id,
            user_name=member_user.full_name,
            user_email=(
                member_user.email
                if access_role == "owner" or member.user_id == user.id
                else None
            ),
            role=member.role,
            created_at=member.created_at,
            updated_at=member.updated_at,
        )
        for member, member_user in rows
    ]


@router.post(
    "/{entity_id}/members",
    response_model=WorkEntityMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_work_entity_member(
    entity_id: UUID,
    body: WorkEntityMemberCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _get_owned_entity_or_404(db, entity_id, user)
    if body.user_id == user.id:
        raise HTTPException(status_code=400, detail="Владелец уже имеет полный доступ")
    member_user = (
        await db.execute(
            select(User).where(User.id == body.user_id, User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if not member_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if not await has_accepted_contact(db, user.id, member_user.id):
        raise HTTPException(
            status_code=400,
            detail="Сначала добавьте пользователя в контакты",
        )
    member = (
        await db.execute(
            select(WorkEntityMember).where(
                WorkEntityMember.entity_id == entity.id,
                WorkEntityMember.user_id == member_user.id,
            )
        )
    ).scalar_one_or_none()
    event_type = "member_updated" if member else "member_added"
    previous_role = member.role if member else None
    if member:
        if member.role == body.role:
            return WorkEntityMemberRead(
                id=member.id,
                entity_id=member.entity_id,
                user_id=member.user_id,
                user_name=member_user.full_name,
                user_email=member_user.email,
                role=member.role,
                created_at=member.created_at,
                updated_at=member.updated_at,
            )
        if body.role == "viewer" and member.role in {"participant", "editor"}:
            counts = await _member_open_responsibilities(
                db,
                entity.id,
                member.user_id,
            )
            _ensure_member_can_lose_participant_role(*counts)
        member.role = body.role
        member.updated_at = datetime.now(timezone.utc)
    else:
        member = WorkEntityMember(
            entity_id=entity.id,
            user_id=member_user.id,
            role=body.role,
            created_by_id=user.id,
        )
        db.add(member)
    entity.visibility = "shared"
    entity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    record_entity_event(
        db,
        entity.id,
        user.id,
        event_type,
        {
            "schema_version": 1,
            "object": {
                "type": "member",
                "id": str(member.id),
                "ref": None,
                "title": member_user.full_name,
            },
            "action": "updated" if previous_role else "added",
            "changes": [
                {
                    "field": "role",
                    "from": previous_role,
                    "to": member.role,
                }
            ],
            "user_id": str(member.user_id),
        },
        object_type="member",
        object_id=member.id,
        object_title=member_user.full_name,
        action="updated" if previous_role else "added",
    )
    await db.commit()
    await db.refresh(member)
    return WorkEntityMemberRead(
        id=member.id,
        entity_id=member.entity_id,
        user_id=member.user_id,
        user_name=member_user.full_name,
        user_email=member_user.email,
        role=member.role,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


@router.patch(
    "/{entity_id}/members/{member_id}",
    response_model=WorkEntityMemberRead,
)
async def update_work_entity_member(
    entity_id: UUID,
    member_id: UUID,
    body: WorkEntityMemberUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _get_owned_entity_or_404(db, entity_id, user)
    row = (
        await db.execute(
            select(WorkEntityMember, User)
            .join(User, User.id == WorkEntityMember.user_id)
            .where(
                WorkEntityMember.id == member_id,
                WorkEntityMember.entity_id == entity.id,
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Участник не найден")
    member, member_user = row
    previous_role = member.role
    if member.role == body.role:
        return WorkEntityMemberRead(
            id=member.id,
            entity_id=member.entity_id,
            user_id=member.user_id,
            user_name=member_user.full_name,
            user_email=member_user.email,
            role=member.role,
            created_at=member.created_at,
            updated_at=member.updated_at,
        )
    if body.role == "viewer" and member.role in {"participant", "editor"}:
        counts = await _member_open_responsibilities(
            db,
            entity.id,
            member.user_id,
        )
        _ensure_member_can_lose_participant_role(*counts)
    member.role = body.role
    member.updated_at = datetime.now(timezone.utc)
    record_entity_event(
        db,
        entity.id,
        user.id,
        "member_updated",
        {
            "schema_version": 1,
            "object": {
                "type": "member",
                "id": str(member.id),
                "ref": None,
                "title": member_user.full_name,
            },
            "action": "updated",
            "changes": [
                {
                    "field": "role",
                    "from": previous_role,
                    "to": member.role,
                }
            ],
            "user_id": str(member.user_id),
        },
        object_type="member",
        object_id=member.id,
        object_title=member_user.full_name,
        action="updated",
    )
    await db.commit()
    await db.refresh(member)
    return WorkEntityMemberRead(
        id=member.id,
        entity_id=member.entity_id,
        user_id=member.user_id,
        user_name=member_user.full_name,
        user_email=member_user.email,
        role=member.role,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


@router.delete(
    "/{entity_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_work_entity_member(
    entity_id: UUID,
    member_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    await lock_entity_state(db)
    entity = await _get_owned_entity_or_404(db, entity_id, user)
    member = (
        await db.execute(
            select(WorkEntityMember).where(
                WorkEntityMember.id == member_id,
                WorkEntityMember.entity_id == entity.id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Участник не найден")
    counts = await _member_open_responsibilities(
        db,
        entity.id,
        member.user_id,
    )
    _ensure_member_can_lose_participant_role(*counts)
    member_user_name = (
        await db.execute(
            select(User.full_name).where(User.id == member.user_id)
        )
    ).scalar_one_or_none()
    record_entity_event(
        db,
        entity.id,
        user.id,
        "member_removed",
        {
            "schema_version": 1,
            "object": {
                "type": "member",
                "id": str(member.id),
                "ref": None,
                "title": member_user_name or "Удаленный участник",
            },
            "action": "removed",
            "changes": [
                {"field": "role", "from": member.role, "to": None}
            ],
            "user_id": str(member.user_id),
        },
        object_type="member",
        object_id=member.id,
        object_title=member_user_name or "Удаленный участник",
        action="removed",
    )
    remaining_members = (
        await db.execute(
            select(func.count(WorkEntityMember.id)).where(
                WorkEntityMember.entity_id == entity.id,
                WorkEntityMember.id != member.id,
            )
        )
    ).scalar_one()
    if remaining_members == 0:
        entity.visibility = "private"
        entity.updated_at = datetime.now(timezone.utc)
    await db.delete(member)
    await db.commit()


@router.get("/{entity_id}/events", response_model=list[WorkEntityEventRead])
async def list_work_entity_events(
    entity_id: UUID,
    limit: int = Query(100, ge=1, le=300),
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    _, access_role = await _get_entity_or_404(db, entity_id, user)
    if before_id is not None and before_created_at is None:
        raise HTTPException(
            status_code=400,
            detail="Для курсора события требуется дата",
        )
    stmt = (
        select(WorkEntityEvent, User)
        .outerjoin(User, User.id == WorkEntityEvent.actor_id)
        .where(WorkEntityEvent.entity_id == entity_id)
    )
    if before_created_at is not None:
        cursor_filter = WorkEntityEvent.created_at < before_created_at
        if before_id is not None:
            cursor_filter = or_(
                cursor_filter,
                and_(
                    WorkEntityEvent.created_at == before_created_at,
                    WorkEntityEvent.id < before_id,
                ),
            )
        stmt = stmt.where(cursor_filter)
    rows = (
        await db.execute(
            stmt.order_by(
                WorkEntityEvent.created_at.desc(),
                WorkEntityEvent.id.desc(),
            ).limit(limit)
        )
    ).all()
    return [
        WorkEntityEventRead(
            id=event.id,
            entity_id=event.entity_id,
            actor_id=event.actor_id,
            actor_name=actor.full_name if actor else None,
            event_type=event.event_type,
            object_type=event.object_type,
            object_id=event.object_id,
            object_ref=event.object_ref,
            object_title=event.object_title,
            action=event.action,
            reason=event.reason,
            correlation_id=event.correlation_id,
            payload=jsonable_encoder(
                redact_entity_event_payload(
                    event.payload,
                    can_view_emails=access_role == "owner",
                )
            ),
            created_at=event.created_at,
        )
        for event, actor in rows
    ]
