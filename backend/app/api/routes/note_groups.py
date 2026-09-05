"""Owner-only note organization; context never grants note access."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.note_group import NoteContextLink, NoteGroup, NoteShareBatch
from app.models.quick_note import QuickNote
from app.models.user import User
from app.models.work_entity import WorkEntityLink
from app.schemas.note_group import (
    NoteBulkMove, NoteGroupCreate, NoteGroupOrder, NoteGroupRead, NoteGroupUpdate,
    NoteLinkCreate, NoteSharePreviewCreate, NoteSharePreviewRead,
)
from app.services import note_groups as service
from app.services.attention_realtime import attention_hub
from app.services.quick_note_realtime import hub_registry

router = APIRouter()
SourceType = Literal["group", "note"]
TargetType = Literal["entity", "personal_task"]


def check_revision(group, revision):
    if group.revision != revision:
        raise HTTPException(409, "Группа изменилась. Обновите список и повторите действие")


async def group_read(db, group):
    count = (await db.execute(select(func.count()).select_from(QuickNote).where(
        QuickNote.group_id == group.id, QuickNote.owner_id == group.owner_id,
    ))).scalar_one()
    return NoteGroupRead.model_validate(group).model_copy(update={"note_count": count})


@router.get("", response_model=list[NoteGroupRead])
async def list_groups(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    groups = (await db.execute(select(NoteGroup).where(NoteGroup.owner_id == user.id).order_by(NoteGroup.position, NoteGroup.id))).scalars().all()
    counts = dict((await db.execute(select(QuickNote.group_id, func.count()).where(QuickNote.owner_id == user.id).group_by(QuickNote.group_id))).all())
    return [NoteGroupRead.model_validate(group).model_copy(update={"note_count": counts.get(group.id, 0)}) for group in groups]


@router.post("", response_model=NoteGroupRead)
async def create_group(body: NoteGroupCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    count = (await db.execute(select(func.count()).select_from(NoteGroup).where(NoteGroup.owner_id == user.id))).scalar_one()
    if count >= 500:
        raise HTTPException(409, "Достигнут предел: 500 групп")
    position = (await db.execute(select(func.max(NoteGroup.position)).where(NoteGroup.owner_id == user.id))).scalar_one()
    group = NoteGroup(owner_id=user.id, title=body.title, position=0 if position is None else position + 1)
    db.add(group)
    await db.flush()
    return await group_read(db, group)


@router.post("/order", response_model=list[NoteGroupRead])
async def reorder_groups(body: NoteGroupOrder, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    groups = (await db.execute(select(NoteGroup).where(NoteGroup.owner_id == user.id))).scalars().all()
    group_map = {group.id: group for group in groups}
    if set(group_map) != {item.id for item in body.groups}:
        raise HTTPException(409, "Состав групп изменился. Обновите список")
    for item in body.groups:
        check_revision(group_map[item.id], item.base_revision)
    for position, item in enumerate(body.groups):
        group_map[item.id].position = position
        group_map[item.id].revision += 1
    await db.flush()
    return await list_groups(user, db)


@router.post("/move")
async def move_notes(body: NoteBulkMove, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    if body.group_id:
        await service.owned_group(db, body.group_id, user.id, active=True)
    notes = await service.owned_notes(db, body.note_ids, user.id, lock=True)
    for note in notes:
        note.group_id = body.group_id
    await db.flush()
    return {"moved": len(notes), "group_id": body.group_id}


@router.get("/targets")
async def targets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.target_options(db, user.id)


@router.get("/backlinks")
async def backlinks(target_type: TargetType, target_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.backlinks(db, target_type, target_id, user.id)


@router.get("/share/recipients")
async def share_recipients(project_id: UUID | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.share_recipients(db, user.id, project_id)


@router.post("/share/preview", response_model=NoteSharePreviewRead)
async def preview_share(body: NoteSharePreviewCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.preview_share(db, body, user.id)


@router.post("/share/{batch_id}/apply")
async def apply_share(batch_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result, changed = await service.apply_share(db, batch_id, user)
    await db.commit()
    recipients = set()
    for note_id, ids in changed:
        recipients.update(ids)
        hub = await hub_registry.try_get(note_id)
        if hub is not None:
            await hub.broadcast({"type": "access.changed", "note_id": str(note_id), "actor_id": str(user.id), "recipients": [str(id) for id in ids]})
    if recipients:
        await attention_hub.send_to_users(list(recipients), {"type": "attention.changed"})
    return result


@router.get("/share/audit")
async def share_audit(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batches = (await db.execute(select(NoteShareBatch).where(NoteShareBatch.owner_id == user.id, NoteShareBatch.applied_at.is_not(None)).order_by(NoteShareBatch.applied_at.desc()).limit(100))).scalars().all()
    return [{"preview": service.preview_read(batch), "result": batch.result} for batch in batches]


@router.get("/sources/{source_type}/{source_id}/links")
async def list_links(source_type: SourceType, source_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.context_links(db, source_type, source_id, user.id)


@router.post("/sources/{source_type}/{source_id}/links")
async def add_link(source_type: SourceType, source_id: UUID, body: NoteLinkCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    await service.owned_source(db, source_type, source_id, user.id, active=True)
    await service.target(db, body.target_type, body.target_id, user.id)
    if source_type == "note" and body.target_type == "entity":
        legacy = (await db.execute(select(WorkEntityLink.id).where(WorkEntityLink.quick_note_id == source_id, WorkEntityLink.entity_id == body.target_id))).scalar_one_or_none()
        if legacy:
            return await service.context_links(db, source_type, source_id, user.id)
    column = NoteContextLink.entity_id if body.target_type == "entity" else NoteContextLink.personal_task_id
    existing = (await db.execute(select(NoteContextLink.id).where(service.source_condition(source_type, source_id), column == body.target_id))).scalar_one_or_none()
    if existing is None:
        db.add(NoteContextLink(**{"group_id" if source_type == "group" else "note_id": source_id,
                                "entity_id" if body.target_type == "entity" else "personal_task_id": body.target_id}))
        await db.flush()
    return await service.context_links(db, source_type, source_id, user.id)


@router.delete("/sources/{source_type}/{source_id}/links/{link_id}")
async def remove_link(source_type: SourceType, source_id: UUID, link_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    await service.owned_source(db, source_type, source_id, user.id, active=True)
    link = (await db.execute(select(NoteContextLink).where(NoteContextLink.id == link_id, service.source_condition(source_type, source_id)))).scalar_one_or_none()
    if link is None:
        raise HTTPException(404, "Связь не найдена")
    await db.delete(link)
    await db.flush()
    return {"deleted": True}


@router.patch("/{group_id}", response_model=NoteGroupRead)
async def update_group(group_id: UUID, body: NoteGroupUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    group = await service.owned_group(db, group_id, user.id)
    check_revision(group, body.base_revision)
    for field, value in body.model_dump(exclude_unset=True, exclude={"base_revision"}).items():
        setattr(group, field, value)
    group.revision += 1
    await db.flush()
    return await group_read(db, group)


@router.delete("/{group_id}")
async def delete_group(group_id: UUID, base_revision: int = Query(ge=1), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_owner(db, user.id)
    group = await service.owned_group(db, group_id, user.id)
    check_revision(group, base_revision)
    if not group.archived:
        raise HTTPException(409, "Перед удалением архивируйте группу")
    await db.execute(update(QuickNote).where(QuickNote.group_id == group.id).values(group_id=None))
    await db.delete(group)
    await db.flush()
    return {"deleted": True, "notes_preserved": True}
