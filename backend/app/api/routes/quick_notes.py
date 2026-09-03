"""API for personal quick notes."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.database import AsyncSessionLocal
from app.api.routes.contacts import has_accepted_contact
from app.core.security import decode_access_token
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.user import User
from app.schemas.quick_note import (
    QuickNoteAttachmentRead,
    QuickNoteCreate,
    QuickNoteCommentCreate,
    QuickNoteCommentRead,
    QuickNoteRead,
    QuickNoteShareCreate,
    QuickNoteShareRead,
    QuickNoteUpdate,
    SharedQuickNoteRead,
)
from app.services.attachments import attachment_path, save_quick_note_attachment
from app.services.storage_quota import (
    finalize_storage_file_deletion,
    schedule_storage_file_deletion,
)
from app.services.attention_realtime import attention_hub
from app.services.messages import emit_attention_event, resolve_attention_for_source
from app.services.quick_note_realtime import QuickNoteConnection, hub_registry
from app.services.quick_note_shares import (
    activate_quick_note_shares,
    revoke_quick_note_share,
)

router = APIRouter()


def _title_from_body(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return first_line[:80] if first_line else "Без названия"


async def _get_owned_note_or_404(
    db: AsyncSession, note_id: UUID, owner_id: UUID, *, for_update: bool = False
) -> QuickNote:
    stmt = select(QuickNote).where(QuickNote.id == note_id, QuickNote.owner_id == owner_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    return note

async def _get_accessible_note_or_404(db: AsyncSession, note_id: UUID, user_id: UUID) -> QuickNote:
    owned = await db.execute(select(QuickNote).where(QuickNote.id == note_id, QuickNote.owner_id == user_id))
    note = owned.scalar_one_or_none()
    if note:
        return note
    shared = await db.execute(
        select(QuickNote)
        .join(QuickNoteShare, QuickNoteShare.note_id == QuickNote.id)
        .where(
            QuickNote.id == note_id,
            QuickNoteShare.recipient_id == user_id,
            QuickNoteShare.status == "active",
        )
    )
    note = shared.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    return note


async def _user_has_note_access(db: AsyncSession, note_id: UUID, user_id: UUID) -> bool:
    owned = await db.execute(
        select(QuickNote.id).where(QuickNote.id == note_id, QuickNote.owner_id == user_id)
    )
    if owned.scalar_one_or_none():
        return True
    shared = await db.execute(
        select(QuickNoteShare.id)
        .join(QuickNote, QuickNote.id == QuickNoteShare.note_id)
        .where(
            QuickNoteShare.note_id == note_id,
            QuickNoteShare.recipient_id == user_id,
            QuickNoteShare.status == "active",
        )
    )
    return shared.scalar_one_or_none() is not None


def _share_read(share: QuickNoteShare, owner: User, recipient: User) -> QuickNoteShareRead:
    return QuickNoteShareRead(
        id=share.id,
        note_id=share.note_id,
        owner_id=share.owner_id,
        owner_name=owner.full_name,
        owner_email=owner.email,
        recipient_id=share.recipient_id,
        recipient_name=recipient.full_name,
        recipient_email=recipient.email,
        status=share.status,
        created_at=share.created_at,
        updated_at=share.updated_at,
    )


async def _broadcast(note_id: UUID, message: dict, *, exclude: UUID | None = None) -> None:
    hub = await hub_registry.try_get(note_id)
    if hub is not None:
        payload = {"note_id": str(note_id), **message}
        await hub.broadcast(payload, exclude=exclude)


@router.get("", response_model=list[QuickNoteRead])
async def list_quick_notes(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's quick notes."""
    stmt = select(QuickNote).where(QuickNote.owner_id == current_user.id)
    if status and status != "all":
        if status not in {"draft", "processed", "archived"}:
            raise HTTPException(status_code=400, detail="Некорректный статус заметки")
        stmt = stmt.where(QuickNote.status == status)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                QuickNote.title.ilike(pattern),
                QuickNote.body.ilike(pattern),
                QuickNote.context.ilike(pattern),
            )
        )
    stmt = stmt.order_by(QuickNote.updated_at.desc(), QuickNote.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/shared", response_model=list[SharedQuickNoteRead])
async def list_shared_notes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List notes shared with current user."""
    owner = aliased(User)
    stmt = (
        select(QuickNoteShare, QuickNote, owner)
        .join(QuickNote, QuickNote.id == QuickNoteShare.note_id)
        .join(owner, owner.id == QuickNoteShare.owner_id)
        .where(QuickNoteShare.recipient_id == current_user.id, QuickNoteShare.status == "active")
        .order_by(QuickNoteShare.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        SharedQuickNoteRead(
            share=_share_read(share, note_owner, current_user),
            note=QuickNoteRead.model_validate(note),
        )
        for share, note, note_owner in rows
    ]


@router.get("/{note_id}", response_model=SharedQuickNoteRead | QuickNoteRead)
async def get_quick_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read one owned or shared quick note."""
    owned = (
        await db.execute(
            select(QuickNote).where(QuickNote.id == note_id, QuickNote.owner_id == current_user.id)
        )
    ).scalar_one_or_none()
    if owned:
        return QuickNoteRead.model_validate(owned)

    owner = aliased(User)
    row = (
        await db.execute(
            select(QuickNoteShare, QuickNote, owner)
            .join(QuickNote, QuickNote.id == QuickNoteShare.note_id)
            .join(owner, owner.id == QuickNoteShare.owner_id)
            .where(
                QuickNote.id == note_id,
                QuickNoteShare.recipient_id == current_user.id,
                QuickNoteShare.status == "active",
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Заметка не найдена")
    share, note, note_owner = row
    return SharedQuickNoteRead(
        share=_share_read(share, note_owner, current_user),
        note=QuickNoteRead.model_validate(note),
    )


@router.post("", response_model=QuickNoteRead)
async def create_quick_note(
    body: QuickNoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create quick note for current user."""
    note = QuickNote(
        owner_id=current_user.id,
        title=body.title or _title_from_body(body.body),
        body=body.body,
        context=body.context,
        status="draft",
        tags=body.tags,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


@router.get("/{note_id}/shares", response_model=list[QuickNoteShareRead])
async def list_note_shares(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active shares for an owned note."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id)
    recipient = aliased(User)
    stmt = (
        select(QuickNoteShare, recipient)
        .join(recipient, recipient.id == QuickNoteShare.recipient_id)
        .where(QuickNoteShare.note_id == note.id, QuickNoteShare.status == "active")
        .order_by(QuickNoteShare.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [_share_read(share, current_user, rec) for share, rec in rows]


@router.post("/{note_id}/shares", response_model=list[QuickNoteShareRead])
async def share_note(
    note_id: UUID,
    payload: QuickNoteShareCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Share an owned note with accepted contacts."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id)
    recipient_ids = list(dict.fromkeys(payload.recipient_ids))
    recipients = (
        await db.execute(select(User).where(User.id.in_(recipient_ids), User.is_active.is_(True)))
    ).scalars().all()
    found_ids = {user.id for user in recipients}
    if len(found_ids) != len(recipient_ids):
        raise HTTPException(status_code=404, detail="Один или несколько получателей не найдены")

    for recipient_id in recipient_ids:
        if recipient_id == current_user.id:
            raise HTTPException(status_code=400, detail="Нельзя поделиться заметкой с самим собой")
        if not await has_accepted_contact(db, current_user.id, recipient_id):
            raise HTTPException(status_code=403, detail="Поделиться можно только с принятым контактом")

    now = datetime.now(timezone.utc)
    newly_activated = await activate_quick_note_shares(
        db,
        note_id=note.id,
        owner_id=current_user.id,
        recipient_ids=recipient_ids,
    )
    if newly_activated:
        await emit_attention_event(
            db,
            target_user_ids=newly_activated,
            kind="direct",
            event_type="quick_note.share.received",
            source_type="quick_note",
            source_key=str(note.id),
            title=f"Открыт доступ к заметке «{note.title}»",
            body=f"{current_user.full_name} поделился заметкой.",
            link=f"/quick-notes/{note.id}",
            actor_id=current_user.id,
            dedupe_key=f"quick-note-share:{note.id}",
            idempotency_key=f"quick-note-share:{note.id}:{now.isoformat()}",
        )
    await db.commit()
    await _broadcast(
        note.id,
        {
            "type": "access.changed",
            "actor_id": str(current_user.id),
            "recipients": [str(rid) for rid in newly_activated],
        },
    )
    if newly_activated:
        await attention_hub.send_to_users(
            newly_activated, {"type": "attention.changed"}
        )
    return await list_note_shares(note.id, current_user, db)


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a share for an owned note."""
    revoked = await revoke_quick_note_share(
        db,
        share_id=share_id,
        owner_id=current_user.id,
    )
    if revoked is None:
        raise HTTPException(status_code=404, detail="Доступ не найден")
    note_id, revoked_id = revoked
    await resolve_attention_for_source(
        db,
        user_id=revoked_id,
        source_type="quick_note",
        source_key=str(note_id),
    )
    await db.commit()
    hub = await hub_registry.try_get(note_id)
    if hub is not None:
        await hub.send_to_user(
            {
                "type": "access.revoked",
                "note_id": str(note_id),
                "actor_id": str(current_user.id),
                "recipient_id": str(revoked_id),
            },
            revoked_id,
        )
        await hub.disconnect_user(revoked_id)
    await attention_hub.send_to_user(revoked_id, {"type": "attention.changed"})
    return {"revoked": True, "share_id": str(share_id)}


@router.get("/{note_id}/comments", response_model=list[QuickNoteCommentRead])
async def list_note_comments(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List note discussion comments for owner or active recipients."""
    note = await _get_accessible_note_or_404(db, note_id, current_user.id)
    author = aliased(User)
    rows = (
        await db.execute(
            select(QuickNoteComment, author)
            .join(author, author.id == QuickNoteComment.author_id)
            .where(QuickNoteComment.note_id == note.id)
            .order_by(QuickNoteComment.created_at.asc())
        )
    ).all()
    return [
        QuickNoteCommentRead(
            id=comment.id,
            note_id=comment.note_id,
            author_id=comment.author_id,
            author_name=user.full_name,
            author_email=user.email,
            parent_id=comment.parent_id,
            body=comment.body,
            created_at=comment.created_at,
        )
        for comment, user in rows
    ]

@router.post("/{note_id}/comments", response_model=QuickNoteCommentRead)
async def create_note_comment(
    note_id: UUID,
    payload: QuickNoteCommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a note discussion comment for owner or active recipients."""
    note = await _get_accessible_note_or_404(db, note_id, current_user.id)
    if payload.parent_id is not None:
        parent = (
            await db.execute(
                select(QuickNoteComment).where(
                    QuickNoteComment.id == payload.parent_id,
                    QuickNoteComment.note_id == note.id,
                )
            )
        ).scalar_one_or_none()
        if not parent:
            raise HTTPException(status_code=400, detail="Комментарий для ответа не найден")
    comment = QuickNoteComment(
        note_id=note.id,
        author_id=current_user.id,
        parent_id=payload.parent_id,
        body=payload.body,
    )
    db.add(comment)
    await db.flush()
    recipient_ids = list(
        (
            await db.execute(
                select(QuickNoteShare.recipient_id).where(
                    QuickNoteShare.note_id == note.id,
                    QuickNoteShare.status == "active",
                )
            )
        ).scalars().all()
    )
    await emit_attention_event(
        db,
        target_user_ids=[note.owner_id, *recipient_ids],
        kind="direct",
        event_type="quick_note.comment.received",
        source_type="quick_note",
        source_key=str(note.id),
        title=f"Новое сообщение в заметке «{note.title}»",
        body=f"{current_user.full_name}: {' '.join(payload.body.split())[:240]}",
        link=f"/quick-notes/{note.id}",
        actor_id=current_user.id,
        dedupe_key=f"quick-note-discussion:{note.id}",
        idempotency_key=f"quick-note-comment:{comment.id}",
    )
    await db.commit()
    await db.refresh(comment)
    await _broadcast(
        note.id,
        {
            "type": "comment.created",
            "comment_id": str(comment.id),
            "actor_id": str(current_user.id),
        },
    )
    attention_targets = [
        user_id
        for user_id in dict.fromkeys([note.owner_id, *recipient_ids])
        if user_id != current_user.id
    ]
    await attention_hub.send_to_users(
        attention_targets, {"type": "attention.changed"}
    )
    return QuickNoteCommentRead(
        id=comment.id,
        note_id=comment.note_id,
        author_id=comment.author_id,
        author_name=current_user.full_name,
        author_email=current_user.email,
        parent_id=comment.parent_id,
        body=comment.body,
        created_at=comment.created_at,
    )

@router.get("/{note_id}/attachments", response_model=list[QuickNoteAttachmentRead])
async def list_note_attachments(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List note attachments for owner or active recipients."""
    note = await _get_accessible_note_or_404(db, note_id, current_user.id)
    result = await db.execute(
        select(QuickNoteAttachment)
        .where(QuickNoteAttachment.note_id == note.id)
        .order_by(QuickNoteAttachment.created_at.asc())
    )
    return list(result.scalars().all())

@router.post("/{note_id}/attachments", response_model=QuickNoteAttachmentRead)
async def upload_note_attachment(
    note_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach a file to an owned note."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id)
    attachment = await save_quick_note_attachment(db, note=note, uploader=current_user, upload=file)
    await db.commit()
    await db.refresh(attachment)
    await _broadcast(
        note.id,
        {
            "type": "attachment.created",
            "attachment_id": str(attachment.id),
            "actor_id": str(current_user.id),
        },
    )
    return attachment

@router.get("/{note_id}/attachments/{attachment_id}/content")
async def get_note_attachment_content(
    note_id: UUID,
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return note attachment content for owner or active recipients."""
    note = await _get_accessible_note_or_404(db, note_id, current_user.id)
    attachment = (
        await db.execute(
            select(QuickNoteAttachment).where(
                QuickNoteAttachment.id == attachment_id,
                QuickNoteAttachment.note_id == note.id,
            )
        )
    ).scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    file_path = attachment_path(attachment)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")
    return FileResponse(
        str(file_path),
        media_type=attachment.content_type,
        filename=attachment.original_filename,
    )


@router.delete("/{note_id}/attachments/{attachment_id}")
async def delete_note_attachment(
    note_id: UUID,
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove one file from an owned note and release its quota."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id, for_update=True)
    attachment = (
        await db.execute(
            select(QuickNoteAttachment)
            .where(
                QuickNoteAttachment.id == attachment_id,
                QuickNoteAttachment.note_id == note.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Файл заметки не найден")
    storage_file_id = await schedule_storage_file_deletion(
        db,
        owner_id=note.owner_id,
        stored_filename=attachment.stored_filename,
    )
    await db.delete(attachment)
    await db.commit()
    await finalize_storage_file_deletion(storage_file_id)
    await _broadcast(
        note.id,
        {
            "type": "attachment.deleted",
            "attachment_id": str(attachment_id),
            "actor_id": str(current_user.id),
        },
    )
    return {"deleted": True, "attachment_id": str(attachment_id)}

@router.patch("/{note_id}", response_model=QuickNoteRead)
async def update_quick_note(
    note_id: UUID,
    body: QuickNoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's quick note with optimistic revision guard."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id, for_update=True)
    if body.base_revision != note.revision:
        raise HTTPException(
            status_code=409,
            detail="Версия заметки устарела: обновите страницу и повторите изменение",
        )
    fields = body.model_fields_set
    if "body" in fields and body.body is not None:
        note.body = body.body
        if "title" not in fields and not note.title:
            note.title = _title_from_body(body.body)
    if "title" in fields:
        note.title = body.title or _title_from_body(note.body)
    if "context" in fields:
        note.context = body.context
    if "status" in fields and body.status is not None:
        note.status = body.status
    if "tags" in fields and body.tags is not None:
        note.tags = body.tags
    note.revision += 1
    note.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(note)
    revision = note.revision
    await _broadcast(
        note.id,
        {
            "type": "note.updated",
            "revision": revision,
            "actor_id": str(current_user.id),
        },
    )
    return note


@router.delete("/{note_id}")
async def delete_quick_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete current user's quick note."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id, for_update=True)
    attachments = list(
        (
            await db.execute(
                select(QuickNoteAttachment).where(QuickNoteAttachment.note_id == note.id)
            )
        ).scalars()
    )
    storage_file_ids = [
        await schedule_storage_file_deletion(
            db,
            owner_id=note.owner_id,
            stored_filename=attachment.stored_filename,
        )
        for attachment in attachments
    ]
    deleted_note_id = note.id
    await db.delete(note)
    await db.commit()
    for storage_file_id in storage_file_ids:
        await finalize_storage_file_deletion(storage_file_id)
    await _broadcast(
        deleted_note_id,
        {"type": "note.deleted", "actor_id": str(current_user.id)},
    )
    hub = await hub_registry.try_get(deleted_note_id)
    if hub is not None:
        await hub.disconnect_all()
        await hub_registry.remove_if_empty(deleted_note_id)
    return {"deleted": True, "note_id": str(note_id)}


async def _authenticate_ws_user(token: str, db: AsyncSession) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Невалидный или истёкший токен")
    token_auth_version = payload.get("ver", 0)
    if type(token_auth_version) is not int or token_auth_version < 0:
        raise HTTPException(status_code=401, detail="Невалидный токен")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Невалидный токен")
    try:
        user_id = UUID(sub) if isinstance(sub, str) else sub
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Невалидный токен")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь деактивирован")
    if user.auth_version != token_auth_version:
        raise HTTPException(status_code=401, detail="Сессия завершена. Войдите снова")
    if user.password_change_required:
        raise HTTPException(status_code=403, detail="Сначала смените временный пароль")
    return user


@router.websocket("/{note_id}/live")
async def quick_note_live(websocket: WebSocket, note_id: UUID) -> None:
    """Authenticated realtime channel for one quick note.

    The browser sends the first JSON message ``{"type":"auth","token":"..."}``
    with the JWT. The token is never accepted from the URL. After validating the
    user (active, auth_version, password setup) and confirming note access
    (owner or active share) the connection joins the in-memory hub and is
    notified of the current active users. Ping/pong keeps idle sockets alive.
    """
    await websocket.accept()
    try:
        auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        await websocket.close(code=1008)
        return
    try:
        auth_msg = json.loads(auth_raw)
    except json.JSONDecodeError:
        await websocket.close(code=1008)
        return
    if (
        not isinstance(auth_msg, dict)
        or auth_msg.get("type") != "auth"
        or not isinstance(auth_msg.get("token"), str)
    ):
        await websocket.close(code=1008)
        return
    token = auth_msg["token"]
    async with AsyncSessionLocal() as db:
        try:
            user = await _authenticate_ws_user(token, db)
            has_access = await _user_has_note_access(db, note_id, user.id)
        except HTTPException:
            await websocket.close(code=1008)
            return
    if not has_access:
        await websocket.close(code=1008)
        return

    hub = await hub_registry.get_or_create(note_id)
    connection = QuickNoteConnection(websocket=websocket, user_id=user.id)
    hub.add(user.id, connection)
    try:
        async with AsyncSessionLocal() as db:
            still_has_access = await _user_has_note_access(db, note_id, user.id)
    except Exception:
        hub.remove(user.id, connection)
        await websocket.close(code=1011)
        await hub_registry.remove_if_empty(note_id)
        return
    if not still_has_access:
        hub.remove(user.id, connection)
        await websocket.close(code=1008)
        await hub_registry.remove_if_empty(note_id)
        return
    try:
        await connection.websocket.send_text(
            json.dumps(
                {
                    "type": "ready",
                    "note_id": str(note_id),
                    "active_users": len(hub.active_users),
                },
                ensure_ascii=False,
            )
        )
        await _broadcast(
            note_id,
            {"type": "presence", "active_users": len(hub.active_users)},
            exclude=user.id,
        )
        while True:
            message = await connection.websocket.receive_text()
            try:
                parsed = json.loads(message)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("type") == "ping":
                await connection.websocket.send_text(
                    json.dumps(
                        {"type": "pong", "note_id": str(note_id)},
                        ensure_ascii=False,
                    )
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.remove(user.id, connection)
        await _broadcast(
            note_id,
            {"type": "presence", "active_users": len(hub.active_users)},
        )
        await hub_registry.remove_if_empty(note_id)
