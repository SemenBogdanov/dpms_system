"""Private note context, target validation and transactional share previews."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.note_group import NoteContextLink, NoteGroup, NoteShareBatch
from app.models.personal_task import PersonalTask
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.user import User
from app.models.work_entity import WorkEntity, WorkEntityLink, WorkEntityMember
from app.schemas.note_group import NoteSharePreviewCreate, NoteSharePreviewRead
from app.services.messages import emit_attention_event
from app.services.quick_note_shares import activate_quick_note_shares
from app.services.work_entities import get_entity_access, list_accessible_entities


async def lock_owner(db: AsyncSession, owner_id: UUID) -> None:
    # Serialize group membership changes with group-scoped share apply.
    await db.execute(select(User.id).where(User.id == owner_id).with_for_update())


async def owned_group(db, group_id, owner_id, *, active=False):
    group = (await db.execute(select(NoteGroup).where(
        NoteGroup.id == group_id, NoteGroup.owner_id == owner_id,
    ))).scalar_one_or_none()
    if group is None:
        raise HTTPException(404, "Группа не найдена")
    if active and group.archived:
        raise HTTPException(409, "Сначала восстановите группу из архива")
    return group


async def owned_notes(db, note_ids, owner_id, *, lock=False):
    stmt = select(QuickNote).where(QuickNote.id.in_(note_ids), QuickNote.owner_id == owner_id).order_by(QuickNote.id)
    if lock:
        stmt = stmt.with_for_update()
    notes = list((await db.execute(stmt)).scalars().all())
    if len(notes) != len(note_ids):
        raise HTTPException(404, "Одна или несколько заметок не найдены")
    return notes


async def owned_source(db, source_type, source_id, owner_id, *, active=False):
    if source_type == "group":
        return await owned_group(db, source_id, owner_id, active=active)
    return (await owned_notes(db, [source_id], owner_id))[0]


async def target(db, target_type, target_id, user_id):
    if target_type == "entity":
        access = await get_entity_access(db, target_id, user_id)
        if not access or access[0].entity_type not in {"project", "goal"}:
            raise HTTPException(404, "Проект или цель не найдены")
        return access[0]
    task = (await db.execute(select(PersonalTask).where(
        PersonalTask.id == target_id, PersonalTask.owner_id == user_id,
    ))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Личная задача не найдена")
    return task


async def target_options(db, user_id):
    entities = await list_accessible_entities(db, user_id)
    tasks = (await db.execute(select(PersonalTask).where(PersonalTask.owner_id == user_id).order_by(PersonalTask.updated_at.desc()))).scalars().all()
    return [
        {"target_type": "entity", "target_id": entity.id, "title": entity.title}
        for entity, _ in entities if entity.entity_type in {"project", "goal"}
    ] + [{"target_type": "personal_task", "target_id": task.id, "title": task.title} for task in tasks]


def source_condition(source_type, source_id):
    return (NoteContextLink.group_id if source_type == "group" else NoteContextLink.note_id) == source_id


async def context_links(db, source_type, source_id, user_id):
    source = await owned_source(db, source_type, source_id, user_id)
    condition = source_condition(source_type, source_id)
    if source_type == "note" and source.group_id:
        condition = or_(condition, NoteContextLink.group_id == source.group_id)
    links = (await db.execute(select(NoteContextLink).where(condition).order_by(NoteContextLink.id))).scalars().all()
    result = []
    for link in links:
        kind = "entity" if link.entity_id else "personal_task"
        target_id = link.entity_id or link.personal_task_id
        try:
            item = await target(db, kind, target_id, user_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        inherited = source_type == "note" and link.group_id is not None
        result.append({"id": str(link.id), "target_type": kind, "target_id": str(target_id), "title": item.title,
                       "inherited": inherited, "origin": "group" if inherited else "direct", "can_remove": not inherited})
    if source_type == "note":
        legacy = (await db.execute(select(WorkEntityLink).where(WorkEntityLink.quick_note_id == source_id))).scalars().all()
        for link in legacy:
            access = await get_entity_access(db, link.entity_id, user_id)
            if access:
                result.append({"id": str(link.id), "target_type": "entity", "target_id": str(link.entity_id),
                    "title": access[0].title, "inherited": False, "origin": "legacy",
                    "can_remove": access[1] in {"owner", "editor"}})
        # Source-note provenance remains distinct from removable context links.
        tasks = (await db.execute(select(PersonalTask).where(
            PersonalTask.source_quick_note_id == source_id, PersonalTask.owner_id == user_id,
        ))).scalars().all()
        result.extend({"id": f"source:{task.id}", "target_type": "personal_task", "target_id": str(task.id),
                       "title": task.title, "inherited": False, "origin": "source", "can_remove": False} for task in tasks)
    return result


async def backlinks(db, target_type, target_id, user_id):
    await target(db, target_type, target_id, user_id)
    column = NoteContextLink.entity_id if target_type == "entity" else NoteContextLink.personal_task_id
    context = select(NoteContextLink).where(column == target_id)
    linked_note_ids = context.with_only_columns(NoteContextLink.note_id)
    linked_group_ids = context.with_only_columns(NoteContextLink.group_id)
    condition = or_(QuickNote.id.in_(linked_note_ids), QuickNote.group_id.in_(linked_group_ids))
    if target_type == "entity":
        condition = or_(condition, QuickNote.id.in_(select(WorkEntityLink.quick_note_id).where(WorkEntityLink.entity_id == target_id)))
    else:
        condition = or_(condition, QuickNote.id.in_(select(PersonalTask.source_quick_note_id).where(PersonalTask.id == target_id, PersonalTask.owner_id == user_id)))
    shared = select(QuickNoteShare.note_id).where(QuickNoteShare.recipient_id == user_id, QuickNoteShare.status == "active")
    notes = (await db.execute(select(QuickNote).where(condition, or_(QuickNote.owner_id == user_id, QuickNote.id.in_(shared))).order_by(QuickNote.updated_at.desc()))).scalars().all()
    # Never expose group identity/counts to recipients or other project members.
    groups = (await db.execute(select(NoteGroup).where(NoteGroup.id.in_(linked_group_ids), NoteGroup.owner_id == user_id).order_by(NoteGroup.position, NoteGroup.id))).scalars().all()
    return {"notes": [{"id": note.id, "title": note.title} for note in notes],
            "groups": [{"id": group.id, "title": group.title, "archived": group.archived} for group in groups]}


async def share_recipients(db, user_id, project_id=None, *, lock=False):
    stmt = select(Contact).where(
        Contact.status == "accepted", or_(Contact.requester_id == user_id, Contact.recipient_id == user_id),
    ).order_by(Contact.id)
    contacts = (await db.execute(stmt.with_for_update() if lock else stmt)).scalars().all()
    ids = {contact.recipient_id if contact.requester_id == user_id else contact.requester_id for contact in contacts}
    if project_id:
        if lock:
            await db.execute(select(WorkEntity.id).where(WorkEntity.id == project_id).with_for_update())
        entity = await target(db, "entity", project_id, user_id)
        stmt = select(WorkEntityMember.user_id).where(WorkEntityMember.entity_id == project_id).order_by(WorkEntityMember.id)
        members = set((await db.execute(stmt.with_for_update() if lock else stmt)).scalars().all()) if entity.visibility == "shared" else set()
        ids &= members | {entity.owner_id}
    ids.discard(user_id)
    stmt = select(User).where(User.id.in_(ids), User.is_active.is_(True)).order_by(User.id)
    users = (await db.execute(stmt.with_for_update(read=True) if lock else stmt)).scalars().all()
    return [{"id": str(user.id), "name": user.full_name} for user in users]


async def share_snapshot(db, body, user_id, *, lock=False):
    if body.group_id:
        await owned_group(db, body.group_id, user_id, active=True)
        note_ids = list((await db.execute(select(QuickNote.id).where(
            QuickNote.owner_id == user_id, QuickNote.group_id == body.group_id,
        ).order_by(QuickNote.id).limit(101))).scalars().all())
    else:
        note_ids = body.note_ids
    if not note_ids or len(note_ids) > 100:
        raise HTTPException(422, "Выберите от 1 до 100 заметок")
    notes = await owned_notes(db, note_ids, user_id, lock=lock)
    allowed = {item["id"]: item for item in await share_recipients(db, user_id, body.project_id, lock=lock)}
    recipients = []
    for recipient_id in sorted(body.recipient_ids, key=str):
        if str(recipient_id) not in allowed:
            raise HTTPException(403, "Получатель недоступен: нужен принятый контакт и участие в выбранном проекте")
        recipients.append(allowed[str(recipient_id)])
    shares = (await db.execute(select(QuickNoteShare).where(
        QuickNoteShare.note_id.in_(note_ids), QuickNoteShare.recipient_id.in_(body.recipient_ids),
    ).order_by(QuickNoteShare.note_id, QuickNoteShare.recipient_id))).scalars().all()
    files = (await db.execute(select(QuickNoteAttachment).where(QuickNoteAttachment.note_id.in_(note_ids)).order_by(QuickNoteAttachment.id))).scalars().all()
    comments = (await db.execute(select(QuickNoteComment).where(QuickNoteComment.note_id.in_(note_ids)).order_by(QuickNoteComment.id))).scalars().all()
    note_reads = []
    for note in notes:
        note_files = [{"id": str(file.id), "name": file.original_filename, "size": file.size_bytes} for file in files if file.note_id == note.id]
        note_comments = [{"id": str(comment.id), "body": comment.body} for comment in comments if comment.note_id == note.id]
        digest = hashlib.sha256(json.dumps({"body": note.body, "context": note.context, "tags": note.tags,
                                           "comments": note_comments}, ensure_ascii=True, sort_keys=True).encode()).hexdigest()
        note_reads.append({"id": str(note.id), "title": note.title, "revision": note.revision, "status": note.status,
                           "excerpt": note.body[:240], "files": note_files, "comment_count": len(note_comments), "digest": digest})
    return {"selection": body.model_dump(mode="json"), "notes": note_reads, "recipients": recipients,
            "shares": [{"note_id": str(share.note_id), "recipient_id": str(share.recipient_id), "status": share.status,
                        "updated_at": share.updated_at.isoformat()} for share in shares]}


def preview_read(batch):
    snapshot = batch.snapshot
    existing = sum(share["status"] == "active" for share in snapshot["shares"])
    return NoteSharePreviewRead(id=batch.id, expires_at=batch.expires_at,
        notes=[{key: value for key, value in note.items() if key != "digest"} for note in snapshot["notes"]],
        recipients=snapshot["recipients"], existing_share_count=existing,
        new_share_count=len(snapshot["notes"]) * len(snapshot["recipients"]) - existing)


async def preview_share(db, body, owner_id):
    await lock_owner(db, owner_id)
    snapshot = await share_snapshot(db, body, owner_id, lock=True)
    batch = NoteShareBatch(owner_id=owner_id, snapshot=snapshot, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    db.add(batch)
    await db.flush()
    return preview_read(batch)


async def apply_share(db, batch_id, user):
    batch = (await db.execute(select(NoteShareBatch).where(NoteShareBatch.id == batch_id, NoteShareBatch.owner_id == user.id).with_for_update())).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "Предпросмотр не найден")
    if batch.applied_at is not None:
        return batch.result, []
    if batch.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(409, "Предпросмотр устарел. Проверьте доступ заново")
    await lock_owner(db, user.id)
    body = NoteSharePreviewCreate.model_validate(batch.snapshot["selection"])
    fresh = await share_snapshot(db, body, user.id, lock=True)
    if fresh != batch.snapshot:
        raise HTTPException(409, "Заметки, файлы, обсуждение или доступ изменились. Создайте новый предпросмотр")
    changed = []
    now = datetime.now(timezone.utc)
    for note in fresh["notes"]:
        note_id = UUID(note["id"])
        recipients = await activate_quick_note_shares(db, note_id=note_id, owner_id=user.id, recipient_ids=body.recipient_ids)
        if recipients:
            await emit_attention_event(db, target_user_ids=recipients, kind="direct", event_type="quick_note.share.received",
                source_type="quick_note", source_key=str(note_id), title=f"Открыт доступ к заметке «{note['title']}»",
                body=f"{user.full_name} поделился заметкой.", link=f"/quick-notes/{note_id}", actor_id=user.id,
                dedupe_key=f"quick-note-share:{note_id}", idempotency_key=f"note-share-batch:{batch.id}:{note_id}")
            changed.append((note_id, recipients))
    batch.applied_at = now
    batch.result = {"id": str(batch.id), "applied_at": now.isoformat(), "changed_share_count": sum(len(ids) for _, ids in changed),
                    "note_ids": [note["id"] for note in fresh["notes"]], "recipient_ids": [str(id) for id in body.recipient_ids]}
    await db.flush()
    return batch.result, changed
