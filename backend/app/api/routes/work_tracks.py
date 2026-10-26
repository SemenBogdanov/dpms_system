"""API for task tracks and ordered work sequences."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role, require_task_workspace_access
from app.models.personal_task import PersonalTask
from app.models.task import Task, TaskStatus
from app.models.user import User, UserRole
from app.models.work_track import WorkMethodology, WorkTrack, WorkTrackItem
from app.schemas.work_track import (
    WorkMethodologyImport,
    WorkMethodologyRead,
    WorkTrackApplyMethodologyRequest,
    WorkTrackAssignedItemRead,
    WorkTrackCreate,
    WorkTrackItemCreate,
    WorkTrackItemRead,
    WorkTrackItemUpdate,
    WorkTrackRead,
    WorkTrackReadinessRead,
    WorkTrackActivationIssue,
    WorkTrackReservationDecisionRequest,
    WorkTrackReorderRequest,
    WorkTrackSendReviewRequest,
    WorkTrackUpdate,
)

router = APIRouter()

TRACK_STATUSES = {"draft", "active", "paused", "done", "archived"}
ITEM_STATUSES = {"active", "waiting", "blocked", "done", "skipped"}
RESERVATION_STATUSES = {"draft", "sent", "reserved", "declined", "released"}


async def _get_owned_track_or_404(db: AsyncSession, track_id: UUID, owner_id: UUID) -> WorkTrack:
    result = await db.execute(select(WorkTrack).where(WorkTrack.id == track_id, WorkTrack.owner_id == owner_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    return track


async def _get_track_item_or_404(db: AsyncSession, track_id: UUID, item_id: UUID) -> WorkTrackItem:
    result = await db.execute(
        select(WorkTrackItem).where(WorkTrackItem.id == item_id, WorkTrackItem.track_id == track_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Элемент трека не найден")
    return item


async def _get_methodology_or_404(db: AsyncSession, methodology_id: UUID) -> WorkMethodology:
    result = await db.execute(select(WorkMethodology).where(WorkMethodology.id == methodology_id))
    methodology = result.scalar_one_or_none()
    if not methodology:
        raise HTTPException(status_code=404, detail="Методология не найдена")
    return methodology


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _methodology_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _validate_methodology_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Методология должна быть JSON-объектом")
    if not isinstance(payload.get("stages"), list):
        raise HTTPException(status_code=400, detail="В методологии должен быть массив stages")
    if not isinstance(payload.get("cubes"), list):
        raise HTTPException(status_code=400, detail="В методологии должен быть массив cubes")
    if not isinstance(payload.get("routes"), dict):
        raise HTTPException(status_code=400, detail="В методологии должен быть объект routes")


def _compact_methodology_snapshot(methodology: WorkMethodology) -> dict[str, Any]:
    return {
        "id": str(methodology.id),
        "title": methodology.title,
        "schemaVersion": methodology.schema_version,
        "methodologyVersion": methodology.methodology_version,
        "displayVersion": methodology.display_version,
        "releaseKind": methodology.release_kind,
        "fingerprint": methodology.fingerprint,
    }


def _methodology_counts(payload: dict[str, Any]) -> tuple[int, int, int, int]:
    stages = payload.get("stages") if isinstance(payload.get("stages"), list) else []
    cubes = payload.get("cubes") if isinstance(payload.get("cubes"), list) else []
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    return len(stages), len(cubes), len(routes), len(products)


def _route_cube_ids(payload: dict[str, Any], route_key: str | None) -> list[str]:
    cubes = payload.get("cubes") if isinstance(payload.get("cubes"), list) else []
    if not route_key:
        return [str(cube.get("id")) for cube in cubes if isinstance(cube, dict) and cube.get("id")]
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    route = routes.get(route_key)
    if not isinstance(route, dict):
        raise HTTPException(status_code=400, detail="Маршрут методологии не найден")
    cube_keys = route.get("cubeKeys")
    if cube_keys == "all":
        return [str(cube.get("id")) for cube in cubes if isinstance(cube, dict) and cube.get("id")]
    if not isinstance(cube_keys, list):
        raise HTTPException(status_code=400, detail="Маршрут методологии не содержит список кубиков")
    result: list[str] = []
    for entry in cube_keys:
        if isinstance(entry, dict) and entry.get("id"):
            result.append(str(entry["id"]))
        elif isinstance(entry, str):
            result.append(entry)
    return result


def _route_snapshot(payload: dict[str, Any], route_key: str | None) -> dict[str, Any] | None:
    if not route_key:
        return None
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    route = routes.get(route_key)
    if not isinstance(route, dict):
        raise HTTPException(status_code=400, detail="Маршрут методологии не найден")
    return {"key": route_key, **route}


def _cube_checklist(payload: dict[str, Any], cube_id: str) -> list[Any] | dict[str, Any] | None:
    checklist_by_id = payload.get("cubeChecklistById")
    if isinstance(checklist_by_id, dict) and cube_id in checklist_by_id:
        return checklist_by_id[cube_id]
    default_checklist = payload.get("defaultCubeChecklist")
    if isinstance(default_checklist, (list, dict)):
        return default_checklist
    return None


def _cube_title(cube: dict[str, Any]) -> str:
    return str(cube.get("name") or cube.get("title") or cube.get("id") or "Кубик методологии")


def _route_name(route_snapshot: dict[str, Any] | None) -> str | None:
    if not route_snapshot:
        return None
    name = route_snapshot.get("name")
    return str(name) if name else None


def _checklist_items(checklist_snapshot: list[Any] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if isinstance(checklist_snapshot, list):
        result: list[dict[str, Any]] = []
        for index, item in enumerate(checklist_snapshot):
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or "").strip()
                checked = bool(item.get("checked"))
                blocking = bool(item.get("blocking", True))
            else:
                text = str(item).strip()
                checked = False
                blocking = True
            if text:
                result.append({"index": index, "text": text, "checked": checked, "blocking": blocking})
        return result
    if isinstance(checklist_snapshot, dict):
        raw_items = checklist_snapshot.get("items")
        if isinstance(raw_items, list):
            return _checklist_items(raw_items)
    return []


def _readiness_issues(track: WorkTrack, items: list[WorkTrackItem]) -> list[WorkTrackActivationIssue]:
    issues: list[WorkTrackActivationIssue] = []
    if not track.methodology_id:
        issues.append(
            WorkTrackActivationIssue(
                code="methodology_required",
                message="Для активации трека нужна активная методология и примененный маршрут.",
            )
        )
    if not track.due_at:
        issues.append(
            WorkTrackActivationIssue(
                code="track_due_required",
                message="Для активации трека нужен общий срок проекта/трека.",
            )
        )
    if not items:
        issues.append(
            WorkTrackActivationIssue(
                code="items_required",
                message="В треке должны быть этапы, задачи или кубики.",
            )
        )
    for item in items:
        title_value = item.title
        if not title_value and isinstance(item.methodology_snapshot, dict):
            title_value = item.methodology_snapshot.get("name")
        title = str(title_value or "Элемент трека")
        if item.item_type == "cube":
            if not item.due_at:
                issues.append(
                    WorkTrackActivationIssue(
                        item_id=item.id,
                        item_title=title,
                        code="cube_due_required",
                        message="У кубика должен быть срок до отправки исполнителю.",
                    )
                )
            if not item.proposed_executor_email:
                issues.append(
                    WorkTrackActivationIssue(
                        item_id=item.id,
                        item_title=title,
                        code="executor_email_required",
                        message="У кубика должен быть email предполагаемого исполнителя.",
                    )
                )
            checklist = _checklist_items(item.checklist_snapshot)
            unchecked = [entry for entry in checklist if entry["blocking"] and not entry["checked"]]
            if unchecked:
                issues.append(
                    WorkTrackActivationIssue(
                        item_id=item.id,
                        item_title=title,
                        code="checklist_required",
                        message=f"Не отмечены обязательные пункты чек-листа: {len(unchecked)}.",
                    )
                )
    return issues


async def _ensure_global_task_access(db: AsyncSession, task_id: UUID | None, user: User) -> None:
    if task_id is None:
        return
    result = await db.execute(select(Task.id, Task.assignee_id).where(Task.id == task_id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Связанная DPMS-задача не найдена")
    if user.role == UserRole.executor and row.assignee_id != user.id:
        raise HTTPException(status_code=403, detail="Нельзя добавить чужую DPMS-задачу в трек")


async def _ensure_personal_task_owner(db: AsyncSession, personal_task_id: UUID | None, owner_id: UUID) -> None:
    if personal_task_id is None:
        return
    result = await db.execute(
        select(PersonalTask.id).where(PersonalTask.id == personal_task_id, PersonalTask.owner_id == owner_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Связанная личная задача не найдена")


async def _ensure_item_not_duplicated(db: AsyncSession, track_id: UUID, body: WorkTrackItemCreate) -> None:
    if body.item_type == "task" and body.task_id is not None:
        result = await db.execute(
            select(WorkTrackItem.id).where(WorkTrackItem.track_id == track_id, WorkTrackItem.task_id == body.task_id)
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="Эта DPMS-задача уже добавлена в трек")
    if body.item_type == "personal_task" and body.personal_task_id is not None:
        result = await db.execute(
            select(WorkTrackItem.id).where(
                WorkTrackItem.track_id == track_id,
                WorkTrackItem.personal_task_id == body.personal_task_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="Эта личная задача уже добавлена в трек")
    if body.item_type == "cube" and body.methodology_id is not None and body.methodology_node_id:
        result = await db.execute(
            select(WorkTrackItem.id).where(
                WorkTrackItem.track_id == track_id,
                WorkTrackItem.methodology_id == body.methodology_id,
                WorkTrackItem.methodology_node_id == body.methodology_node_id,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="Этот кубик уже добавлен в трек")


async def _next_position(db: AsyncSession, track_id: UUID) -> int:
    result = await db.execute(select(func.max(WorkTrackItem.position)).where(WorkTrackItem.track_id == track_id))
    current = result.scalar_one_or_none()
    return int(current or 0) + 10


async def _track_items(db: AsyncSession, track_id: UUID) -> list[WorkTrackItem]:
    result = await db.execute(
        select(WorkTrackItem)
        .where(WorkTrackItem.track_id == track_id)
        .order_by(WorkTrackItem.position.asc(), WorkTrackItem.created_at.asc())
    )
    return list(result.scalars().all())


def _linked_task_done(task: Task | None) -> bool:
    return bool(task and getattr(task.status, "value", task.status) == TaskStatus.done.value)


def _linked_personal_task_done(task: PersonalTask | None) -> bool:
    return bool(task and task.status == "done")


def _item_done(item: WorkTrackItem, task: Task | None, personal_task: PersonalTask | None) -> bool:
    if item.item_type == "task":
        return _linked_task_done(task)
    if item.item_type == "personal_task":
        return _linked_personal_task_done(personal_task)
    return item.status in {"done", "skipped"}


def _item_effective_due_at(
    item: WorkTrackItem,
    task: Task | None,
    personal_task: PersonalTask | None,
) -> datetime | None:
    return item.due_at or (task.due_date if task else None) or (personal_task.due_at if personal_task else None)


def _serialize_item(
    item: WorkTrackItem,
    task: Task | None,
    personal_task: PersonalTask | None,
) -> WorkTrackItemRead:
    linked_title: str | None = None
    linked_number: int | None = None
    linked_status: str | None = None
    linked_due_at: datetime | None = None
    source_available = True
    if item.item_type == "task":
        source_available = task is not None
        if task:
            linked_title = task.title
            linked_number = task.task_number
            linked_status = getattr(task.status, "value", task.status)
            linked_due_at = task.due_date
    elif item.item_type == "personal_task":
        source_available = personal_task is not None
        if personal_task:
            linked_title = personal_task.title
            linked_number = personal_task.task_number
            linked_status = personal_task.status
            linked_due_at = personal_task.due_at
    methodology_title = None
    if item.item_type == "cube" and isinstance(item.methodology_snapshot, dict):
        methodology_title = _cube_title(item.methodology_snapshot)
    effective_title = item.title or linked_title or methodology_title or "Без названия"
    effective_due_at = _item_effective_due_at(item, task, personal_task)
    return WorkTrackItemRead(
        id=item.id,
        track_id=item.track_id,
        item_type=item.item_type,
        task_id=item.task_id,
        personal_task_id=item.personal_task_id,
        methodology_id=item.methodology_id,
        methodology_node_type=item.methodology_node_type,
        methodology_node_id=item.methodology_node_id,
        methodology_stage_id=item.methodology_stage_id,
        methodology_snapshot=item.methodology_snapshot,
        checklist_snapshot=item.checklist_snapshot,
        proposed_executor_email=item.proposed_executor_email,
        proposed_executor_name=item.proposed_executor_name,
        reservation_status=item.reservation_status,
        title=item.title,
        description=item.description,
        status=item.status,
        position=item.position,
        starts_at=item.starts_at,
        due_at=item.due_at,
        notes=item.notes,
        linked_title=linked_title,
        linked_number=linked_number,
        linked_status=linked_status,
        linked_due_at=linked_due_at,
        effective_title=effective_title,
        effective_due_at=effective_due_at,
        is_done=_item_done(item, task, personal_task),
        source_available=source_available,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _serialize_track(db: AsyncSession, track: WorkTrack, include_items: bool = True) -> WorkTrackRead:
    result = await db.execute(
        select(WorkTrackItem)
        .where(WorkTrackItem.track_id == track.id)
        .order_by(WorkTrackItem.position.asc(), WorkTrackItem.created_at.asc())
    )
    items = list(result.scalars().all())
    task_ids = [item.task_id for item in items if item.task_id]
    personal_task_ids = [item.personal_task_id for item in items if item.personal_task_id]
    task_map: dict[UUID, Task] = {}
    personal_task_map: dict[UUID, PersonalTask] = {}
    if task_ids:
        task_result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
        task_map = {task.id: task for task in task_result.scalars().all()}
    if personal_task_ids:
        personal_result = await db.execute(select(PersonalTask).where(PersonalTask.id.in_(personal_task_ids)))
        personal_task_map = {task.id: task for task in personal_result.scalars().all()}
    serialized_items = [
        _serialize_item(
            item,
            task_map.get(item.task_id) if item.task_id else None,
            personal_task_map.get(item.personal_task_id) if item.personal_task_id else None,
        )
        for item in items
    ]
    items_count = len(serialized_items)
    done_count = sum(1 for item in serialized_items if item.is_done)
    due_dates = [item.effective_due_at for item in serialized_items if item.effective_due_at and not item.is_done]
    next_due_at = min(due_dates) if due_dates else None
    progress_percent = round(done_count / items_count * 100) if items_count else 0
    methodology_title: str | None = None
    methodology_version: str | None = None
    if track.methodology_id:
        methodology_result = await db.execute(select(WorkMethodology).where(WorkMethodology.id == track.methodology_id))
        methodology = methodology_result.scalar_one_or_none()
        if methodology:
            methodology_title = methodology.title
            methodology_version = methodology.display_version or methodology.methodology_version
    return WorkTrackRead(
        id=track.id,
        owner_id=track.owner_id,
        title=track.title,
        description=track.description,
        status=track.status,
        start_at=track.start_at,
        due_at=track.due_at,
        color=track.color,
        methodology_id=track.methodology_id,
        methodology_title=methodology_title,
        methodology_version=methodology_version,
        product_key=track.product_key,
        route_key=track.route_key,
        route_name=_route_name(track.route_snapshot),
        methodology_snapshot=track.methodology_snapshot,
        route_snapshot=track.route_snapshot,
        items_count=items_count,
        done_count=done_count,
        progress_percent=progress_percent,
        next_due_at=next_due_at,
        items=serialized_items if include_items else [],
        created_at=track.created_at,
        updated_at=track.updated_at,
    )


@router.get("", response_model=list[WorkTrackRead])
async def list_work_tracks(
    status_filter: str = Query("active", alias="status"),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """List current user's task tracks."""
    query = select(WorkTrack).where(WorkTrack.owner_id == user.id)
    if status_filter != "all":
        if status_filter not in TRACK_STATUSES:
            raise HTTPException(status_code=400, detail="Некорректный статус трека")
        query = query.where(WorkTrack.status == status_filter)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(WorkTrack.title.ilike(pattern), WorkTrack.description.ilike(pattern)))
    query = query.order_by(
        WorkTrack.status.asc(),
        WorkTrack.due_at.is_(None),
        WorkTrack.due_at.asc(),
        WorkTrack.updated_at.desc(),
    ).limit(limit)
    result = await db.execute(query)
    tracks = list(result.scalars().all())
    return [await _serialize_track(db, track, include_items=True) for track in tracks]


