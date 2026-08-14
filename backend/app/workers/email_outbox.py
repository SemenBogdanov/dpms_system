"""Standalone lease-based email outbox worker."""
from __future__ import annotations

import asyncio
import logging
import re
import signal
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit
from uuid import UUID

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.email_outbox import EmailOutbox
from app.services.email_outbox import (
    claim_email_batch,
    group_claimed_emails,
    mark_email_group_failed,
    mark_email_group_sent,
    sanitized_delivery_error,
)


logger = logging.getLogger("dpms.email_worker")


class EmailDeliveryError(RuntimeError):
    """Provider configuration or transport failure without sensitive details."""


@dataclass(frozen=True)
class EmailDelivery:
    recipient_email: str
    sender_name: str | None
    event_count: int
    deep_link_url: str
    message_id: str


class EmailProvider:
    async def send(self, delivery: EmailDelivery) -> str:
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    """Local provider that records delivery metadata but never email content."""

    async def send(self, delivery: EmailDelivery) -> str:
        logger.info(
            "email_delivery=console event_count=%d message_id=%s",
            delivery.event_count,
            delivery.message_id,
        )
        return f"console:{delivery.message_id}"[:255]


class SMTPEmailProvider(EmailProvider):
    def __init__(self) -> None:
        if not settings.SMTP_HOST:
            raise EmailDeliveryError("smtp_host_missing")
        if settings.SMTP_SSL and settings.SMTP_STARTTLS:
            raise EmailDeliveryError("smtp_tls_modes_conflict")

    def _message(self, delivery: EmailDelivery) -> EmailMessage:
        sender = delivery.sender_name or "Сотрудник"
        if delivery.event_count == 1:
            subject = "Новое сообщение в Простосделал.рф"
            lead = f"{sender} отправил(а) вам сообщение в системе Простосделал.рф."
        else:
            subject = "Новые сообщения в Простосделал.рф"
            lead = (
                f"{sender} отправил(а) вам новые сообщения "
                f"({delivery.event_count}) в системе Простосделал.рф."
            )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(
            (settings.EMAIL_FROM_NAME, settings.EMAIL_FROM_ADDRESS)
        )
        message["To"] = delivery.recipient_email
        message["Message-ID"] = delivery.message_id
        message.set_content(
            f"{lead}\n\n"
            f"Открыть переписку: {delivery.deep_link_url}\n\n"
            "Текст сообщения не включен в email. Откройте систему, чтобы прочитать его."
        )
        return message

    def _send_sync(self, delivery: EmailDelivery) -> str:
        message = self._message(delivery)
        timeout = max(settings.SMTP_TIMEOUT_SECONDS, 5)
        context = ssl.create_default_context()
        try:
            if settings.SMTP_SSL:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=timeout,
                    context=context,
                )
            else:
                client = smtplib.SMTP(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=timeout,
                )
            with client:
                client.ehlo()
                if settings.SMTP_STARTTLS:
                    client.starttls(context=context)
                    client.ehlo()
                if settings.SMTP_USERNAME:
                    client.login(
                        settings.SMTP_USERNAME,
                        settings.SMTP_PASSWORD or "",
                    )
                client.send_message(message)
        except Exception as error:
            raise EmailDeliveryError(sanitized_delivery_error(error)) from error
        return delivery.message_id

    async def send(self, delivery: EmailDelivery) -> str:
        return await asyncio.to_thread(self._send_sync, delivery)


def build_provider() -> EmailProvider | None:
    mode = settings.EMAIL_DELIVERY_MODE.strip().lower()
    if mode == "disabled":
        return None
    if mode == "console":
        return ConsoleEmailProvider()
    if mode == "smtp":
        return SMTPEmailProvider()
    raise EmailDeliveryError("unsupported_email_delivery_mode")


def _message_id(job_id: object) -> str:
    domain = urlsplit(f"mailto:{settings.EMAIL_FROM_ADDRESS}").path.rsplit("@", 1)
    candidate = domain[-1] if len(domain) == 2 else "dpms.local"
    safe_domain = re.sub(r"[^A-Za-z0-9.-]", "", candidate) or "dpms.local"
    return f"<dpms-email-{job_id}@{safe_domain}>"


def build_delivery(jobs: list[EmailOutbox]) -> EmailDelivery:
    if not jobs:
        raise ValueError("empty email group")
    first = jobs[0]
    base = settings.PUBLIC_APP_URL.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EmailDeliveryError("public_app_url_invalid")
    if not first.deep_link_path.startswith("/") or first.deep_link_path.startswith("//"):
        raise EmailDeliveryError("deep_link_invalid")
    return EmailDelivery(
        recipient_email=first.recipient_email,
        sender_name=jobs[-1].sender_name,
        event_count=len(jobs),
        deep_link_url=f"{base}{first.deep_link_path}",
        message_id=_message_id(first.id),
    )


async def run_worker_once(
    provider: EmailProvider,
    *,
    now: datetime | None = None,
    recipient_user_id: UUID | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        jobs = await claim_email_batch(
            db,
            now=now,
            recipient_user_id=recipient_user_id,
        )
        await db.commit()
    if not jobs:
        return 0

    processed = 0
    for group in group_claimed_emails(jobs):
        try:
            provider_message_id = await provider.send(build_delivery(group))
        except Exception as error:
            error_code = sanitized_delivery_error(error)
            logger.warning(
                "email_delivery=failed job_count=%d error_code=%s",
                len(group),
                error_code,
            )
            async with AsyncSessionLocal() as db:
                await mark_email_group_failed(db, group, error_code=error_code)
                await db.commit()
        else:
            async with AsyncSessionLocal() as db:
                await mark_email_group_sent(
                    db,
                    group,
                    provider_message_id=provider_message_id,
                )
                await db.commit()
            logger.info("email_delivery=sent job_count=%d", len(group))
        processed += len(group)
    return processed


async def _sleep_until_stop(stop_event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(timeout, 0.1))
    except asyncio.TimeoutError:
        pass


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:
            pass

    try:
        provider = build_provider()
    except EmailDeliveryError as error:
        logger.error("email_worker_start=failed error_code=%s", sanitized_delivery_error(error))
        raise SystemExit(2) from error

    if provider is None:
        logger.info("email_worker=disabled")
        await stop_event.wait()
        return

    logger.info("email_worker=started mode=%s", settings.EMAIL_DELIVERY_MODE.lower())
    while not stop_event.is_set():
        try:
            processed = await run_worker_once(provider)
        except Exception as error:
            logger.error(
                "email_worker_cycle=failed error_code=%s",
                sanitized_delivery_error(error),
            )
            processed = 0
        if processed == 0:
            await _sleep_until_stop(stop_event, settings.EMAIL_WORKER_POLL_SECONDS)
    logger.info("email_worker=stopped")


if __name__ == "__main__":
    asyncio.run(run())
