"""Access control and read models for the entity graph."""
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deadline_tracker import DeadlineTracker
from app.models.personal_task import PersonalTask
from app.models.quick_note import QuickNote
from app.models.quick_note_share import QuickNoteShare
from app.models.task import Task
from app.models.user import User, UserRole
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityEvent,
    WorkEntityLink,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityTask,
)
from app.schemas.work_entity import (
    WorkEntityAccessRole,
    WorkEntityLinkOption,
    WorkEntityLinkRead,
    WorkEntitySummary,
    WorkEntityTargetType,
)

STRUCTURAL_RELATIONS = {"contains", "contributes_to", "depends_on", "measures"}
ENTITY_GRAPH_ADVISORY_LOCK_KEY = 460046
ENTITY_STATE_ADVISORY_LOCK_KEY = 460045


async def get_entity_access(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
) -> tuple[WorkEntity, WorkEntityAccessRole] | None:
    """Return an entity only when the user owns it or has an active shared membership."""
    result = await db.execute(
        select(WorkEntity, WorkEntityMember.role)
        .outerjoin(
            WorkEntityMember,
            and_(
                WorkEntityMember.entity_id == WorkEntity.id,
                WorkEntityMember.user_id == user_id,
            ),
        )
        .where(
            WorkEntity.id == entity_id,
            or_(
                WorkEntity.owner_id == user_id,
                and_(
                    WorkEntity.visibility == "shared",
                    WorkEntityMember.id.is_not(None),
                ),
            ),
        )
    )
    row = result.first()
    if not row:
        return None
    entity, member_role = row
    access_role: WorkEntityAccessRole = (
        "owner" if entity.owner_id == user_id else member_role
    )
    return entity, access_role


async def list_accessible_entities(
    db: AsyncSession,
    user_id: UUID,
) -> list[tuple[WorkEntity, WorkEntityAccessRole]]:
    """List owned and explicitly shared entities without granting admin bypass."""
    result = await db.execute(
        select(WorkEntity, WorkEntityMember.role)
        .outerjoin(
            WorkEntityMember,
            and_(
                WorkEntityMember.entity_id == WorkEntity.id,
                WorkEntityMember.user_id == user_id,
            ),
        )
        .where(
            or_(
                WorkEntity.owner_id == user_id,
                and_(
                    WorkEntity.visibility == "shared",
                    WorkEntityMember.id.is_not(None),
                ),
            )
        )
        .order_by(
            WorkEntity.status == "archived",
            WorkEntity.forecast_due_at.is_(None),
            WorkEntity.forecast_due_at.asc(),
            WorkEntity.updated_at.desc(),
        )
    )
    return [
        (entity, "owner" if entity.owner_id == user_id else member_role)
        for entity, member_role in result.all()
    ]


def record_entity_event(
    db: AsyncSession,
    entity_id: UUID,
    actor_id: UUID | None,
    event_type: str,
    payload: dict | None = None,
    *,
    object_type: str | None = None,
    object_id: UUID | None = None,
    object_ref: str | None = None,
    object_title: str | None = None,
    action: str | None = None,
    reason: str | None = None,
    correlation_id: UUID | None = None,
) -> WorkEntityEvent:
    """Append an audit event that remains understandable without UI inference."""
    event = WorkEntityEvent(
        entity_id=entity_id,
        actor_id=actor_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        object_ref=object_ref,
        object_title=object_title,
        action=action,
        reason=reason,
        correlation_id=correlation_id,
        payload=payload,
    )
    db.add(event)
    return event


