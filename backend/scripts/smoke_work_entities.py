"""Local API smoke for projects, goals, typed links, and access boundaries."""
import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete

from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.personal_task import PersonalTask
from app.models.user import League, User, UserRole


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")


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
        raise AssertionError(f"{label}: expected HTTP {expected}, got {status}: {payload}")
    return payload


async def create_fixtures() -> dict[str, Any]:
    marker = f"{int(time.time())}"
    async with AsyncSessionLocal() as db:
        users = {
            name: User(
                full_name=f"Entity smoke {name}",
                email=f"entity-smoke-{name}-{marker}@example.invalid",
                league=League.C,
                role=UserRole.executor,
                task_workspace_enabled=True,
                is_active=True,
            )
            for name in ("owner", "editor", "viewer", "outsider")
        }
        db.add_all(users.values())
        await db.flush()
        db.add_all(
            [
                Contact(
                    requester_id=users["owner"].id,
                    recipient_id=users["editor"].id,
                    status="accepted",
                ),
                Contact(
                    requester_id=users["owner"].id,
                    recipient_id=users["viewer"].id,
                    status="accepted",
                ),
            ]
        )
        owner_task = PersonalTask(owner_id=users["owner"].id, title="Owner private task")
        done_task = PersonalTask(
            owner_id=users["owner"].id,
            title="Owner completed task",
            status="done",
            due_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        archived_task = PersonalTask(
            owner_id=users["owner"].id,
            title="Owner archived task",
            status="archived",
            due_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        outsider_task = PersonalTask(
            owner_id=users["outsider"].id,
            title="Outsider private task",
        )
        db.add_all([owner_task, done_task, archived_task, outsider_task])
        await db.commit()
        return {
            "user_ids": [user.id for user in users.values()],
            "tokens": {
                name: create_access_token({"sub": str(user.id), "ver": user.auth_version})
                for name, user in users.items()
            },
            "users": users,
            "owner_task_id": owner_task.id,
            "done_task_id": done_task.id,
            "archived_task_id": archived_task.id,
            "outsider_task_id": outsider_task.id,
        }


async def cleanup(user_ids: list[UUID]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def run() -> None:
    fixtures = await create_fixtures()
    tokens = fixtures["tokens"]
    try:
        status, entity = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Entity graph smoke",
                "status": "draft",
            },
        )
        entity = expect(status, 201, entity, "create entity")
        entity_id = entity["id"]
        assert entity["visibility"] == "private"
        assert entity["access_role"] == "owner"

        status, payload = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["outsider"],
        )
        expect(status, 404, payload, "private entity isolation")

        created_members: dict[str, Any] = {}
        for role_name, member_role in (("editor", "editor"), ("viewer", "viewer")):
            status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/members",
                tokens["owner"],
                {
                    "user_id": str(fixtures["users"][role_name].id),
                    "role": member_role,
                },
            )
            created_members[role_name] = expect(
                status,
                201,
                payload,
                f"add {member_role}",
            )

        status, shared_entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["viewer"],
        )
        shared_entity = expect(status, 200, shared_entity, "viewer reads shared entity")
        assert shared_entity["owner_email"] is None

        status, owner_members = request(
            "GET",
            f"/api/work-entities/{entity_id}/members",
            tokens["owner"],
        )
        owner_members = expect(status, 200, owner_members, "owner reads member emails")
        assert all(member["user_email"] for member in owner_members)

        status, viewer_members = request(
            "GET",
            f"/api/work-entities/{entity_id}/members",
            tokens["viewer"],
        )
        viewer_members = expect(status, 200, viewer_members, "viewer reads members")
        visible_email_ids = {
            member["user_id"]
            for member in viewer_members
            if member["user_email"] is not None
        }
        assert visible_email_ids == {str(fixtures["users"]["viewer"].id)}

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["editor"],
            {"description": "Edited by accepted contact"},
        )
        expect(status, 200, payload, "editor can edit")

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["editor"],
            {"visibility": "private"},
        )
        expect(status, 403, payload, "editor cannot change access")

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["editor"],
            {"status": "archived"},
        )
        expect(status, 403, payload, "editor cannot archive")

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["viewer"],
            {"description": "Viewer must not edit"},
        )
        expect(status, 403, payload, "viewer cannot edit")

        status, link = request(
            "POST",
            f"/api/work-entities/{entity_id}/links",
            tokens["owner"],
            {
                "target_type": "personal_task",
                "target_id": str(fixtures["owner_task_id"]),
                "relation_type": "contains",
            },
        )
        link = expect(status, 201, link, "link owner personal task")
        assert link["target_accessible"] is True

        for fixture_key, label in (
            ("done_task_id", "link completed personal task"),
            ("archived_task_id", "link archived personal task"),
        ):
            status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/links",
                tokens["owner"],
                {
                    "target_type": "personal_task",
                    "target_id": str(fixtures[fixture_key]),
                    "relation_type": "contains",
                },
            )
            expect(status, 201, payload, label)

        status, owner_summary = request(
            "GET",
            f"/api/work-entities/{entity_id}/summary",
            tokens["owner"],
        )
        owner_summary = expect(status, 200, owner_summary, "terminal status summary")
        assert owner_summary["work_items_total"] == 2
        assert owner_summary["work_items_done"] == 1
        assert owner_summary["overdue_items"] == 0
        assert owner_summary["next_due_at"] is None

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/links",
            tokens["owner"],
            {
                "target_type": "personal_task",
                "target_id": str(fixtures["outsider_task_id"]),
                "relation_type": "related",
            },
        )
        expect(status, 404, payload, "cannot link inaccessible target")

        status, editor_links = request(
            "GET",
            f"/api/work-entities/{entity_id}/links",
            tokens["editor"],
        )
        editor_links = expect(status, 200, editor_links, "editor reads links")
        assert len(editor_links) == 3
        assert all(item["target_accessible"] is False for item in editor_links)
        assert all(item["target_id"] is None for item in editor_links)
        assert all(item["target_title"] is None for item in editor_links)

        status, editor_summary = request(
            "GET",
            f"/api/work-entities/{entity_id}/summary",
            tokens["editor"],
        )
        editor_summary = expect(status, 200, editor_summary, "restricted summary")
        assert editor_summary["accessible_links"] == 0
        assert editor_summary["restricted_links"] == 3

        status, second_entity = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "goal",
                "title": "Entity graph cycle target",
            },
        )
        second_entity = expect(status, 201, second_entity, "create second entity")
        second_id = second_entity["id"]

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/links",
            tokens["owner"],
            {
                "target_type": "entity",
                "target_id": second_id,
                "relation_type": "contributes_to",
            },
        )
        expect(status, 201, payload, "create structural entity link")

        status, payload = request(
            "POST",
            f"/api/work-entities/{second_id}/links",
            tokens["owner"],
            {
                "target_type": "entity",
                "target_id": entity_id,
                "relation_type": "contains",
            },
        )
        expect(status, 409, payload, "reject structural cycle")

        concurrent_entities: list[str] = []
        for title in ("Concurrent graph A", "Concurrent graph B"):
            status, payload = request(
                "POST",
                "/api/work-entities",
                tokens["owner"],
                {"entity_type": "goal", "title": title},
            )
            concurrent_entities.append(expect(status, 201, payload, title)["id"])

        def create_concurrent_link(source_id: str, target_id: str) -> tuple[int, Any]:
            return request(
                "POST",
                f"/api/work-entities/{source_id}/links",
                tokens["owner"],
                {
                    "target_type": "entity",
                    "target_id": target_id,
                    "relation_type": "depends_on",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    create_concurrent_link,
                    concurrent_entities[0],
                    concurrent_entities[1],
                ),
                executor.submit(
                    create_concurrent_link,
                    concurrent_entities[1],
                    concurrent_entities[0],
                ),
            ]
            concurrent_results = [future.result(timeout=15) for future in futures]
        assert sorted(status for status, _ in concurrent_results) == [201, 409]

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/links",
            tokens["owner"],
            {
                "target_type": "entity",
                "target_id": entity_id,
                "relation_type": "related",
            },
        )
        expect(status, 400, payload, "reject self link")

        status, backlinks = request(
            "GET",
            "/api/work-entities/links/by-target"
            f"?target_type=personal_task&target_id={fixtures['owner_task_id']}",
            tokens["owner"],
        )
        backlinks = expect(status, 200, backlinks, "reverse link")
        assert any(item["entity_id"] == entity_id for item in backlinks)

        status, events = request(
            "GET",
            f"/api/work-entities/{entity_id}/events",
            tokens["viewer"],
        )
        events = expect(status, 200, events, "viewer audit")
        assert all("target_id" not in (event.get("payload") or {}) for event in events)
        assert all(
            not any("email" in key.lower() for key in (event.get("payload") or {}))
            for event in events
        )

        for role_name in ("editor", "viewer"):
            status, payload = request(
                "DELETE",
                f"/api/work-entities/{entity_id}/members/{created_members[role_name]['id']}",
                tokens["owner"],
            )
            expect(status, 204, payload, f"remove {role_name}")
        status, private_again = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        private_again = expect(status, 200, private_again, "private after last member")
        assert private_again["visibility"] == "private"

        print("Work entities smoke OK: access, privacy, links, cycles, summary, audit")
    finally:
        await cleanup(fixtures["user_ids"])


if __name__ == "__main__":
    asyncio.run(run())
