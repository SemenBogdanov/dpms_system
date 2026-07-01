"""API for personal quick notes."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.quick_note import QuickNote
from app.models.user import User
from app.schemas.quick_note import QuickNoteCreate, QuickNoteRead, QuickNoteUpdate

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