def redact_entity_event_payload(
    payload: dict | None,
    *,
    can_view_emails: bool,
) -> dict | None:
    """Remove identity fields that are not required for project collaboration."""
    if payload is None or can_view_emails:
        return payload

    def redact(value):
        if isinstance(value, dict):
            return {
                key: redact(item)
                for key, item in value.items()
                if "email" not in key.lower() and key.lower() != "target_id"
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(payload)


def link_target_type(link: WorkEntityLink) -> WorkEntityTargetType:
    if link.target_entity_id is not None:
        return "entity"
    if link.task_id is not None:
        return "task"
    if link.personal_task_id is not None:
        return "personal_task"
    if link.quick_note_id is not None:
        return "quick_note"
    return "deadline_tracker"


def link_target_id(link: WorkEntityLink) -> UUID:
    for value in (
        link.target_entity_id,
        link.task_id,
        link.personal_task_id,
        link.quick_note_id,
        link.deadline_tracker_id,
    ):
        if value is not None:
            return value
    raise ValueError("Entity link has no target")


def target_column_values(target_type: WorkEntityTargetType, target_id: UUID) -> dict:
    """Map API target discriminator to one concrete FK column."""
    return {
        "target_entity_id": target_id if target_type == "entity" else None,
        "task_id": target_id if target_type == "task" else None,
        "personal_task_id": target_id if target_type == "personal_task" else None,
        "quick_note_id": target_id if target_type == "quick_note" else None,
        "deadline_tracker_id": target_id if target_type == "deadline_tracker" else None,
    }


def _task_access_filter(user: User):
    if user.role in (UserRole.admin, UserRole.teamlead):
        return True
    return Task.assignee_id == user.id


async def lock_entity_graph(db: AsyncSession) -> None:
    """Serialize structural graph writes for transaction-safe cycle checks."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": ENTITY_GRAPH_ADVISORY_LOCK_KEY},
    )


async def lock_entity_state(db: AsyncSession) -> None:
    """Serialize project membership, assignment, and date-boundary writes."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": ENTITY_STATE_ADVISORY_LOCK_KEY},
    )


async def target_is_accessible(
    db: AsyncSession,
    target_type: WorkEntityTargetType,
    target_id: UUID,
    user: User,
) -> bool:
    """Validate target existence and access before persisting a link."""
    if target_type == "entity":
        return await get_entity_access(db, target_id, user.id) is not None
    if target_type == "task":
        result = await db.execute(
            select(Task.id).where(Task.id == target_id, _task_access_filter(user))
        )
        return result.scalar_one_or_none() is not None
    if target_type == "personal_task":
        result = await db.execute(
            select(PersonalTask.id).where(
                PersonalTask.id == target_id,
                PersonalTask.owner_id == user.id,
            )
        )
        return result.scalar_one_or_none() is not None
    if target_type == "quick_note":
        result = await db.execute(
            select(QuickNote.id)
            .outerjoin(
                QuickNoteShare,
                and_(
                    QuickNoteShare.note_id == QuickNote.id,
                    QuickNoteShare.recipient_id == user.id,
                    QuickNoteShare.status == "active",
                ),
            )
            .where(
                QuickNote.id == target_id,
                or_(
                    QuickNote.owner_id == user.id,
                    QuickNoteShare.id.is_not(None),
                ),
            )
        )
        return result.scalar_one_or_none() is not None
    result = await db.execute(
        select(DeadlineTracker.id).where(
            DeadlineTracker.id == target_id,
            DeadlineTracker.owner_id == user.id,
        )
    )
    return result.scalar_one_or_none() is not None


