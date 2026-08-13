"""Real local API smoke for login, session revocation, and deactivation."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token, get_password_hash
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.user import League, User, UserRole


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}
SMOKE_PASSWORD = "AuthSmokeA123"


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Auth smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Auth smoke refuses a non-local database")


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


def expect(status: int, expected: int, label: str) -> None:
    if status != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {status}")


async def create_fixture_users() -> tuple[User, User]:
    marker = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        active = User(
            full_name="Auth session smoke active",
            email=f"auth-session-active-{marker}@dpms-demo.ru",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            is_active=True,
            password_hash=get_password_hash(SMOKE_PASSWORD),
            password_change_required=False,
        )
        inactive = User(
            full_name="Auth session smoke inactive",
            email=f"auth-session-inactive-{marker}@dpms-demo.ru",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            is_active=False,
            password_hash=get_password_hash(SMOKE_PASSWORD),
            password_change_required=False,
        )
        db.add_all([active, inactive])
        await db.commit()
        return active, inactive


async def increment_auth_version(user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.auth_version += 1
        await db.commit()


async def cleanup(user_ids: list[uuid.UUID]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ActivityEvent).where(ActivityEvent.actor_id.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def run() -> None:
    ensure_safe_target()
    active: User | None = None
    inactive: User | None = None
    try:
        active, inactive = await create_fixture_users()

        status, login = request(
            "POST",
            "/api/auth/login",
            body={"email": active.email, "password": SMOKE_PASSWORD},
        )
        expect(status, 200, "valid login")
        token = login.get("access_token") if isinstance(login, dict) else None
        assert isinstance(token, str) and token

        status, profile = request("GET", "/api/auth/me", token=token)
        expect(status, 200, "authenticated profile")
        assert isinstance(profile, dict) and profile.get("id") == str(active.id)

        status, _ = request(
            "POST",
            "/api/auth/login",
            body={"email": active.email, "password": "wrong-password"},
        )
        expect(status, 401, "invalid password")

        await increment_auth_version(active.id)
        status, _ = request("GET", "/api/auth/me", token=token)
        expect(status, 401, "revoked token")

        inactive_token = create_access_token(
            {"sub": str(inactive.id), "ver": inactive.auth_version}
        )
        status, _ = request("GET", "/api/auth/me", token=inactive_token)
        expect(status, 401, "inactive user session")

        print("Auth session smoke OK: login, /me, revocation, inactive guard")
    finally:
        ids = [user.id for user in (active, inactive) if user is not None]
        if ids:
            await cleanup(ids)


if __name__ == "__main__":
    asyncio.run(run())
