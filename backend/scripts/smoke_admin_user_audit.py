"""Authenticated local API smoke for admin user audit and access changes."""
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

from app.api.routes import admin as admin_routes
from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.schemas.admin import RolloverRequest
from app.models.user import League, User, UserRole


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}
FORBIDDEN_AUDIT_KEYS = {
    "password",
    "password_hash",
    "temporary_password",
    "auth_version",
    "token",
}


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Admin smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Admin smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
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


async def create_actors() -> tuple[list[uuid.UUID], str, str, str]:
    marker = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        admin = User(
            full_name="Admin audit smoke administrator",
            email=f"admin-audit-smoke-admin-{marker}@dpms-demo.ru",
            league=League.A,
            role=UserRole.admin,
            mpw=0,
            task_workspace_enabled=True,
            feedback_enabled=True,
            competency_development_enabled=True,
            is_active=True,
        )
        observer = User(
            full_name="Admin audit smoke observer",
            email=f"admin-audit-smoke-observer-{marker}@dpms-demo.ru",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            task_workspace_enabled=False,
            feedback_enabled=False,
            competency_development_enabled=True,
            is_active=True,
        )
        db.add_all([admin, observer])
        await db.commit()
        return (
            [admin.id, observer.id],
            create_access_token({"sub": str(admin.id), "ver": admin.auth_version}),
            create_access_token({"sub": str(observer.id), "ver": observer.auth_version}),
            observer.email,
        )


async def cleanup(user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ActivityEvent).where(ActivityEvent.actor_id.in_(user_ids)))
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def assert_admin_routes_use_authenticated_actor(admin_id: uuid.UUID) -> None:
    captured: list[uuid.UUID] = []

    async def fake_rollover(
        _db: Any,
        actor_id: uuid.UUID,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured.append(actor_id)
        return {
            "period": "2099-01",
            "users_processed": 0,
            "total_main_reset": 0.0,
            "total_karma_burned": 0.0,
        }

    async def fake_apply_leagues(_db: Any, actor_id: uuid.UUID) -> list[Any]:
        captured.append(actor_id)
        return []

    originals = (
        admin_routes.rollover_period,
        admin_routes.auto_close_previous_period,
        admin_routes.cancel_period_closure,
        admin_routes.apply_league_changes,
    )
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, admin_id)
        assert admin is not None
        try:
            admin_routes.rollover_period = fake_rollover
            admin_routes.auto_close_previous_period = fake_rollover
            admin_routes.cancel_period_closure = fake_rollover
            admin_routes.apply_league_changes = fake_apply_leagues
            assert "admin_id" not in RolloverRequest.model_fields
            await admin_routes.rollover_period_route(
                RolloverRequest(period="2099-01"),
                user=admin,
                db=db,
            )
            await admin_routes.auto_close_previous_period_route(user=admin, db=db)
            await admin_routes.cancel_period_closure_route("2099-01", user=admin, db=db)
            await admin_routes.apply_league_changes_route(user=admin, db=db)
        finally:
            (
                admin_routes.rollover_period,
                admin_routes.auto_close_previous_period,
                admin_routes.cancel_period_closure,
                admin_routes.apply_league_changes,
            ) = originals

    assert captured == [admin_id, admin_id, admin_id, admin_id]