async def serialize_links(
    db: AsyncSession,
    links: list[WorkEntityLink],
    user: User,
) -> list[WorkEntityLinkRead]:
    """Enrich links in batches and suppress data the viewer cannot access."""
    ids_by_type: dict[WorkEntityTargetType, set[UUID]] = {
        "entity": set(),
        "task": set(),
        "personal_task": set(),
        "quick_note": set(),
        "deadline_tracker": set(),
    }
    for link in links:
        ids_by_type[link_target_type(link)].add(link_target_id(link))

    entity_map: dict[UUID, WorkEntity] = {}
    if ids_by_type["entity"]:
        result = await db.execute(
            select(WorkEntity, WorkEntityMember.role)
            .outerjoin(
                WorkEntityMember,
                and_(
                    WorkEntityMember.entity_id == WorkEntity.id,
                    WorkEntityMember.user_id == user.id,
                ),
            )
            .where(
                WorkEntity.id.in_(ids_by_type["entity"]),
                or_(
                    WorkEntity.owner_id == user.id,
                    and_(
                        WorkEntity.visibility == "shared",
                        WorkEntityMember.id.is_not(None),
                    ),
                ),
            )
        )
        for entity, member_role in result.all():
            entity_map[entity.id] = entity

    task_map: dict[UUID, Task] = {}
    if ids_by_type["task"]:
        result = await db.execute(
            select(Task).where(
                Task.id.in_(ids_by_type["task"]),
                _task_access_filter(user),
            )
        )
        task_map = {task.id: task for task in result.scalars().all()}

    personal_task_map: dict[UUID, PersonalTask] = {}
    if ids_by_type["personal_task"]:
        result = await db.execute(
            select(PersonalTask).where(
                PersonalTask.id.in_(ids_by_type["personal_task"]),
                PersonalTask.owner_id == user.id,
            )
        )
        personal_task_map = {task.id: task for task in result.scalars().all()}

    quick_note_map: dict[UUID, QuickNote] = {}
    if ids_by_type["quick_note"]:
        result = await db.execute(
            select(QuickNote)
            .outerjoin(
                QuickNoteShare,
                and_(
                    QuickNoteShare.note_id == QuickNote.id,
                    QuickNoteShare.recipient_id == user.id,
                    QuickNoteShare.status == "active",
                ),
            )
            .where(
                QuickNote.id.in_(ids_by_type["quick_note"]),
                or_(
                    QuickNote.owner_id == user.id,
                    QuickNoteShare.id.is_not(None),
                ),
            )
        )
        quick_note_map = {note.id: note for note in result.scalars().unique().all()}

    tracker_map: dict[UUID, DeadlineTracker] = {}
    if ids_by_type["deadline_tracker"]:
        result = await db.execute(
            select(DeadlineTracker).where(
                DeadlineTracker.id.in_(ids_by_type["deadline_tracker"]),
                DeadlineTracker.owner_id == user.id,
            )
        )
        tracker_map = {tracker.id: tracker for tracker in result.scalars().all()}

    items: list[WorkEntityLinkRead] = []
    for link in links:
        target_type = link_target_type(link)
        raw_target_id = link_target_id(link)
        target = None
        if target_type == "entity":
            target = entity_map.get(raw_target_id)
        elif target_type == "task":
            target = task_map.get(raw_target_id)
        elif target_type == "personal_task":
            target = personal_task_map.get(raw_target_id)
        elif target_type == "quick_note":
            target = quick_note_map.get(raw_target_id)
        else:
            target = tracker_map.get(raw_target_id)

        values = {
            "target_id": raw_target_id if target is not None else None,
            "target_title": None,
            "target_subtitle": None,
            "target_status": None,
            "target_starts_at": None,
            "target_due_at": None,
        }
        if isinstance(target, WorkEntity):
            values.update(
                target_title=target.title,
                target_subtitle=target.entity_type,
                target_status=target.status,
                target_starts_at=target.starts_at,
                target_due_at=target.due_at,
            )
        elif isinstance(target, Task):
            values.update(
                target_title=target.title,
                target_subtitle=f"Q-{target.task_number}",
                target_status=target.status.value,
                target_starts_at=target.started_at,
                target_due_at=target.due_date,
            )
        elif isinstance(target, PersonalTask):
            values.update(
                target_title=target.title,
                target_subtitle=f"PT-{target.task_number}",
                target_status=target.status,
                target_starts_at=target.start_at,
                target_due_at=target.due_at,
            )
        elif isinstance(target, QuickNote):
            values.update(
                target_title=target.title or "Без названия",
                target_subtitle=target.context,
                target_status=target.status,
            )
        elif isinstance(target, DeadlineTracker):
            values.update(
                target_title=target.title,
                target_subtitle=target.tracker_type,
                target_status=target.status,
                target_starts_at=target.starts_at,
                target_due_at=target.due_at,
            )

        items.append(
            WorkEntityLinkRead(
                id=link.id,
                entity_id=link.entity_id,
                relation_type=link.relation_type,
                notes=link.notes,
                position=link.position,
                target_type=target_type,
                target_accessible=target is not None,
                created_by_id=link.created_by_id,
                created_at=link.created_at,
                updated_at=link.updated_at,
                **values,
            )
        )
    return items


