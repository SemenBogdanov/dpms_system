"""API for reusable user contacts."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, get_db
from app.models.contact import Contact
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead
from app.services.attention_realtime import attention_hub
from app.services.messages import emit_attention_event, resolve_attention_for_source

router = APIRouter()


def contact_read(contact: Contact, requester: User, recipient: User, current_user_id: UUID) -> ContactRead:
    """Serialize a contact with current user's direction."""
    return ContactRead(
        id=contact.id,
        requester_id=contact.requester_id,
        recipient_id=contact.recipient_id,
        requester_name=requester.full_name,
        requester_email=requester.email,
        recipient_name=recipient.full_name,
        recipient_email=recipient.email,
        status=contact.status,
        direction="outgoing" if contact.requester_id == current_user_id else "incoming",
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )


async def has_accepted_contact(db: AsyncSession, user_id: UUID, other_user_id: UUID) -> bool:
    """Check if two users have an accepted contact relation."""
    result = await db.execute(
        select(Contact.id).where(
            Contact.status == "accepted",
            or_(
                and_(Contact.requester_id == user_id, Contact.recipient_id == other_user_id),
                and_(Contact.requester_id == other_user_id, Contact.recipient_id == user_id),
            ),
        )
    )
    return result.scalar_one_or_none() is not None


@router.get("", response_model=list[ContactRead])
async def list_contacts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's contacts and requests."""
    requester = aliased(User)
    recipient = aliased(User)
    stmt = (
        select(Contact, requester, recipient)
        .join(requester, requester.id == Contact.requester_id)
        .join(recipient, recipient.id == Contact.recipient_id)
        .where(or_(Contact.requester_id == current_user.id, Contact.recipient_id == current_user.id))
        .order_by(Contact.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [contact_read(contact, req, rec, current_user.id) for contact, req, rec in rows]


@router.post("", response_model=ContactRead)
async def create_contact_request(
    payload: ContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a contact request by recipient email."""
    target = (
        await db.execute(select(User).where(func.lower(User.email) == payload.email))
    ).scalar_one_or_none()
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="Пользователь с такой почтой не найден")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя отправить заявку самому себе")
    current_user_id = current_user.id
    target_id = target.id

    existing = (
        await db.execute(
            select(Contact).where(
                or_(
                    and_(Contact.requester_id == current_user.id, Contact.recipient_id == target.id),
                    and_(Contact.requester_id == target.id, Contact.recipient_id == current_user.id),
                )
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.status == "rejected":
            existing.requester_id = current_user.id
            existing.recipient_id = target.id
            existing.status = "pending"
            existing.updated_at = datetime.now(timezone.utc)
            await emit_attention_event(
                db,
                target_user_ids=[target.id],
                kind="direct",
                event_type="contact.request.received",
                source_type="contact",
                source_key=str(existing.id),
                title="Новая заявка в контакты",
                body=f"{current_user.full_name} предлагает добавить контакт.",
                link="/contacts",
                actor_id=current_user.id,
                dedupe_key=f"contact-request:{existing.id}",
                idempotency_key=(
                    f"contact-request:{existing.id}:{existing.updated_at.isoformat()}"
                ),
            )
            await db.commit()
            await db.refresh(existing)
            await attention_hub.send_to_user(target.id, {"type": "attention.changed"})
            return contact_read(existing, current_user, target, current_user.id)
        requester = current_user if existing.requester_id == current_user.id else target
        recipient = target if existing.recipient_id == target.id else current_user
        return contact_read(existing, requester, recipient, current_user.id)

    contact = Contact(
        requester_id=current_user.id,
        recipient_id=target.id,
        status="pending",
    )
    db.add(contact)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(Contact).where(
                    or_(
                        and_(
                            Contact.requester_id == current_user_id,
                            Contact.recipient_id == target_id,
                        ),
                        and_(
                            Contact.requester_id == target_id,
                            Contact.recipient_id == current_user_id,
                        ),
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(
                status_code=409,
                detail="Заявка уже создается. Обновите список контактов",
            )
        users = list(
            (
                await db.execute(
                    select(User).where(User.id.in_([current_user_id, target_id]))
                )
            ).scalars().all()
        )
        users_by_id = {user.id: user for user in users}
        return contact_read(
            existing,
            users_by_id[existing.requester_id],
            users_by_id[existing.recipient_id],
            current_user_id,
        )
    await emit_attention_event(
        db,
        target_user_ids=[target.id],
        kind="direct",
        event_type="contact.request.received",
        source_type="contact",
        source_key=str(contact.id),
        title="Новая заявка в контакты",
        body=f"{current_user.full_name} предлагает добавить контакт.",
        link="/contacts",
        actor_id=current_user.id,
        dedupe_key=f"contact-request:{contact.id}",
        idempotency_key=f"contact-request:{contact.id}",
    )
    await db.commit()
    await db.refresh(contact)
    await attention_hub.send_to_user(target.id, {"type": "attention.changed"})
    return contact_read(contact, current_user, target, current_user.id)


@router.patch("/{contact_id}/accept", response_model=ContactRead)
async def accept_contact_request(
    contact_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept incoming contact request."""
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.recipient_id == current_user.id,
                Contact.status == "pending",
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    contact.status = "accepted"
    contact.updated_at = datetime.now(timezone.utc)
    await resolve_attention_for_source(
        db,
        user_id=current_user.id,
        source_type="contact",
        source_key=str(contact.id),
    )
    requester = (await db.execute(select(User).where(User.id == contact.requester_id))).scalar_one()
    await emit_attention_event(
        db,
        target_user_ids=[requester.id],
        kind="direct",
        event_type="contact.request.accepted",
        source_type="contact",
        source_key=str(contact.id),
        title="Заявка в контакты принята",
        body=f"{current_user.full_name} добавил вас в контакты.",
        link="/contacts",
        actor_id=current_user.id,
        dedupe_key=f"contact-response:{contact.id}",
        idempotency_key=f"contact-accepted:{contact.id}",
    )
    await db.commit()
    await attention_hub.send_to_users(
        [current_user.id, requester.id], {"type": "attention.changed"}
    )
    return contact_read(contact, requester, current_user, current_user.id)


@router.patch("/{contact_id}/reject", response_model=ContactRead)
async def reject_contact_request(
    contact_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject incoming contact request."""
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.recipient_id == current_user.id,
                Contact.status == "pending",
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    decision_at = datetime.now(timezone.utc)
    contact.status = "rejected"
    contact.updated_at = decision_at
    await resolve_attention_for_source(
        db,
        user_id=current_user.id,
        source_type="contact",
        source_key=str(contact.id),
    )
    requester = (await db.execute(select(User).where(User.id == contact.requester_id))).scalar_one()
    await emit_attention_event(
        db,
        target_user_ids=[requester.id],
        kind="direct",
        event_type="contact.request.rejected",
        source_type="contact",
        source_key=str(contact.id),
        title="Заявка в контакты отклонена",
        body=f"{current_user.full_name} отклонил заявку в контакты.",
        link="/contacts",
        actor_id=current_user.id,
        dedupe_key=f"contact-response:{contact.id}",
        idempotency_key=f"contact-rejected:{contact.id}:{decision_at.isoformat()}",
    )
    await db.commit()
    await attention_hub.send_to_users(
        [current_user.id, requester.id], {"type": "attention.changed"}
    )
    return contact_read(contact, requester, current_user, current_user.id)