def assert_audit_is_sanitized(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in FORBIDDEN_AUDIT_KEYS:
        assert f'"{forbidden}"' not in serialized, forbidden


async def run() -> None:
    ensure_safe_target()
    user_ids: list[uuid.UUID] = []
    target_id: uuid.UUID | None = None
    try:
        user_ids, admin_token, observer_token, observer_email = await create_actors()
        await assert_admin_routes_use_authenticated_actor(user_ids[0])
        marker = uuid.uuid4().hex
        status, created = request(
            "POST",
            "/api/users",
            admin_token,
            {
                "full_name": "Admin audit smoke target",
                "email": f"admin-audit-smoke-target-{marker}@dpms-demo.ru",
                "role": "executor",
                "league": "C",
                "mpw": 0,
                "is_new_employee": False,
                "task_workspace_enabled": False,
                "feedback_enabled": False,
                "competency_development_enabled": True,
                "competency_constructor_enabled": False,
                "password": "SmokeAuditA123",
            },
        )
        created = expect(status, 200, created, "create employee through admin API")
        target_id = uuid.UUID(created["id"])
        user_ids.append(target_id)

        status, users = request("GET", "/api/users/admin", admin_token)
        users = expect(status, 200, users, "authenticated admin page data")
        assert any(item["id"] == str(target_id) for item in users)

        status, payload = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            observer_token,
        )
        expect(status, 403, payload, "non-admin history access")

        status, history = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            admin_token,
        )
        history = expect(status, 200, history, "created employee history")
        assert history["total"] == 1
        assert history["items"][0]["action"] == "created"
        assert_audit_is_sanitized(history)

        status, payload = request(
            "PATCH",
            f"/api/users/{target_id}",
            admin_token,
            {"can_link_queue_tasks_to_projects": True},
        )
        expect(status, 400, payload, "project Q capability requires task workspace")

        changed_body = {
            "role": "teamlead",
            "mpw": 17,
            "feedback_enabled": True,
            "task_workspace_enabled": True,
            "can_link_queue_tasks_to_projects": True,
        }
        status, payload = request(
            "PATCH",
            f"/api/users/{target_id}",
            admin_token,
            changed_body,
        )
        expect(status, 200, payload, "update audited employee fields")

        status, history = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            admin_token,
        )
        history = expect(status, 200, history, "updated employee history")
        assert history["total"] == 2
        latest = history["items"][0]
        assert latest["action"] == "updated"
        assert latest["sessions_revoked"] is True
        changes = {item["field"]: item for item in latest["changes"]}
        assert set(changes) == {
            "role",
            "mpw",
            "feedback_enabled",
            "task_workspace_enabled",
            "can_link_queue_tasks_to_projects",
        }
        assert changes["role"] == {
            "field": "role",
            "before": "executor",
            "after": "teamlead",
        }
        assert_audit_is_sanitized(history)

        status, payload = request(
            "PATCH",
            f"/api/users/{target_id}",
            admin_token,
            changed_body,
        )
        expect(status, 200, payload, "no-op employee update")
        status, no_op_history = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            admin_token,
        )
        no_op_history = expect(status, 200, no_op_history, "history after no-op")
        assert no_op_history["total"] == 2

        status, payload = request(
            "PATCH",
            f"/api/users/{target_id}",
            admin_token,
            {"email": observer_email},
        )
        expect(status, 400, payload, "failed update is not audited")
        status, failed_history = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            admin_token,
        )
        failed_history = expect(status, 200, failed_history, "history after failed update")
        assert failed_history["total"] == 2

        status, payload = request(
            "PATCH",
            f"/api/users/{target_id}",
            admin_token,
            {
                "role": "executor",
                "mpw": 0,
                "feedback_enabled": False,
                "task_workspace_enabled": False,
                "can_link_queue_tasks_to_projects": False,
            },
        )
        expect(status, 200, payload, "restore audited employee fields")

        status, payload = request(
            "POST",
            f"/api/users/{target_id}/temporary-password",
            admin_token,
            {"temporary_password": "SmokeAuditB456"},
        )
        expect(status, 200, payload, "issue temporary password")
        status, final_history = request(
            "GET",
            f"/api/users/{target_id}/admin-history",
            admin_token,
        )
        final_history = expect(status, 200, final_history, "complete admin history")
        assert final_history["total"] == 4
        assert final_history["items"][0]["action"] == "temporary_password_issued"
        assert final_history["items"][0]["changes"] == []
        assert_audit_is_sanitized(final_history)
    finally:
        await cleanup(user_ids)


if __name__ == "__main__":
    asyncio.run(run())
    print(
        "Admin user audit smoke OK: auth, create, before/after, no-op, "
        "capability implication, failed update, rollback, privacy, role guard, "
        "and trusted actor."
    )
