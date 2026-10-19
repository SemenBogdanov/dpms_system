"""Transactional state transitions for verified email-login changes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_change_request import EmailChangeRequest
from app.models.user import User
from app.services.email_outbox import (
    enqueue_email_change_notifications,
    suppress_email_change_notifications,
)
from app.services.user_admin_audit import (
    EMAIL_CHANGE_CANCELLED_EVENT,
    EMAIL_CHANGE_CONFIRMED_EVENT,
    EMAIL_CHANGE_EXPIRED_EVENT,
    EMAIL_CHANGE_REQUESTED_EVENT,
    EMAIL_CHANGE_SUPERSEDED_EVENT,
    record_email_change_audit_event,
)


class EmailChangeServiceError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def ensure_email_change_delivery_available() -> None:
    if settings.EMAIL_DELIVERY_MODE.strip().lower() == "disabled":
        raise EmailChangeServiceError(
            503,
            "Email-подтверждение пока не настроено. Обратитесь к администратору.",
        )


async def expire_stale_email_change_requests(
    db: AsyncSession,
    *,
    user_id: UUID | None = None,
    new_email: str | None = None,
    now: datetime | None = None,
) -> int:
    current = now or utc_now()
    filters = [
        EmailChangeRequest.status == "pending",
        EmailChangeRequest.expires_at <= current,
    ]
    scope = []
    if user_id is not None:
        scope.append(EmailChangeRequest.user_id == user_id)
    if new_email is not None:
        scope.append(EmailChangeRequest.new_email == normalize_email(new_email))
    if scope:
        filters.append(or_(*scope))
    requests = list(
        (
            await db.execute(
                select(EmailChangeRequest)
                .where(*filters)
                .order_by(EmailChangeRequest.expires_at.asc())
                .with_for_update()
            )
        ).scalars()
    )
    for request in requests:
        target = await db.get(User, request.user_id)
        if target is None:
            continue
        request.status = "expired"
        request.updated_at = current
        await suppress_email_change_notifications(db, request_id=request.id, now=current)
        await record_email_change_audit_event(
            db,
            actor_id=request.requested_by_id or target.id,
            target=target,
            request=request,
            event_type=EMAIL_CHANGE_EXPIRED_EVENT,
        )
    if requests:
        await db.flush()
    return len(requests)


async def get_pending_email_change(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> EmailChangeRequest | None:
    return (
        await db.execute(
            select(EmailChangeRequest)
            .where(
                EmailChangeRequest.user_id == user_id,
                EmailChangeRequest.status == "pending",
            )
            .order_by(EmailChangeRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create_email_change_request(
    db: AsyncSession,
    *,
    target: User,
    actor: User,
    new_email: str,
    request_kind: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> EmailChangeRequest:
    ensure_email_change_delivery_available()
    current = now or utc_now()
    normalized = normalize_email(new_email)
    if normalized == normalize_email(target.email):
        raise EmailChangeServiceError(400, "Новый email должен отличаться от текущего")
    if request_kind not in {"self", "admin_assisted"}:
        raise EmailChangeServiceError(400, "Некорректный тип запроса")
    clean_reason = (reason or "").strip()[:500] or None
    if request_kind == "admin_assisted" and not clean_reason:
        raise EmailChangeServiceError(422, "Укажите причину смены email")

    existing_user = (
        await db.execute(
            select(User.id).where(func.lower(User.email) == normalized)
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise EmailChangeServiceError(400, "Этот адрес нельзя использовать")

    pending = await get_pending_email_change(db, user_id=target.id)
    if pending is not None:
        pending.status = "superseded"
        pending.updated_at = current
        await suppress_email_change_notifications(db, request_id=pending.id, now=current)
        await record_email_change_audit_event(
            db,
            actor_id=actor.id,
            target=target,
            request=pending,
            event_type=EMAIL_CHANGE_SUPERSEDED_EVENT,
        )
        await db.flush()

    reserved = (
        await db.execute(
            select(EmailChangeRequest.id).where(
                EmailChangeRequest.status == "pending",
                EmailChangeRequest.new_email == normalized,
            )
        )
    ).scalar_one_or_none()
    if reserved is not None:
        raise EmailChangeServiceError(400, "Этот адрес нельзя использовать")

    request = EmailChangeRequest(
        user_id=target.id,
        requested_by_id=actor.id,
        request_kind=request_kind,
        old_email=normalize_email(target.email),
        new_email=normalized,
        status="pending",
        auth_version_at_request=target.auth_version,
        reason=clean_reason,
        expires_at=current + timedelta(hours=max(settings.EMAIL_CHANGE_TTL_HOURS, 1)),
    )
    db.add(request)
    try:
        await db.flush()
        await enqueue_email_change_notifications(
            db,
            request=request,
            recipient=target,
            now=current,
        )
        await record_email_change_audit_event(
            db,
            actor_id=actor.id,
            target=target,
            request=request,
            event_type=EMAIL_CHANGE_REQUESTED_EVENT,
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise EmailChangeServiceError(400, "Этот адрес нельзя использовать") from error
    await db.refresh(request)
    return request


async def cancel_pending_email_change(
    db: AsyncSession,
    *,
    target: User,
    actor: User,
    now: datetime | None = None,
) -> EmailChangeRequest | None:
    current = now or utc_now()
    request = (
        await db.execute(
            select(EmailChangeRequest)
            .where(
                EmailChangeRequest.user_id == target.id,
                EmailChangeRequest.status == "pending",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        return None
    request.status = "cancelled"
    request.cancelled_at = current
    request.updated_at = current
    await suppress_email_change_notifications(db, request_id=request.id, now=current)
    await record_email_change_audit_event(
        db,
        actor_id=actor.id,
        target=target,
        request=request,
        event_type=EMAIL_CHANGE_CANCELLED_EVENT,
    )
    await db.commit()
    await db.refresh(request)
    return request


async def _lock_action_request(
    db: AsyncSession,
    *,
    request_id: UUID,
) -> tuple[EmailChangeRequest, User]:
    candidate = await db.get(EmailChangeRequest, request_id)
    if candidate is None:
        raise EmailChangeServiceError(400, "Ссылка недействительна или устарела")
    target = (
        await db.execute(
            select(User).where(User.id == candidate.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise EmailChangeServiceError(400, "Ссылка недействительна или устарела")
    request = (
        await db.execute(
            select(EmailChangeRequest)
            .where(EmailChangeRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return request, target


async def confirm_email_change(
    db: AsyncSession,
    *,
    request_id: UUID,
    now: datetime | None = None,
) -> EmailChangeRequest:
    current = now or utc_now()
    request, target = await _lock_action_request(db, request_id=request_id)
    if request.status != "pending":
        raise EmailChangeServiceError(409, "Запрос уже обработан")
    if request.expires_at <= current:
        request.status = "expired"
        request.updated_at = current
        await suppress_email_change_notifications(db, request_id=request.id, now=current)
        await record_email_change_audit_event(
            db,
            actor_id=target.id,
            target=target,
            request=request,
            event_type=EMAIL_CHANGE_EXPIRED_EVENT,
        )
        await db.commit()
        raise EmailChangeServiceError(410, "Срок действия ссылки истек")
    if (
        target.auth_version != request.auth_version_at_request
        or normalize_email(target.email) != request.old_email
    ):
        request.status = "superseded"
        request.updated_at = current
        await suppress_email_change_notifications(db, request_id=request.id, now=current)
        await record_email_change_audit_event(
            db,
            actor_id=target.id,
            target=target,
            request=request,
            event_type=EMAIL_CHANGE_SUPERSEDED_EVENT,
        )
        await db.commit()
        raise EmailChangeServiceError(409, "Учетная запись изменилась. Создайте новый запрос")
    existing_user = (
        await db.execute(
            select(User.id).where(
                func.lower(User.email) == request.new_email,
                User.id != target.id,
            )
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise EmailChangeServiceError(409, "Этот адрес больше нельзя использовать")

    target.email = request.new_email
    target.auth_version += 1
    request.status = "confirmed"
    request.confirmed_at = current
    request.updated_at = current
    await suppress_email_change_notifications(db, request_id=request.id, now=current)
    await record_email_change_audit_event(
        db,
        actor_id=target.id,
        target=target,
        request=request,
        event_type=EMAIL_CHANGE_CONFIRMED_EVENT,
        sessions_revoked=True,
    )
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise EmailChangeServiceError(409, "Этот адрес больше нельзя использовать") from error
    await db.refresh(request)
    return request


async def cancel_email_change_by_link(
    db: AsyncSession,
    *,
    request_id: UUID,
    now: datetime | None = None,
) -> EmailChangeRequest:
    current = now or utc_now()
    request, target = await _lock_action_request(db, request_id=request_id)
    if request.status != "pending":
        raise EmailChangeServiceError(409, "Запрос уже обработан")
    if request.expires_at <= current:
        request.status = "expired"
        request.updated_at = current
        await suppress_email_change_notifications(db, request_id=request.id, now=current)
        await record_email_change_audit_event(
            db,
            actor_id=target.id,
            target=target,
            request=request,
            event_type=EMAIL_CHANGE_EXPIRED_EVENT,
        )
        await db.commit()
        raise EmailChangeServiceError(410, "Срок действия ссылки истек")
    request.status = "cancelled"
    request.cancelled_at = current
    request.updated_at = current
    await suppress_email_change_notifications(db, request_id=request.id, now=current)
    await record_email_change_audit_event(
        db,
        actor_id=target.id,
        target=target,
        request=request,
        event_type=EMAIL_CHANGE_CANCELLED_EVENT,
    )
    await db.commit()
    await db.refresh(request)
    return request
