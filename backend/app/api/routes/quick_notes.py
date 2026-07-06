"""API for personal quick notes."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.routes.contacts import has_accepted_contact
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

router = APIRouter()


def _title_from_body(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return first_line[:80] if first_line else "Без названия"


async def _get_owned_note_or_404(db: AsyncSession, note_id: UUID, owner_id: UUID) -> QuickNote:
    result = await db.execute(
        select(QuickNote).where(QuickNote.id == note_id, QuickNote.owner_id == owner_id)
    )
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

    existing = (
        await db.execute(
            select(QuickNoteShare).where(
                QuickNoteShare.note_id == note.id,
                QuickNoteShare.recipient_id.in_(recipient_ids),
            )
        )
    ).scalars().all()
    existing_by_recipient = {share.recipient_id: share for share in existing}
    now = datetime.now(timezone.utc)
    for recipient_id in recipient_ids:
        share = existing_by_recipient.get(recipient_id)
        if share:
            share.status = "active"
            share.updated_at = now
        else:
            db.add(
                QuickNoteShare(
                    note_id=note.id,
                    owner_id=current_user.id,
                    recipient_id=recipient_id,
                    status="active",
                )
            )
    await db.commit()
    return await list_note_shares(note.id, current_user, db)


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a share for an owned note."""
    share = (
        await db.execute(
            select(QuickNoteShare).where(
                QuickNoteShare.id == share_id,
                QuickNoteShare.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not share:
        raise HTTPException(status_code=404, detail="Доступ не найден")
    share.status = "revoked"
    share.updated_at = datetime.now(timezone.utc)
    await db.commit()
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
    await db.commit()
    await db.refresh(comment)
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
    return await save_quick_note_attachment(db, note=note, uploader=current_user, upload=file)

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

@router.patch("/{note_id}", response_model=QuickNoteRead)
async def update_quick_note(
    note_id: UUID,
    body: QuickNoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's quick note."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id)
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
    note.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(note)
    return note


@router.delete("/{note_id}")
async def delete_quick_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete current user's quick note."""
    note = await _get_owned_note_or_404(db, note_id, current_user.id)
    await db.delete(note)
    await db.flush()
    return {"deleted": True, "note_id": str(note_id)}