@router.post("", response_model=WorkTrackRead, status_code=status.HTTP_201_CREATED)
async def create_work_track(
    body: WorkTrackCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Create a task track."""
    methodology: WorkMethodology | None = None
    route_snapshot = None
    if body.methodology_id:
        methodology = await _get_methodology_or_404(db, body.methodology_id)
        if not methodology.is_active:
            raise HTTPException(status_code=400, detail="Можно использовать только активную методологию")
        route_snapshot = _route_snapshot(methodology.payload, body.route_key)
    track = WorkTrack(
        owner_id=user.id,
        title=body.title,
        description=body.description,
        status=body.status,
        start_at=body.start_at,
        due_at=body.due_at,
        color=body.color or "slate",
        methodology_id=methodology.id if methodology else None,
        product_key=body.product_key,
        route_key=body.route_key,
        methodology_snapshot=_compact_methodology_snapshot(methodology) if methodology else None,
        route_snapshot=route_snapshot,
    )
    db.add(track)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.get("/methodologies", response_model=list[WorkMethodologyRead])
async def list_work_methodologies(
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List imported track methodologies."""
    _ = user
    result = await db.execute(
        select(WorkMethodology)
        .order_by(WorkMethodology.updated_at.desc(), WorkMethodology.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/methodologies/active", response_model=WorkMethodologyRead | None)
async def get_active_work_methodology(
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Read the methodology version currently selected by admin."""
    _ = user
    result = await db.execute(select(WorkMethodology).where(WorkMethodology.is_active.is_(True)).limit(1))
    return result.scalar_one_or_none()


@router.post("/methodologies/import", response_model=WorkMethodologyRead, status_code=status.HTTP_201_CREATED)
async def import_work_methodology(
    body: WorkMethodologyImport,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Import a versioned methodology JSON payload."""
    payload = body.payload
    _validate_methodology_payload(payload)
    fingerprint = _methodology_fingerprint(payload)
    existing_result = await db.execute(select(WorkMethodology).where(WorkMethodology.fingerprint == fingerprint))
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    stages_count, cubes_count, routes_count, products_count = _methodology_counts(payload)
    methodology = WorkMethodology(
        created_by_id=user.id,
        title=str(payload.get("title") or "Методология без названия")[:240],
        description=str(payload.get("description")) if payload.get("description") else None,
        schema_version=payload.get("schemaVersion") if isinstance(payload.get("schemaVersion"), int) else None,
        methodology_version=str(payload.get("methodologyVersion"))[:80] if payload.get("methodologyVersion") else None,
        display_version=str(payload.get("displayVersion"))[:80] if payload.get("displayVersion") else None,
        release_kind=str(payload.get("releaseKind"))[:80] if payload.get("releaseKind") else None,
        source_kind=body.source_kind,
        fingerprint=fingerprint,
        stages_count=stages_count,
        cubes_count=cubes_count,
        routes_count=routes_count,
        products_count=products_count,
        payload=payload,
    )
    db.add(methodology)
    await db.flush()
    await db.refresh(methodology)
    return methodology


@router.post("/methodologies/{methodology_id}/activate", response_model=WorkMethodologyRead)
async def activate_work_methodology(
    methodology_id: UUID,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Select the methodology version that tracks should use by default."""
    _ = user
    methodology = await _get_methodology_or_404(db, methodology_id)
    active_result = await db.execute(select(WorkMethodology).where(WorkMethodology.is_active.is_(True)))
    for item in active_result.scalars().all():
        item.is_active = False
        item.activated_at = None
        item.updated_at = datetime.now(timezone.utc)
    methodology.is_active = True
    methodology.activated_at = datetime.now(timezone.utc)
    methodology.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(methodology)
    return methodology


@router.get("/assigned-items", response_model=list[WorkTrackAssignedItemRead])
async def list_assigned_work_track_items(
    status_filter: str = Query("sent", alias="reservation_status"),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """List future track items proposed to the current user by email."""
    query = (
        select(WorkTrack, WorkTrackItem)
        .join(WorkTrackItem, WorkTrackItem.track_id == WorkTrack.id)
        .where(func.lower(WorkTrackItem.proposed_executor_email) == user.email.lower())
    )
    if status_filter != "all":
        if status_filter not in RESERVATION_STATUSES:
            raise HTTPException(status_code=400, detail="Некорректный статус бронирования")
        query = query.where(WorkTrackItem.reservation_status == status_filter)
    query = query.order_by(
        WorkTrackItem.due_at.is_(None),
        WorkTrackItem.due_at.asc(),
        WorkTrackItem.updated_at.desc(),
    ).limit(limit)
    result = await db.execute(query)
    rows = result.all()
    return [
        WorkTrackAssignedItemRead(
            track_id=track.id,
            track_title=track.title,
            track_owner_id=track.owner_id,
            item=_serialize_item(item, None, None),
        )
        for track, item in rows
    ]


@router.post("/assigned-items/{item_id}/decision", response_model=WorkTrackAssignedItemRead)
async def decide_assigned_work_track_item(
    item_id: UUID,
    body: WorkTrackReservationDecisionRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Accept or decline a future track item proposed to the current user."""
    result = await db.execute(
        select(WorkTrack, WorkTrackItem)
        .join(WorkTrackItem, WorkTrackItem.track_id == WorkTrack.id)
        .where(
            WorkTrackItem.id == item_id,
            func.lower(WorkTrackItem.proposed_executor_email) == user.email.lower(),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Задача на рассмотрение не найдена")
    track, item = row
    item.reservation_status = body.decision
    item.status = "waiting" if body.decision == "reserved" else "blocked"
    if body.comment:
        suffix = f"\n\nРешение исполнителя {user.email}: {body.comment}"
        item.notes = (item.notes or "") + suffix
    item.updated_at = datetime.now(timezone.utc)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(item)
    return WorkTrackAssignedItemRead(
        track_id=track.id,
        track_title=track.title,
        track_owner_id=track.owner_id,
        item=_serialize_item(item, None, None),
    )


@router.get("/{track_id}", response_model=WorkTrackRead)
async def get_work_track(
    track_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Read one task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    return await _serialize_track(db, track)


@router.get("/{track_id}/readiness", response_model=WorkTrackReadinessRead)
async def get_work_track_readiness(
    track_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Check whether a draft track can be activated."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    issues = _readiness_issues(track, await _track_items(db, track.id))
    return WorkTrackReadinessRead(can_activate=len(issues) == 0, issues=issues)


@router.post("/{track_id}/methodology/apply", response_model=WorkTrackRead)
async def apply_methodology_to_work_track(
    track_id: UUID,
    body: WorkTrackApplyMethodologyRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Attach a methodology route to a track and create cube items."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    methodology = await _get_methodology_or_404(db, body.methodology_id)
    if not methodology.is_active:
        raise HTTPException(status_code=400, detail="Можно применить только активную методологию")
    payload = methodology.payload
    cube_ids = _route_cube_ids(payload, body.route_key)
    cube_map = {
        str(cube.get("id")): cube
        for cube in payload.get("cubes", [])
        if isinstance(cube, dict) and cube.get("id")
    }
    missing = [cube_id for cube_id in cube_ids if cube_id not in cube_map]
    if missing:
        raise HTTPException(status_code=400, detail=f"В методологии не найдены кубики: {', '.join(missing[:5])}")

    if body.replace_existing_cubes:
        result = await db.execute(select(WorkTrackItem).where(WorkTrackItem.track_id == track.id, WorkTrackItem.item_type == "cube"))
        for item in result.scalars().all():
            await db.delete(item)
        await db.flush()

    existing_result = await db.execute(
        select(WorkTrackItem.methodology_node_id).where(
            WorkTrackItem.track_id == track.id,
            WorkTrackItem.item_type == "cube",
            WorkTrackItem.methodology_id == methodology.id,
        )
    )
    existing_cube_ids = {cube_id for cube_id in existing_result.scalars().all() if cube_id}
    position = await _next_position(db, track.id)
    for cube_id in cube_ids:
        if cube_id in existing_cube_ids:
            continue
        cube = cube_map[cube_id]
        item = WorkTrackItem(
            track_id=track.id,
            item_type="cube",
            methodology_id=methodology.id,
            methodology_node_type="cube",
            methodology_node_id=cube_id,
            methodology_stage_id=str(cube.get("stage_id")) if cube.get("stage_id") is not None else None,
            methodology_snapshot=cube,
            checklist_snapshot=_cube_checklist(payload, cube_id),
            proposed_executor_name=str(cube.get("responsible"))[:200] if cube.get("responsible") else None,
            reservation_status="draft",
            title=_cube_title(cube),
            description=", ".join(cube.get("outputs", [])) if isinstance(cube.get("outputs"), list) else None,
            status="active",
            position=position,
        )
        db.add(item)
        position += 10

    track.methodology_id = methodology.id
    track.methodology_snapshot = _compact_methodology_snapshot(methodology)
    track.product_key = body.product_key
    track.route_key = body.route_key
    track.route_snapshot = _route_snapshot(payload, body.route_key)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.post("/{track_id}/methodology/send-review", response_model=WorkTrackRead)
async def send_track_items_for_review(
    track_id: UUID,
    body: WorkTrackSendReviewRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Mark proposed future track items as sent for executor consideration."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    query = select(WorkTrackItem).where(WorkTrackItem.track_id == track.id)
    if body.item_ids:
        query = query.where(WorkTrackItem.id.in_(body.item_ids))
    result = await db.execute(query)
    items = list(result.scalars().all())
    if body.item_ids and len(items) != len(set(body.item_ids)):
        raise HTTPException(status_code=400, detail="Часть элементов не найдена в треке")
    sent_count = 0
    blocked: list[str] = []
    for item in items:
        if item.status in {"done", "skipped"}:
            continue
        if not item.proposed_executor_email:
            blocked.append(f"{item.title or item.methodology_node_id or item.id}: нет email исполнителя")
            continue
        if not item.due_at:
            blocked.append(f"{item.title or item.methodology_node_id or item.id}: нет срока")
            continue
        item.reservation_status = "sent"
        item.status = "waiting"
        item.updated_at = datetime.now(timezone.utc)
        sent_count += 1
    if sent_count == 0:
        detail = "Нет элементов, которые можно отправить исполнителям"
        if blocked:
            detail = f"{detail}: {'; '.join(blocked[:5])}"
        raise HTTPException(status_code=400, detail=detail)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.patch("/{track_id}", response_model=WorkTrackRead)
async def update_work_track(
    track_id: UUID,
    body: WorkTrackUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Update a task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    payload = body.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] not in TRACK_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус трека")
    if "title" in payload:
        track.title = payload["title"]
    if "description" in payload:
        track.description = payload["description"]
    if "status" in payload:
        track.status = payload["status"]
    if "start_at" in payload:
        track.start_at = payload["start_at"]
    if "due_at" in payload:
        track.due_at = payload["due_at"]
    if track.start_at is not None and track.due_at is not None and track.due_at <= track.start_at:
        raise HTTPException(status_code=400, detail="Дата окончания трека должна быть позже даты старта")
    if "color" in payload:
        track.color = payload["color"] or "slate"
    if "methodology_id" in payload:
        methodology = await _get_methodology_or_404(db, payload["methodology_id"]) if payload["methodology_id"] else None
        if methodology and not methodology.is_active:
            raise HTTPException(status_code=400, detail="Можно использовать только активную методологию")
        track.methodology_id = methodology.id if methodology else None
        track.methodology_snapshot = _compact_methodology_snapshot(methodology) if methodology else None
        if methodology and track.route_key:
            track.route_snapshot = _route_snapshot(methodology.payload, track.route_key)
        if not methodology:
            track.route_snapshot = None
    if "product_key" in payload:
        track.product_key = payload["product_key"]
    if "route_key" in payload:
        track.route_key = payload["route_key"]
        if track.methodology_id:
            methodology = await _get_methodology_or_404(db, track.methodology_id)
            track.route_snapshot = _route_snapshot(methodology.payload, track.route_key)
        else:
            track.route_snapshot = None
    if track.status == "active":
        issues = _readiness_issues(track, await _track_items(db, track.id))
        if issues:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Трек нельзя активировать: есть незаполненные обязательные детали",
                    "issues": [issue.model_dump(mode="json") for issue in issues],
                },
            )
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_track(
    track_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task track and its ordered items."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    await db.delete(track)
    await db.flush()
    return None


@router.post("/{track_id}/items", response_model=WorkTrackRead, status_code=status.HTTP_201_CREATED)
async def create_work_track_item(
    track_id: UUID,
    body: WorkTrackItemCreate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Add an item to a task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    await _ensure_global_task_access(db, body.task_id, user)
    await _ensure_personal_task_owner(db, body.personal_task_id, user.id)
    if body.methodology_id:
        await _get_methodology_or_404(db, body.methodology_id)
    await _ensure_item_not_duplicated(db, track.id, body)
    item = WorkTrackItem(
        track_id=track.id,
        item_type=body.item_type,
        task_id=body.task_id,
        personal_task_id=body.personal_task_id,
        methodology_id=body.methodology_id,
        methodology_node_type=body.methodology_node_type,
        methodology_node_id=body.methodology_node_id,
        methodology_stage_id=body.methodology_stage_id,
        methodology_snapshot=body.methodology_snapshot,
        checklist_snapshot=body.checklist_snapshot,
        proposed_executor_email=body.proposed_executor_email,
        proposed_executor_name=body.proposed_executor_name,
        reservation_status=body.reservation_status,
        title=body.title,
        description=body.description,
        status=body.status,
        position=body.position if body.position is not None else await _next_position(db, track.id),
        starts_at=body.starts_at,
        due_at=body.due_at,
        notes=body.notes,
    )
    db.add(item)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.patch("/{track_id}/items/{item_id}", response_model=WorkTrackRead)
async def update_work_track_item(
    track_id: UUID,
    item_id: UUID,
    body: WorkTrackItemUpdate,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Update an item inside a task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    item = await _get_track_item_or_404(db, track.id, item_id)
    payload = body.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] not in ITEM_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус элемента")
    if "reservation_status" in payload and payload["reservation_status"] not in RESERVATION_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус бронирования")
    for field in (
        "title",
        "description",
        "status",
        "position",
        "starts_at",
        "due_at",
        "notes",
        "checklist_snapshot",
        "proposed_executor_email",
        "proposed_executor_name",
        "reservation_status",
    ):
        if field in payload:
            setattr(item, field, payload[field])
    if item.starts_at is not None and item.due_at is not None and item.due_at <= item.starts_at:
        raise HTTPException(status_code=400, detail="Срок элемента должен быть позже даты старта")
    item.updated_at = datetime.now(timezone.utc)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.post("/{track_id}/items/reorder", response_model=WorkTrackRead)
async def reorder_work_track_items(
    track_id: UUID,
    body: WorkTrackReorderRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Persist item order for a task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    result = await db.execute(select(WorkTrackItem).where(WorkTrackItem.track_id == track.id))
    items = list(result.scalars().all())
    item_map = {item.id: item for item in items}
    if set(body.item_ids) != set(item_map):
        raise HTTPException(status_code=400, detail="Список элементов трека не совпадает")
    for index, item_id in enumerate(body.item_ids):
        item_map[item_id].position = (index + 1) * 10
        item_map[item_id].updated_at = datetime.now(timezone.utc)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)


@router.delete("/{track_id}/items/{item_id}", response_model=WorkTrackRead)
async def delete_work_track_item(
    track_id: UUID,
    item_id: UUID,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Remove an item from a task track."""
    track = await _get_owned_track_or_404(db, track_id, user.id)
    item = await _get_track_item_or_404(db, track.id, item_id)
    await db.delete(item)
    track.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(track)
    return await _serialize_track(db, track)
