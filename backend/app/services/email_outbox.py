"""Transactional enqueue and lease-based delivery state for email notifications."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_outbox import EmailOutbox
from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_email(value: str) -> str:
    return value.strip().lower()


async def enqueue_email_notification(
    db: AsyncSession,
    *,
    idempotency_key: str,
    event_type: str,
    template_key: str,
    source_type: str,
    source_id: uuid.UUID | None,
    recipient_user_id: uuid.UUID | None,
    recipient_email: str,
    sender_name: str | None,
    deep_link_path: str,
    message_post_id: uuid.UUID | None = None,
    available_at: datetime | None = None,
    max_attempts: int | None = None,
) -> uuid.UUID:
    """Insert one durable intent without committing or contacting a provider."""
    outbox_id = uuid.uuid4()
    statement = (
        insert(EmailOutbox)
        .values(
            id=outbox_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            template_key=template_key,
            source_type=source_type,
            source_id=source_id,
            message_post_id=message_post_id,
            recipient_user_id=recipient_user_id,
            recipient_email=_normalized_email(recipient_email),
            sender_name=(sender_name or "").strip()[:255] or None,
            deep_link_path=deep_link_path,
            status="pending",
            attempt_count=0,
            max_attempts=max_attempts or settings.EMAIL_WORKER_MAX_ATTEMPTS,
            available_at=available_at or utc_now(),
        )
        .on_conflict_do_nothing(index_elements=[EmailOutbox.idempotency_key])
        .returning(EmailOutbox.id)
    )
    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    if inserted_id is not None:
        return inserted_id
    existing_id = (
        await db.execute(
            select(EmailOutbox.id).where(
                EmailOutbox.idempotency_key == idempotency_key
            )
        )
    ).scalar_one()
    return existing_id


async def enqueue_message_notification(
    db: AsyncSession,
    *,
    post_id: uuid.UUID,
    thread_id: uuid.UUID,
    recipient: User,
    sender_name: str,
    now: datetime | None = None,
) -> uuid.UUID:
    """Queue a body-free email notification for one message recipient."""
    current = now or utc_now()
    return await enqueue_email_notification(
        db,
        idempotency_key=f"message.post:{post_id}:recipient:{recipient.id}",
        event_type="message.post.received",
        template_key="message_received",
        source_type="message_post",
        source_id=post_id,
        message_post_id=post_id,
        recipient_user_id=recipient.id,
        recipient_email=recipient.email,
        sender_name=sender_name,
        deep_link_path=f"/messages/{thread_id}",
        available_at=current + timedelta(seconds=max(settings.EMAIL_MESSAGE_DELAY_SECONDS, 0)),
    )


async def claim_email_batch(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
    lease_seconds: int | None = None,
) -> list[EmailOutbox]:
    """Atomically claim due jobs; callers commit before provider I/O."""
    current = now or utc_now()
    limit = max(1, min(batch_size or settings.EMAIL_WORKER_BATCH_SIZE, 100))
    lease_for = max(30, lease_seconds or settings.EMAIL_WORKER_LEASE_SECONDS)

    await db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.status == "processing",
            EmailOutbox.lease_expires_at <= current,
        )
        .values(
            status="pending",
            lease_token=None,
            lease_expires_at=None,
            available_at=current,
            last_error="lease_expired",
            updated_at=current,
        )
    )

    jobs = list(
        (
            await db.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == "pending",
                    EmailOutbox.available_at <= current,
                    EmailOutbox.attempt_count < EmailOutbox.max_attempts,
                )
                .order_by(EmailOutbox.available_at.asc(), EmailOutbox.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    lease_expires_at = current + timedelta(seconds=lease_for)
    for job in jobs:
        job.status = "processing"
        job.attempt_count += 1
        job.lease_token = uuid.uuid4()
        job.lease_expires_at = lease_expires_at
        job.updated_at = current
    await db.flush()
    return jobs


async def mark_email_group_sent(
    db: AsyncSession,
    jobs: Iterable[EmailOutbox],
    *,
    provider_message_id: str,
    now: datetime | None = None,
) -> int:
    """Finalize only rows still owned by the supplied leases."""
    current = now or utc_now()
    updated = 0
    for job in jobs:
        if job.lease_token is None:
            continue
        result = await db.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.id == job.id,
                EmailOutbox.status == "processing",
                EmailOutbox.lease_token == job.lease_token,
            )
            .values(
                status="sent",
                provider_message_id=provider_message_id[:255],
                sent_at=current,
                lease_token=None,
                lease_expires_at=None,
                last_error=None,
                updated_at=current,
            )
        )
        updated += int(result.rowcount or 0)
    return updated


def sanitized_delivery_error(error: BaseException) -> str:
    """Return a bounded class-only reason, never provider text or credentials."""
    name = type(error).__name__ or "DeliveryError"
    return name[:120]


async def mark_email_group_failed(
    db: AsyncSession,
    jobs: Iterable[EmailOutbox],
    *,
    error_code: str,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Retry leased rows with bounded backoff or move exhausted rows to failed."""
    current = now or utc_now()
    retry_count = 0
    failed_count = 0
    clean_error = (error_code or "DeliveryError")[:120]
    for job in jobs:
        if job.lease_token is None:
            continue
        terminal = job.attempt_count >= job.max_attempts
        delay_seconds = min(
            max(2 ** max(job.attempt_count, 1), 2),
            max(settings.EMAIL_RETRY_MAX_SECONDS, 2),
        )
        values = {
            "status": "failed" if terminal else "pending",
            "available_at": current if terminal else current + timedelta(seconds=delay_seconds),
            "lease_token": None,
            "lease_expires_at": None,
            "last_error": clean_error,
            "updated_at": current,
        }
        result = await db.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.id == job.id,
                EmailOutbox.status == "processing",
                EmailOutbox.lease_token == job.lease_token,
            )
            .values(**values)
        )
        if result.rowcount:
            if terminal:
                failed_count += 1
            else:
                retry_count += 1
    return retry_count, failed_count


def group_claimed_emails(jobs: Iterable[EmailOutbox]) -> list[list[EmailOutbox]]:
    """Coalesce only jobs claimed together for one recipient and one destination."""
    grouped: dict[tuple[str, str, str], list[EmailOutbox]] = {}
    for job in jobs:
        key = (job.recipient_email, job.template_key, job.deep_link_path)
        grouped.setdefault(key, []).append(job)
    return list(grouped.values())
