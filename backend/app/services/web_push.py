"""Web Push subscription validation and transactional delivery enqueue."""
import base64
import hashlib
import os
import re
import uuid
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.web_push import WebPushDelivery, WebPushSubscription


def decode_urlsafe(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Некорректный ключ подписки")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def public_key() -> str | None:
    raw = os.getenv("DPMS_WEB_PUSH_PRIVATE_KEY", "")
    if not raw:
        return None
    key_bytes = decode_urlsafe(raw)
    if len(key_bytes) != 32:
        raise ValueError("DPMS_WEB_PUSH_PRIVATE_KEY must be a raw 32-byte P-256 key")
    private = ec.derive_private_key(int.from_bytes(key_bytes, "big"), ec.SECP256R1())
    encoded = private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def vapid_subject() -> str:
    subject = os.getenv("DPMS_WEB_PUSH_SUBJECT", settings.PUBLIC_APP_URL).strip()
    parsed = urlsplit(subject)
    if parsed.scheme == "mailto" and "@" in parsed.path and not parsed.query and not parsed.fragment:
        return subject
    if (parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment):
        return f"https://{parsed.netloc}"
    raise ValueError("DPMS_WEB_PUSH_SUBJECT must be an HTTPS URL or mailto address")


def validate_vapid_configuration() -> None:
    raw = os.getenv("DPMS_WEB_PUSH_PRIVATE_KEY", "")
    if public_key() is None:
        raise ValueError("DPMS_WEB_PUSH_PRIVATE_KEY is missing")
    Vapid.from_string(raw).sign({"sub": vapid_subject(), "aud": "https://web.push.apple.com"})


def validate_subscription(endpoint: str, p256dh: str, auth_value: str) -> None:
    if len(endpoint) > 2048 or len(endpoint) < 30:
        raise ValueError("Некорректный адрес push-сервиса")
    url = urlsplit(endpoint)
    host = (url.hostname or "").lower()
    if (url.scheme != "https" or not host.endswith(".push.apple.com")
            or url.port not in (None, 443) or url.username or url.password
            or url.fragment or not url.path):
        raise ValueError("Поддерживаются только подписки Web Push от Apple")
    key = decode_urlsafe(p256dh)
    secret = decode_urlsafe(auth_value)
    if len(key) != 65 or key[0] != 4 or len(secret) < 16 or len(secret) > 32:
        raise ValueError("Некорректные ключи подписки")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


async def save_subscription(db: AsyncSession, *, user_id: UUID, endpoint: str, p256dh: str, auth_value: str) -> None:
    validate_subscription(endpoint, p256dh, auth_value)
    digest = endpoint_hash(endpoint)
    existing = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.endpoint_hash == digest))).scalar_one_or_none()
    if existing:
        if existing.user_id != user_id:
            # A browser subscription can outlive a logout. Drop its old user's queued jobs.
            await db.delete(existing)
            await db.flush()
        else:
            existing.p256dh = p256dh
            existing.auth_value = auth_value
            return
    count = (await db.execute(select(func.count(WebPushSubscription.id)).where(WebPushSubscription.user_id == user_id))).scalar_one()
    if count >= 20:
        oldest = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.user_id == user_id).order_by(WebPushSubscription.created_at, WebPushSubscription.id).limit(1))).scalar_one()
        await db.delete(oldest)
        await db.flush()
    db.add(WebPushSubscription(id=uuid.uuid4(), user_id=user_id, endpoint_hash=digest, endpoint=endpoint, p256dh=p256dh, auth_value=auth_value))


async def enqueue_push(db: AsyncSession, *, user_id: UUID, event_key: str, kind: str, path: str) -> None:
    if kind not in {"direct", "important"} or not path.startswith("/messages") or path.startswith("//"):
        raise ValueError("Unsupported push event")
    ids = (await db.execute(select(WebPushSubscription.id).where(WebPushSubscription.user_id == user_id))).scalars().all()
    for subscription_id in ids:
        await db.execute(
            insert(WebPushDelivery).values(
                id=uuid.uuid4(), subscription_id=subscription_id,
                event_key=event_key[:100], kind=kind, path=path,
                status="pending", attempts=0,
            ).on_conflict_do_nothing(constraint="uq_web_push_delivery_event")
        )
