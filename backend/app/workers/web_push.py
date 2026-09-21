"""Deliver durable, content-free Web Push notifications to Apple devices."""
import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timedelta, timezone
from uuid import UUID

import requests
from pywebpush import WebPushException, webpush
from sqlalchemy import or_, select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.messages import MessagePost, MessageThreadParticipant, UserAttentionItem
from app.models.web_push import WebPushDelivery, WebPushSubscription
from app.services.web_push import public_key, validate_subscription, validate_vapid_configuration, vapid_subject

logger = logging.getLogger("dpms.web_push_worker")


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


async def claim_one(now: datetime) -> tuple[WebPushDelivery, WebPushSubscription, bool] | None:
    async with AsyncSessionLocal() as db:
        delivery = (await db.execute(
            select(WebPushDelivery).where(
                or_(
                    (WebPushDelivery.status == "pending") & (WebPushDelivery.due_at <= now),
                    (WebPushDelivery.status == "leased") & (WebPushDelivery.lease_until <= now),
                )
            ).order_by(WebPushDelivery.due_at, WebPushDelivery.created_at)
            .with_for_update(skip_locked=True).limit(1)
        )).scalar_one_or_none()
        if delivery is None:
            return None
        subscription = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.id == delivery.subscription_id))).scalar_one()
        active = (await db.execute(select(User.is_active).where(User.id == subscription.user_id))).scalar_one()
        unread = False
        try:
            _, source_id = delivery.event_key.split(":", 1)
            source_uuid = UUID(source_id)
            if delivery.event_key.startswith("attention:"):
                unread = (await db.execute(select(UserAttentionItem.id).where(
                    UserAttentionItem.user_id == subscription.user_id,
                    UserAttentionItem.event_id == source_uuid,
                    UserAttentionItem.is_read.is_(False),
                ).limit(1))).scalar_one_or_none() is not None
            elif delivery.event_key.startswith("post:"):
                unread = (await db.execute(select(MessageThreadParticipant.id).join(
                    MessagePost, MessagePost.thread_id == MessageThreadParticipant.thread_id,
                ).where(
                    MessagePost.id == source_uuid,
                    MessageThreadParticipant.user_id == subscription.user_id,
                    MessageThreadParticipant.unread_count > 0,
                ).limit(1))).scalar_one_or_none() is not None
        except (ValueError, TypeError):
            pass
        delivery.status = "leased"
        delivery.lease_until = now + timedelta(seconds=60)
        delivery.attempts += 1
        await db.commit()
        return delivery, subscription, active and unread


def send_one(delivery: WebPushDelivery, subscription: WebPushSubscription) -> None:
    validate_subscription(subscription.endpoint, subscription.p256dh, subscription.auth_value)
    body = json.dumps({
        "title": "Новое сообщение" if delivery.kind == "direct" else "Важное событие",
        "body": "Откройте Простосделал.рф, чтобы посмотреть.",
        "path": delivery.path,
        "tag": delivery.event_key,
    }, ensure_ascii=False)
    with NoRedirectSession() as session:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth_value},
            },
            data=body,
            vapid_private_key=os.environ["DPMS_WEB_PUSH_PRIVATE_KEY"],
            vapid_claims={"sub": vapid_subject()},
            timeout=12,
            ttl=3600,
            requests_session=session,
        )


async def finish_one(delivery: WebPushDelivery, *, invalid: bool = False, retry: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        current = (await db.execute(select(WebPushDelivery).where(WebPushDelivery.id == delivery.id))).scalar_one_or_none()
        if current is None:
            return
        if invalid:
            subscription = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.id == current.subscription_id))).scalar_one_or_none()
            if subscription:
                await db.delete(subscription)
        elif retry and current.attempts < 5:
            current.status = "pending"
            current.due_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** current.attempts * 10))
            current.lease_until = None
        else:
            current.status = "failed" if retry else "sent"
            current.lease_until = None
        await db.commit()


async def run_once() -> bool:
    claimed = await claim_one(datetime.now(timezone.utc))
    if claimed is None:
        return False
    delivery, subscription, active = claimed
    if not active:
        await finish_one(delivery)
        return True
    try:
        await asyncio.to_thread(send_one, delivery, subscription)
    except WebPushException as error:
        response = error.response
        status = getattr(response, "status_code", None)
        await finish_one(delivery, invalid=status in (404, 410), retry=status not in (400, 401, 403, 404, 410))
        logger.warning("web_push_delivery=failed status=%s", status)
    except Exception as error:
        await finish_one(delivery, retry=True)
        logger.warning("web_push_delivery=retry error_type=%s", type(error).__name__)
    else:
        await finish_one(delivery)
        logger.info("web_push_delivery=sent")
    return True


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    if public_key() is None:
        logger.info("web_push_worker=disabled")
        await stop.wait()
        return
    validate_vapid_configuration()
    while not stop.is_set():
        try:
            found = await run_once()
        except Exception:
            logger.exception("web_push_worker=unexpected_error")
            found = False
        if not found:
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(run())
