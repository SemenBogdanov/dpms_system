"""Concurrency-safe access changes for shared quick notes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quick_note_share import QuickNoteShare


async def activate_quick_note_shares(
    db: AsyncSession,
    *,
    note_id: UUID,
    owner_id: UUID,
    recipient_ids: list[UUID],
) -> list[UUID]:
    """Create or reactivate shares and return recipients whose access changed."""
    recipients = list(dict.fromkeys(recipient_ids))
    if not recipients:
        return []

    now = datetime.now(timezone.utc)
    inserted = set(
        (
            await db.execute(
                insert(QuickNoteShare)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "note_id": note_id,
                            "owner_id": owner_id,
                            "recipient_id": recipient_id,
                            "status": "active",
                            "created_at": now,
                            "updated_at": now,
                        }
                        for recipient_id in recipients
                    ]
                )
                .on_conflict_do_nothing(
                    constraint="uq_quick_note_shares_note_recipient"
                )
                .returning(QuickNoteShare.recipient_id)
            )
        ).scalars().all()
    )

    existing_recipients = [
        recipient_id for recipient_id in recipients if recipient_id not in inserted
    ]
    reactivated: set[UUID] = set()
    if existing_recipients:
        reactivated = set(
            (
                await db.execute(
                    update(QuickNoteShare)
                    .where(
                        QuickNoteShare.note_id == note_id,
                        QuickNoteShare.recipient_id.in_(existing_recipients),
                        QuickNoteShare.status != "active",
                    )
                    .values(owner_id=owner_id, status="active", updated_at=now)
                    .returning(QuickNoteShare.recipient_id)
                )
            ).scalars().all()
        )

    changed = inserted | reactivated
    return [recipient_id for recipient_id in recipients if recipient_id in changed]


async def revoke_quick_note_share(
    db: AsyncSession,
    *,
    share_id: UUID,
    owner_id: UUID,
) -> tuple[UUID, UUID] | None:
    """Atomically revoke a share and return ``(note_id, recipient_id)``."""
    row = (
        await db.execute(
            update(QuickNoteShare)
            .where(
                QuickNoteShare.id == share_id,
                QuickNoteShare.owner_id == owner_id,
            )
            .values(status="revoked", updated_at=datetime.now(timezone.utc))
            .returning(QuickNoteShare.note_id, QuickNoteShare.recipient_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return row.note_id, row.recipient_id
