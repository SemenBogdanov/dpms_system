"""Authenticated and concurrent local smoke for personal storage quotas."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.storage_quota import UserStorageFile, UserStorageQuota
from app.models.user import League, User, UserRole
from app.services.storage_quota import (
    StorageReservation,
    activate_storage_file,
    finalize_storage_file_deletion,
    reserve_storage_file,
    schedule_storage_file_deletion,
)


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}
MIB = 1024 * 1024


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Storage quota smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Storage quota smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    api_request = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(api_request, timeout=15) as response:
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


def token_for(user: User) -> str:
    return create_access_token({"sub": str(user.id), "ver": user.auth_version})


async def create_user(
    *,
    marker: str,
    suffix: str,
    role: UserRole,
) -> User:
    user = User(
        id=uuid.uuid4(),
        full_name=f"Storage quota smoke {suffix}",
        email=f"storage-quota-{suffix}-{marker}@example.invalid",
        league=League.A if role == UserRole.admin else League.C,
        role=role,
        password_hash=None,
    )
    async with AsyncSessionLocal() as db:
        async with db.begin():
            db.add(user)
            await db.flush()
    return user


async def cleanup_users(user_ids: list[uuid.UUID]) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(
                delete(ActivityEvent).where(ActivityEvent.actor_id.in_(user_ids))
            )
            await db.execute(delete(User).where(User.id.in_(user_ids)))


async def assert_concurrent_reservation(
    marker: str,
    user_ids: list[uuid.UUID],
) -> None:
    user = await create_user(
        marker=marker,
        suffix="concurrency",
        role=UserRole.executor,
    )
    user_ids.append(user.id)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            db.add(
                UserStorageQuota(
                    user_id=user.id,
                    limit_bytes=10,
                    used_bytes=0,
                    reserved_bytes=0,
                )
            )

    filenames = [f"quota-smoke/{marker}-{index}.txt" for index in range(2)]
    results = await asyncio.gather(
        *(
            reserve_storage_file(
                owner_id=user.id,
                stored_filename=filename,
                size_bytes=6,
                category="quick_note",
            )
            for filename in filenames
        ),
        return_exceptions=True,
    )
    reservations = [item for item in results if isinstance(item, StorageReservation)]
    rejected = [
        item
        for item in results
        if isinstance(item, HTTPException) and item.status_code == 413
    ]
    assert len(reservations) == 1, results
    assert len(rejected) == 1, results

    reservation = reservations[0]
    async with AsyncSessionLocal() as db:
        async with db.begin():
            account = await db.get(UserStorageQuota, user.id)
            assert account is not None
            assert (account.used_bytes, account.reserved_bytes) == (0, 6)
            await activate_storage_file(db, reservation.id)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            account = await db.get(UserStorageQuota, user.id)
            assert account is not None
            assert (account.used_bytes, account.reserved_bytes) == (6, 0)
            storage_file_id = await schedule_storage_file_deletion(
                db,
                owner_id=user.id,
                stored_filename=reservation.stored_filename,
            )

    assert await finalize_storage_file_deletion(storage_file_id)
    async with AsyncSessionLocal() as db:
        account = await db.get(UserStorageQuota, user.id)
        stored_file = await db.scalar(
            select(UserStorageFile).where(UserStorageFile.id == reservation.id)
        )
        assert account is not None
        assert (account.used_bytes, account.reserved_bytes) == (0, 0)
        assert stored_file is not None and stored_file.status == "released"
async def assert_api_workflow(
    marker: str,
    user_ids: list[uuid.UUID],
) -> None:
    user = await create_user(
        marker=marker,
        suffix="user",
        role=UserRole.executor,
    )
    admin = await create_user(
        marker=marker,
        suffix="admin",
        role=UserRole.admin,
    )
    user_ids.extend([user.id, admin.id])
    user_token = token_for(user)
    admin_token = token_for(admin)

    status, payload = request("GET", "/api/storage-quota/me", user_token)
    summary = expect(status, 200, payload, "initial quota")
    assert summary["quota_bytes"] == 50 * MIB

    status, payload = request(
        "POST",
        "/api/storage-quota/me/requests",
        user_token,
        body={
            "requested_limit_bytes": 100 * MIB,
            "reason": "Нужно хранить рабочие материалы личных задач",
        },
    )
    quota_request = expect(status, 201, payload, "create increase request")

    status, payload = request(
        "GET",
        "/api/storage-quota/admin/requests",
        admin_token,
        query={"status": "pending"},
    )
    pending = expect(status, 200, payload, "admin pending requests")
    assert any(item["id"] == quota_request["id"] for item in pending)

    status, payload = request(
        "POST",
        f"/api/storage-quota/admin/requests/{quota_request['id']}/decision",
        admin_token,
        body={
            "decision": "approved",
            "comment": "Согласовано для рабочих материалов",
            "approved_limit_bytes": 75 * MIB,
        },
    )
    decision = expect(status, 200, payload, "approve increase request")
    assert decision["approved_limit_bytes"] == 75 * MIB

    status, payload = request("GET", "/api/storage-quota/me", user_token)
    summary = expect(status, 200, payload, "approved quota")
    assert summary["quota_bytes"] == 75 * MIB

    async with AsyncSessionLocal() as db:
        event_types = set(
            (
                await db.execute(
                    select(ActivityEvent.event_type).where(
                        ActivityEvent.actor_id.in_([user.id, admin.id])
                    )
                )
            ).scalars()
        )
    assert "storage_quota_increase_requested" in event_types
    assert "storage_quota_increase_approved" in event_types
async def main() -> None:
    ensure_safe_target()
    marker = uuid.uuid4().hex
    user_ids: list[uuid.UUID] = []
    try:
        await assert_concurrent_reservation(marker, user_ids)
        await assert_api_workflow(marker, user_ids)
    finally:
        if user_ids:
            await cleanup_users(user_ids)
    print("Storage quota smoke: 2/2 checks passed")


if __name__ == "__main__":
    asyncio.run(main())