async def build_entity_summary(
    db: AsyncSession,
    entity_id: UUID,
    links: list[WorkEntityLink],
    user: User,
) -> WorkEntitySummary:
    """Build a transparent summary of native work and accessible external links."""
    items = await serialize_links(db, links, user)
    accessible = [item for item in items if item.target_accessible]
    native_tasks = list(
        (
            await db.execute(
                select(WorkEntityTask).where(
                    WorkEntityTask.entity_id == entity_id,
                    WorkEntityTask.status != "cancelled",
                )
            )
        ).scalars().all()
    )
    native_milestones = list(
        (
            await db.execute(
                select(WorkEntityMilestone).where(
                    WorkEntityMilestone.entity_id == entity_id,
                    WorkEntityMilestone.status != "cancelled",
                )
            )
        ).scalars().all()
    )
    artifacts_count = int(
        (
            await db.execute(
                select(func.count(WorkEntityArtifact.id)).where(
                    WorkEntityArtifact.entity_id == entity_id,
                    WorkEntityArtifact.status != "archived",
                )
            )
        ).scalar_one()
    )
    now = datetime.now(timezone.utc)
    work_types = {"task", "personal_task", "deadline_tracker"}
    excluded_statuses = {
        "task": {"cancelled"},
        "personal_task": {"archived"},
        "deadline_tracker": {"archived"},
    }
    work_items = [
        item
        for item in accessible
        if item.target_type in work_types
        and item.target_status not in excluded_statuses.get(item.target_type, set())
    ]
    open_work_items = [item for item in work_items if item.target_status != "done"]
    open_native_tasks = [task for task in native_tasks if task.status != "done"]
    open_native_milestones = [
        milestone
        for milestone in native_milestones
        if milestone.status != "achieved"
    ]
    due_dates = [
        item.target_due_at
        for item in open_work_items
        if item.target_due_at is not None
    ]
    due_dates.extend(
        task.forecast_due_at
        for task in open_native_tasks
        if task.forecast_due_at is not None
    )
    due_dates.extend(
        milestone.forecast_at for milestone in open_native_milestones
    )
    future_due_dates = [due for due in due_dates if due >= now]
    overdue = sum(
        1
        for item in open_work_items
        if item.target_due_at is not None
        and item.target_due_at < now
    )
    overdue += sum(
        1
        for task in open_native_tasks
        if task.forecast_due_at is not None and task.forecast_due_at < now
    )
    overdue += sum(
        1
        for milestone in open_native_milestones
        if milestone.forecast_at < now
    )
    counts_by_type = Counter(item.target_type for item in accessible)
    counts_by_type.update("project_task" for _ in native_tasks)
    counts_by_type.update("project_milestone" for _ in native_milestones)
    counts_by_status = Counter(
        item.target_status for item in accessible if item.target_status
    )
    counts_by_status.update(task.status for task in native_tasks)
    counts_by_status.update(milestone.status for milestone in native_milestones)
    return WorkEntitySummary(
        entity_id=entity_id,
        accessible_links=len(accessible),
        restricted_links=len(items) - len(accessible),
        native_tasks=len(native_tasks),
        artifacts=artifacts_count,
        work_items_total=(
            len(work_items) + len(native_tasks) + len(native_milestones)
        ),
        work_items_done=(
            sum(1 for item in work_items if item.target_status == "done")
            + sum(1 for task in native_tasks if task.status == "done")
            + sum(
                1
                for milestone in native_milestones
                if milestone.status == "achieved"
            )
        ),
        overdue_items=overdue,
        next_due_at=min(future_due_dates) if future_due_dates else None,
        counts_by_type=dict(counts_by_type),
        counts_by_status=dict(counts_by_status),
    )


