"""Local durable email outbox smoke: idempotency, leases, retry and privacy."""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.email_outbox import EmailOutbox
from app.models.messages import MessagePost, MessageThread
from app.models.user import League, User, UserRole
from app.services.email_outbox import (
    claim_email_batch,
    enqueue_email_notification,
    enqueue_message_notification,
    group_claimed_emails,
    mark_email_group_failed,
    mark_email_group_sent,
    sanitized_delivery_error,
)
from app.workers.email_outbox import (
    ConsoleEmailProvider,
    build_delivery,
    logger,
    run_worker_once,
)


SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}


def ensure_safe_target() -> None:
    url = make_url(settings.DATABASE_URL)
    if (url.host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Email outbox smoke refuses a non-local database")
    if "prod" in (url.database or "").lower():
        raise RuntimeError("Email outbox smoke refuses a production-like database")


async def cleanup(user_ids: list[uuid.UUID], thread_id: uuid.UUID | None) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EmailOutbox).where(EmailOutbox.recipient_user_id.in_(user_ids)))
        if thread_id is not None:
            await db.execute(delete(MessagePost).where(MessagePost.thread_id == thread_id))
            await db.execute(delete(MessageThread).where(MessageThread.id == thread_id))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def run() -> None:
    ensure_safe_target()
    marker = uuid.uuid4().hex
    user_ids: list[uuid.UUID] = []
    thread_id: uuid.UUID | None = None
    original_delay = settings.EMAIL_MESSAGE_DELAY_SECONDS
    original_url = settings.PUBLIC_APP_URL
    try:
        settings.EMAIL_MESSAGE_DELAY_SECONDS = 0
        settings.PUBLIC_APP_URL = "https://example.invalid"
        async with AsyncSessionLocal() as db:
            sender = User(
                full_name="Email outbox smoke sender",
                email=f"email-outbox-sender-{marker}@dpms-demo.ru",
                league=League.C,
                role=UserRole.executor,
                mpw=0,
                is_active=True,
            )
            recipient = User(
                full_name="Email outbox smoke recipient",
                email=f"email-outbox-recipient-{marker}@dpms-demo.ru",
                league=League.C,
                role=UserRole.executor,
                mpw=0,
                is_active=True,
            )
            db.add_all([sender, recipient])
            await db.flush()
            user_ids = [sender.id, recipient.id]
            thread = MessageThread(
                subject="Private smoke subject that must not enter outbox",
                created_by_id=sender.id,
                request_id=uuid.uuid4(),
            )
            db.add(thread)
            await db.flush()
            thread_id = thread.id
            first_post = MessagePost(
                thread_id=thread.id,
                author_id=sender.id,
                body=f"SECRET-MESSAGE-BODY-{marker}",
                request_id=uuid.uuid4(),
            )
            second_post = MessagePost(
                thread_id=thread.id,
                author_id=sender.id,
                body=f"SECOND-SECRET-BODY-{marker}",
                request_id=uuid.uuid4(),
            )
            db.add_all([first_post, second_post])
            await db.flush()
            future = datetime.now(timezone.utc) + timedelta(days=1)
            first_id = await enqueue_message_notification(
                db,
                post_id=first_post.id,
                thread_id=thread.id,
                recipient=recipient,
                sender_name=sender.full_name,
                now=future,
            )
            replay_id = await enqueue_message_notification(
                db,
                post_id=first_post.id,
                thread_id=thread.id,
                recipient=recipient,
                sender_name=sender.full_name,
                now=future,
            )
            second_id = await enqueue_message_notification(
                db,
                post_id=second_post.id,
                thread_id=thread.id,
                recipient=recipient,
                sender_name=sender.full_name,
                now=future,
            )
            assert first_id == replay_id and first_id != second_id
            await db.execute(
                update(EmailOutbox)
                .where(EmailOutbox.id.in_([first_id, second_id]))
                .values(max_attempts=3)
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = list(
                (
                    await db.execute(
                        select(EmailOutbox)
                        .where(EmailOutbox.recipient_user_id == user_ids[1])
                        .order_by(EmailOutbox.created_at.asc())
                    )
                ).scalars()
            )
            assert len(rows) == 2
            serialized = " ".join(
                str(value)
                for row in rows
                for value in (
                    row.idempotency_key,
                    row.event_type,
                    row.template_key,
                    row.source_type,
                    row.sender_name,
                    row.deep_link_path,
                )
            )
            assert "SECRET-MESSAGE-BODY" not in serialized
            assert "Private smoke subject" not in serialized
            assert all(row.deep_link_path == f"/messages/{thread_id}" for row in rows)
            assert len(group_claimed_emails(rows)) == 1

        claim_time = future + timedelta(hours=1)
        session_one = AsyncSessionLocal()
        session_two = AsyncSessionLocal()
        try:
            first_claim = await claim_email_batch(
                session_one, now=claim_time, batch_size=1, lease_seconds=30
            )
            second_claim = await claim_email_batch(
                session_two, now=claim_time, batch_size=1, lease_seconds=30
            )
            assert len(first_claim) == 1 and len(second_claim) == 1
            assert first_claim[0].id != second_claim[0].id
            await session_one.commit()
            await session_two.commit()
        finally:
            await session_one.close()
            await session_two.close()

        success_job = second_claim[0]
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        try:
            provider_id = await ConsoleEmailProvider().send(build_delivery([success_job]))
        finally:
            logger.removeHandler(handler)
        logs = stream.getvalue()
        assert recipient.email not in logs
        assert sender.full_name not in logs
        assert marker not in logs
        async with AsyncSessionLocal() as db:
            assert await mark_email_group_sent(
                db, [success_job], provider_message_id=provider_id, now=claim_time
            ) == 1
            await db.commit()

        expired_job = first_claim[0]
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(EmailOutbox)
                .where(EmailOutbox.id == expired_job.id)
                .values(lease_expires_at=claim_time - timedelta(seconds=1))
            )
            await db.commit()
        recovery_time = claim_time + timedelta(minutes=1)
        async with AsyncSessionLocal() as db:
            recovered = await claim_email_batch(db, now=recovery_time, batch_size=1)
            await db.commit()
        assert len(recovered) == 1 and recovered[0].id == expired_job.id
        assert recovered[0].attempt_count == 2

        assert sanitized_delivery_error(ValueError(f"secret-{marker}")) == "ValueError"
        async with AsyncSessionLocal() as db:
            retried, failed = await mark_email_group_failed(
                db,
                recovered,
                error_code="ValueError",
                now=recovery_time,
            )
            assert (retried, failed) == (1, 0)
            await db.commit()

        terminal_time = recovery_time + timedelta(minutes=1)
        async with AsyncSessionLocal() as db:
            terminal_claim = await claim_email_batch(
                db, now=terminal_time, batch_size=1
            )
            await db.commit()
        assert len(terminal_claim) == 1 and terminal_claim[0].attempt_count == 3
        async with AsyncSessionLocal() as db:
            retried, failed = await mark_email_group_failed(
                db,
                terminal_claim,
                error_code="SMTPConnectError",
                now=terminal_time,
            )
            assert (retried, failed) == (0, 1)
            await db.commit()

        async with AsyncSessionLocal() as db:
            statuses = dict(
                (
                    await db.execute(
                        select(EmailOutbox.id, EmailOutbox.status).where(
                            EmailOutbox.id.in_([first_id, second_id])
                        )
                    )
                ).all()
            )
            assert set(statuses.values()) == {"sent", "failed"}
            assert (
                await db.execute(
                    select(func.count(EmailOutbox.id)).where(
                        EmailOutbox.recipient_user_id == user_ids[1]
                    )
                )
            ).scalar_one() == 2

        worker_time = terminal_time + timedelta(days=1)
        async with AsyncSessionLocal() as db:
            worker_job_id = await enqueue_email_notification(
                db,
                idempotency_key=f"smoke.worker:{marker}",
                event_type="smoke.worker",
                template_key="message_received",
                source_type="smoke",
                source_id=None,
                recipient_user_id=user_ids[1],
                recipient_email=recipient.email,
                sender_name=sender.full_name,
                deep_link_path="/messages",
                available_at=worker_time,
                max_attempts=1,
            )
            await db.commit()
        assert await run_worker_once(ConsoleEmailProvider(), now=worker_time) == 1
        async with AsyncSessionLocal() as db:
            worker_status = (
                await db.execute(
                    select(EmailOutbox.status).where(EmailOutbox.id == worker_job_id)
                )
            ).scalar_one()
            assert worker_status == "sent"

        print(
            "Email outbox smoke OK: body-free enqueue, idempotency, SKIP LOCKED, "
            "lease recovery, coalescing, sanitized logs, worker cycle, success/retry/failure"
        )
    finally:
        settings.EMAIL_MESSAGE_DELAY_SECONDS = original_delay
        settings.PUBLIC_APP_URL = original_url
        if user_ids:
            await cleanup(user_ids, thread_id)


if __name__ == "__main__":
    asyncio.run(run())
