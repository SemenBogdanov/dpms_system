"""Authenticated local API smoke for verified email-login changes."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import (
    create_access_token,
    create_email_change_token,
    decode_access_token,
    decode_email_change_token,
    get_password_hash,
)
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.email_change_request import EmailChangeRequest
from app.models.email_outbox import EmailOutbox
from app.models.user import League, User, UserRole
from app.workers.email_outbox import build_delivery


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}
SMOKE_PASSWORD = "EmailChangeSmokeA123"


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Email-change smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Email-change smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    api_request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(api_request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def expect(status: int, expected: int, payload: Any, label: str) -> Any:
    if status != expected:
        raise AssertionError(
            f"{label}: expected HTTP {expected}, got {status}: {payload}"
        )
    return payload


async def create_fixture_users() -> tuple[list[uuid.UUID], str, User, User]:
    marker = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        admin = User(
            full_name="Email change smoke admin",
            email=f"email-change-admin-{marker}@dpms-demo.ru",
            league=League.A,
            role=UserRole.admin,
            mpw=0,
            is_active=True,
            password_hash=get_password_hash(SMOKE_PASSWORD),
            password_change_required=False,
        )
        first = User(
            full_name="Email change smoke first",
            email=f"email-change-first-{marker}@dpms-demo.ru",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            is_active=True,
            password_hash=get_password_hash(SMOKE_PASSWORD),
            password_change_required=False,
        )
        second = User(
            full_name="Email change smoke second",
            email=f"email-change-second-{marker}@dpms-demo.ru",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            is_active=True,
            password_hash=get_password_hash(SMOKE_PASSWORD),
            password_change_required=False,
        )
        db.add_all([admin, first, second])
        await db.commit()
        return (
            [admin.id, first.id, second.id],
            create_access_token({"sub": str(admin.id), "ver": admin.auth_version}),
            first,
            second,
        )


async def cleanup(user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(EmailOutbox).where(EmailOutbox.recipient_user_id.in_(user_ids)))
        await db.execute(delete(EmailChangeRequest).where(EmailChangeRequest.user_id.in_(user_ids)))
        await db.execute(delete(ActivityEvent).where(ActivityEvent.actor_id.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def outbox_for_request(request_id: uuid.UUID) -> list[EmailOutbox]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(EmailOutbox)
                    .where(EmailOutbox.source_id == request_id)
                    .order_by(EmailOutbox.template_key.asc())
                )
            ).scalars()
        )


async def run() -> None:
    ensure_safe_target()
    user_ids: list[uuid.UUID] = []
    original_public_url = settings.PUBLIC_APP_URL
    try:
        settings.PUBLIC_APP_URL = "https://example.invalid"
        user_ids, admin_token, first, second = await create_fixture_users()
        first_old_email = first.email
        first_new_email = f"changed-{uuid.uuid4().hex}@dpms-demo.ru"
        second_new_email = f"assisted-{uuid.uuid4().hex}@dpms-demo.ru"

        status, login = request(
            "POST",
            "/api/auth/login",
            body={"email": first_old_email, "password": SMOKE_PASSWORD},
        )
        login = expect(status, 200, login, "login before email change")
        first_token = login["access_token"]

        status, payload = request(
            "PATCH",
            f"/api/users/{first.id}",
            token=admin_token,
            body={"email": first_new_email},
        )
        expect(status, 422, payload, "direct admin email replacement is forbidden")

        status, payload = request(
            "POST",
            "/api/auth/email-change/request",
            token=first_token,
            body={"new_email": first_new_email, "current_password": "wrong-password"},
        )
        expect(status, 400, payload, "current password is required")

        status, created = request(
            "POST",
            "/api/auth/email-change/request",
            token=first_token,
            body={"new_email": first_new_email, "current_password": SMOKE_PASSWORD},
        )
        created = expect(status, 200, created, "self-service request")
        first_request_id = uuid.UUID(created["id"])
        assert created["status"] == "pending" and created["request_kind"] == "self"

        status, pending = request("GET", "/api/auth/email-change", token=first_token)
        pending = expect(status, 200, pending, "pending request status")
        assert pending["request"]["id"] == str(first_request_id)

        jobs = await outbox_for_request(first_request_id)
        assert {job.template_key for job in jobs} == {
            "email_change_alert",
            "email_change_verify",
        }
        persisted = " ".join(
            str(value)
            for job in jobs
            for value in (
                job.idempotency_key,
                job.event_type,
                job.source_type,
                job.deep_link_path,
                job.last_error,
            )
        ).lower()
        assert "token=" not in persisted and "#" not in persisted and "?" not in persisted
        verify_job = next(job for job in jobs if job.template_key == "email_change_verify")
        delivery = build_delivery([verify_job])
        fragment = parse_qs(urlparse(delivery.deep_link_url).fragment)
        delivered_token = fragment["token"][0]
        assert fragment["action"] == ["confirm"]
        assert decode_access_token(delivered_token) is None
        assert decode_email_change_token(
            delivered_token,
            expected_action="confirm",
        ) == first_request_id

        cancel_token = create_email_change_token(first_request_id, "cancel")
        assert decode_access_token(cancel_token) is None
        status, payload = request(
            "POST",
            "/api/auth/email-change/confirm",
            body={"token": cancel_token},
        )
        expect(status, 400, payload, "action-bound token")

        status, profile = request("GET", "/api/auth/me", token=first_token)
        expect(status, 200, profile, "old session remains valid while pending")

        confirm_token = create_email_change_token(first_request_id, "confirm")
        status, result = request(
            "POST",
            "/api/auth/email-change/confirm",
            body={"token": confirm_token},
        )
        result = expect(status, 200, result, "confirm new mailbox")
        assert result["reauth_required"] is True

        status, payload = request("GET", "/api/auth/me", token=first_token)
        expect(status, 401, payload, "old session revoked")
        status, payload = request(
            "POST",
            "/api/auth/login",
            body={"email": first_old_email, "password": SMOKE_PASSWORD},
        )
        expect(status, 401, payload, "old login rejected")
        status, payload = request(
            "POST",
            "/api/auth/login",
            body={"email": first_new_email, "password": SMOKE_PASSWORD},
        )
        expect(status, 200, payload, "new login accepted")
        status, payload = request(
            "POST",
            "/api/auth/email-change/confirm",
            body={"token": confirm_token},
        )
        expect(status, 409, payload, "single-use confirmation")

        status, assisted = request(
            "POST",
            f"/api/users/{second.id}/email-change-request",
            token=admin_token,
            body={
                "new_email": second_new_email,
                "reason": "Smoke test of administrator-assisted continuity",
            },
        )
        assisted = expect(status, 200, assisted, "admin-assisted request")
        second_request_id = uuid.UUID(assisted["id"])
        assert assisted["request_kind"] == "admin_assisted"

        status, result = request(
            "POST",
            "/api/auth/email-change/cancel-link",
            body={"token": create_email_change_token(second_request_id, "cancel")},
        )
        expect(status, 200, result, "old mailbox cancellation")
        status, payload = request(
            "POST",
            "/api/auth/email-change/confirm",
            body={"token": create_email_change_token(second_request_id, "confirm")},
        )
        expect(status, 409, payload, "cancelled request cannot be confirmed")

        status, history = request(
            "GET",
            f"/api/users/{first.id}/admin-history",
            token=admin_token,
        )
        history = expect(status, 200, history, "email-change audit history")
        actions = {item["action"] for item in history["items"]}
        assert {"email_change_requested", "email_change_confirmed"}.issubset(actions)
        serialized_history = json.dumps(history, ensure_ascii=False).lower()
        assert "current_password" not in serialized_history
        assert "password_hash" not in serialized_history
        assert "token" not in serialized_history

        print(
            "Email change smoke OK: verified self/admin flows, action-bound single-use "
            "links, body-free outbox, audit, login switch, and session revocation"
        )
    finally:
        settings.PUBLIC_APP_URL = original_public_url
        await cleanup(user_ids)


if __name__ == "__main__":
    asyncio.run(run())