async def list_link_options(
    db: AsyncSession,
    target_type: WorkEntityTargetType,
    user: User,
    search: str | None,
    limit: int,
    exclude_entity_id: UUID | None = None,
) -> list[WorkEntityLinkOption]:
    """Return a small searchable list of targets the current user can already access."""
    pattern = f"%{search.strip()}%" if search and search.strip() else None
    options: list[WorkEntityLinkOption] = []
    if target_type == "entity":
        rows = await list_accessible_entities(db, user.id)
        for entity, _ in rows:
            if entity.id == exclude_entity_id:
                continue
            if pattern and search and search.strip().lower() not in entity.title.lower():
                continue
            options.append(
                WorkEntityLinkOption(
                    target_type=target_type,
                    target_id=entity.id,
                    title=entity.title,
                    subtitle=entity.entity_type,
                    status=entity.status,
                    starts_at=entity.forecast_starts_at or entity.starts_at,
                    due_at=entity.forecast_due_at or entity.due_at,
                )
            )
            if len(options) >= limit:
                break
        return options

    if target_type == "task":
        stmt = select(Task).where(_task_access_filter(user))
        if pattern:
            stmt = stmt.where(Task.title.ilike(pattern))
        result = await db.execute(stmt.order_by(Task.updated_at.desc()).limit(limit))
        return [
            WorkEntityLinkOption(
                target_type=target_type,
                target_id=task.id,
                title=task.title,
                subtitle=f"Q-{task.task_number}",
                status=task.status.value,
                starts_at=task.started_at,
                due_at=task.due_date,
            )
            for task in result.scalars().all()
        ]

    if target_type == "personal_task":
        stmt = select(PersonalTask).where(PersonalTask.owner_id == user.id)
        if pattern:
            stmt = stmt.where(PersonalTask.title.ilike(pattern))
        result = await db.execute(stmt.order_by(PersonalTask.updated_at.desc()).limit(limit))
        return [
            WorkEntityLinkOption(
                target_type=target_type,
                target_id=task.id,
                title=task.title,
                subtitle=f"PT-{task.task_number}",
                status=task.status,
                starts_at=task.start_at,
                due_at=task.due_at,
            )
            for task in result.scalars().all()
        ]

    if target_type == "quick_note":
        stmt = (
            select(QuickNote)
            .outerjoin(
                QuickNoteShare,
                and_(
                    QuickNoteShare.note_id == QuickNote.id,
                    QuickNoteShare.recipient_id == user.id,
                    QuickNoteShare.status == "active",
                ),
            )
            .where(
                or_(
                    QuickNote.owner_id == user.id,
                    QuickNoteShare.id.is_not(None),
                )
            )
        )
        if pattern:
            stmt = stmt.where(
                or_(
                    QuickNote.title.ilike(pattern),
                    QuickNote.body.ilike(pattern),
                    QuickNote.context.ilike(pattern),
                )
            )
        result = await db.execute(stmt.order_by(QuickNote.updated_at.desc()).limit(limit))
        return [
            WorkEntityLinkOption(
                target_type=target_type,
                target_id=note.id,
                title=note.title or "Без названия",
                subtitle=note.context,
                status=note.status,
            )
            for note in result.scalars().unique().all()
        ]

    stmt = select(DeadlineTracker).where(DeadlineTracker.owner_id == user.id)
    if pattern:
        stmt = stmt.where(DeadlineTracker.title.ilike(pattern))
    result = await db.execute(stmt.order_by(DeadlineTracker.updated_at.desc()).limit(limit))
    return [
        WorkEntityLinkOption(
            target_type=target_type,
            target_id=tracker.id,
            title=tracker.title,
            subtitle=tracker.tracker_type,
            status=tracker.status,
            starts_at=tracker.starts_at,
            due_at=tracker.due_at,
        )
        for tracker in result.scalars().all()
    ]


async def would_create_structural_cycle(
    db: AsyncSession,
    source_entity_id: UUID,
    target_entity_id: UUID,
    relation_type: str,
) -> bool:
    """Prevent directed cycles for structural relations while allowing `related` links."""
    if relation_type not in STRUCTURAL_RELATIONS:
        return False
    result = await db.execute(
        select(WorkEntityLink.entity_id, WorkEntityLink.target_entity_id).where(
            WorkEntityLink.target_entity_id.is_not(None),
            WorkEntityLink.relation_type.in_(STRUCTURAL_RELATIONS),
        )
    )
    adjacency: dict[UUID, set[UUID]] = {}
    for source_id, target_id in result.all():
        adjacency.setdefault(source_id, set()).add(target_id)
    adjacency.setdefault(source_entity_id, set()).add(target_entity_id)

    pending = [target_entity_id]
    visited: set[UUID] = set()
    while pending:
        current = pending.pop()
        if current == source_entity_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return False
