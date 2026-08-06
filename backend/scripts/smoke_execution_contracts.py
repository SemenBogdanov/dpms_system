"""Local API smoke for project operation to global Q execution contracts."""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.catalog import Complexity
from app.models.contact import Contact
from app.models.task import Task, TaskPriority, TaskStatus, TaskType
from app.models.user import League, User, UserRole
from app.models.work_entity import WorkEntity


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Execution contract smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Execution contract smoke refuses a non-local database")


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


def iso(value: datetime) -> str:
    return value.isoformat()


async def create_fixtures() -> dict[str, Any]:
    marker = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    async with AsyncSessionLocal() as db:
        owner = User(
            full_name="Contract smoke owner",
            email=f"contract-smoke-owner-{marker}@example.invalid",
            league=League.A,
            role=UserRole.executor,
            mpw=0,
            task_workspace_enabled=True,
            can_link_queue_tasks_to_projects=True,
            is_active=True,
        )
        editor = User(
            full_name="Contract smoke editor",
            email=f"contract-smoke-editor-{marker}@example.invalid",
            league=League.B,
            role=UserRole.executor,
            mpw=0,
            task_workspace_enabled=True,
            can_link_queue_tasks_to_projects=False,
            is_active=True,
        )
        assignee = User(
            full_name="Contract smoke assignee",
            email=f"contract-smoke-assignee-{marker}@example.invalid",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            task_workspace_enabled=True,
            can_link_queue_tasks_to_projects=False,
            is_active=True,
        )
        db.add_all([owner, editor, assignee])
        await db.flush()
        db.add_all(
            [
                Contact(
                    requester_id=owner.id,
                    recipient_id=editor.id,
                    status="accepted",
                ),
                Contact(
                    requester_id=owner.id,
                    recipient_id=assignee.id,
                    status="accepted",
                ),
            ]
        )
        existing_task = Task(
            title="Existing Q task for execution contract smoke",
            description="An eligible unassigned task with a fixed due date.",
            task_type=TaskType.docs,
            complexity=Complexity.S,
            estimated_q=Decimal("2.0"),
            priority=TaskPriority.medium,
            status=TaskStatus.in_queue,
            min_league=League.C,
            estimator_id=owner.id,
            acceptance_owner_id=owner.id,
            acceptance_mode="full",
            due_date=now + timedelta(days=15),
            tags=["contract-smoke"],
        )
        db.add(existing_task)
        await db.commit()
        users = {"owner": owner, "editor": editor, "assignee": assignee}
        return {
            "users": users,
            "user_ids": [item.id for item in users.values()],
            "tokens": {
                name: create_access_token(
                    {"sub": str(item.id), "ver": item.auth_version}
                )
                for name, item in users.items()
            },
            "existing_task_id": existing_task.id,
        }


async def cleanup(user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ActivityEvent).where(ActivityEvent.actor_id.in_(user_ids))
        )
        await db.execute(
            delete(WorkEntity).where(WorkEntity.owner_id.in_(user_ids))
        )
        await db.execute(delete(Task).where(Task.estimator_id.in_(user_ids)))
        await db.execute(
            delete(Contact).where(
                (Contact.requester_id.in_(user_ids))
                | (Contact.recipient_id.in_(user_ids))
            )
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def assign_and_start(task_id: uuid.UUID, assignee_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                assignee_id=assignee_id,
                status=TaskStatus.in_progress,
                started_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def set_task_status(task_id: uuid.UUID, status: TaskStatus) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Task).where(Task.id == task_id).values(status=status)
        )
        await db.commit()


async def task_status(task_id: uuid.UUID) -> TaskStatus:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Task.status).where(Task.id == task_id))
        ).scalar_one()


async def run() -> None:
    ensure_safe_target()
    fixtures = await create_fixtures()
    tokens = fixtures["tokens"]
    users = fixtures["users"]
    existing_task_id = fixtures["existing_task_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    starts_at = now + timedelta(days=1)
    due_at = now + timedelta(days=30)

    try:
        status, entity = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Execution contract smoke project",
                "status": "draft",
                "outcome_statement": "One operation has one explicit Q executor.",
                "success_criteria": "No duplicate execution or acceptance.",
                "starts_at": iso(starts_at),
                "due_at": iso(due_at),
                "planning_mode": "free",
            },
        )
        entity = expect(status, 201, entity, "create project")
        entity_id = entity["id"]

        for name, role in (("editor", "editor"), ("assignee", "participant")):
            status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/members",
                tokens["owner"],
                {"user_id": str(users[name].id), "role": role},
            )
            expect(status, 201, payload, f"add {role}")

        status, milestone = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Q delivery accepted",
                "criticality": "control",
                "acceptance_criteria": "The requested outcome is accepted.",
                "decision_owner_id": str(users["owner"].id),
                "baseline_at": iso(now + timedelta(days=20)),
            },
        )
        milestone = expect(status, 201, milestone, "create milestone")

        async def create_operation(title: str) -> dict[str, Any]:
            response_status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/tasks",
                tokens["owner"],
                {
                    "title": title,
                    "acceptance_criteria": "A verifiable result is supplied.",
                    "assignee_id": str(users["editor"].id),
                    "baseline_starts_at": iso(now + timedelta(days=2)),
                    "baseline_due_at": iso(now + timedelta(days=10)),
                    "target_milestone_id": milestone["id"],
                },
            )
            return expect(response_status, 201, payload, f"create operation {title}")

        operation_one = await create_operation("Link an existing Q task")
        options_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_one['id']}"
            "/execution-contract-options"
        )
        status, payload = request("GET", options_path, tokens["editor"])
        expect(status, 403, payload, "editor without capability cannot manage contract")
        status, payload = request("GET", options_path, tokens["owner"])
        payload = expect(status, 409, payload, "draft project cannot list Q tasks")
        assert payload["detail"]["code"] == "project_not_active_for_q_publication"

        link_key = str(uuid.uuid4())
        link_body = {
            "mode": "link",
            "idempotency_key": link_key,
            "task_id": str(existing_task_id),
        }
        contract_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_one['id']}"
            "/execution-contract"
        )
        status, payload = request("POST", contract_path, tokens["owner"], link_body)
        payload = expect(status, 409, payload, "draft project cannot publish Q task")
        assert payload["detail"]["code"] == "project_not_active_for_q_publication"

        status, activated = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
            {"status": "active"},
        )
        activated = expect(status, 200, activated, "activate project baseline")
        assert activated["status"] == "active"
        assert activated["baseline_locked_at"] is not None

        status, options = request("GET", options_path, tokens["owner"])
        options = expect(status, 200, options, "active project lists Q tasks")
        assert any(item["task_id"] == str(existing_task_id) for item in options)

        status, current = request("GET", contract_path, tokens["assignee"])
        current = expect(status, 200, current, "participant reads empty contract")
        assert current is None
        status, linked = request("POST", contract_path, tokens["owner"], link_body)
        linked = expect(status, 201, linked, "link existing Q task")
        assert linked["source"] == "linked_existing"
        assert linked["task_id"] == str(existing_task_id)

        status, current = request("GET", contract_path, tokens["editor"])
        current = expect(status, 200, current, "editor reads live contract")
        assert current["id"] == linked["id"]
        assert current["can_release"] is False

        status, replay = request("POST", contract_path, tokens["owner"], link_body)
        replay = expect(status, 201, replay, "idempotent link replay")
        assert replay["id"] == linked["id"]

        status, workspace = request(
            "GET",
            f"/api/work-entities/{entity_id}/workspace",
            tokens["owner"],
        )
        workspace = expect(status, 200, workspace, "workspace contract projection")
        projected = next(
            item for item in workspace["tasks"] if item["id"] == operation_one["id"]
        )
        assert projected["can_manage_execution_contract"] is True
        assert projected["execution_contract"]["id"] == linked["id"]

        operation_two = await create_operation("Reject duplicate execution")
        duplicate_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_two['id']}"
            "/execution-contract"
        )
        status, payload = request(
            "POST",
            duplicate_path,
            tokens["owner"],
            link_body,
        )
        expect(
            status,
            409,
            payload,
            "idempotency key cannot replay another operation contract",
        )
        status, payload = request(
            "POST",
            duplicate_path,
            tokens["owner"],
            {
                "mode": "link",
                "idempotency_key": str(uuid.uuid4()),
                "task_id": str(existing_task_id),
            },
        )
        expect(status, 409, payload, "one Q task cannot execute two operations")

        status, released = request(
            "PATCH",
            contract_path,
            tokens["owner"],
            {"reason": "The project chose a different execution route."},
        )
        released = expect(status, 200, released, "release linked contract")
        assert released["status"] == "released"
        assert await task_status(existing_task_id) == TaskStatus.in_queue
        status, current = request("GET", contract_path, tokens["owner"])
        current = expect(status, 200, current, "released contract leaves active scope")
        assert current is None

        operation_three = await create_operation("Publish a criteria-based Q task")
        publish_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_three['id']}"
            "/execution-contract"
        )
        publish_body = {
            "mode": "publish",
            "idempotency_key": str(uuid.uuid4()),
            "title": "Prepare the project delivery package",
            "description": "Deliver two independently verifiable outcomes.",
            "task_type": "docs",
            "complexity": "M",
            "estimated_q": 5,
            "priority": "medium",
            "min_league": "C",
            "due_date": iso(now + timedelta(days=12)),
            "tags": ["project", "contract-smoke"],
            "acceptance_mode": "criteria",
            "acceptance_criteria": [
                {"title": "Package is assembled", "kind": "required"},
                {"title": "Package is delivered", "kind": "quality_gate"},
            ],
        }
        status, published = request(
            "POST", publish_path, tokens["owner"], publish_body
        )
        published = expect(status, 201, published, "publish operation to Q pool")
        assert published["source"] == "created_from_operation"
        assert Decimal(str(published["estimated_q"])) == Decimal("5")
        assert published["acceptance_required_count"] == 2

        status, publish_replay = request(
            "POST", publish_path, tokens["owner"], publish_body
        )
        publish_replay = expect(status, 201, publish_replay, "idempotent publish replay")
        assert publish_replay["id"] == published["id"]

        operation_four = await create_operation("Started Q task cannot be released")
        started_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_four['id']}"
            "/execution-contract"
        )
        started_body = {
            **publish_body,
            "idempotency_key": str(uuid.uuid4()),
            "title": "Started execution contract task",
            "acceptance_mode": "full",
            "acceptance_criteria": [],
        }
        status, started = request(
            "POST", started_path, tokens["owner"], started_body
        )
        started = expect(status, 201, started, "publish task that will start")
        await assign_and_start(uuid.UUID(started["task_id"]), users["assignee"].id)
        status, payload = request(
            "PATCH",
            started_path,
            tokens["owner"],
            {"reason": "This release must be rejected after work starts."},
        )
        expect(status, 409, payload, "started contract cannot be released")

        operation_five = await create_operation("Cancelled Q task can be released")
        cancelled_path = (
            f"/api/work-entities/{entity_id}/tasks/{operation_five['id']}"
            "/execution-contract"
        )
        cancelled_body = {
            **started_body,
            "idempotency_key": str(uuid.uuid4()),
            "title": "Cancelled pre-start execution task",
        }
        status, cancelled = request(
            "POST", cancelled_path, tokens["owner"], cancelled_body
        )
        cancelled = expect(status, 201, cancelled, "publish task that will cancel")
        cancelled_task_id = uuid.UUID(cancelled["task_id"])
        await set_task_status(cancelled_task_id, TaskStatus.cancelled)
        status, released_cancelled = request(
            "PATCH",
            cancelled_path,
            tokens["owner"],
            {"reason": "The cancelled pre-start task must not lock the operation."},
        )
        released_cancelled = expect(
            status,
            200,
            released_cancelled,
            "cancelled pre-start contract can be released",
        )
        assert released_cancelled["status"] == "released"
        assert await task_status(cancelled_task_id) == TaskStatus.cancelled

        status, events = request(
            "GET",
            f"/api/work-entities/{entity_id}/events",
            tokens["owner"],
        )
        events = expect(status, 200, events, "execution contract project history")
        event_types = {item["event_type"] for item in events}
        assert {
            "execution_contract_linked",
            "execution_contract_published",
            "execution_contract_released",
        }.issubset(event_types)
        published_event = next(
            item for item in events if item["event_type"] == "execution_contract_published"
        )
        assert published_event["object_type"] == "task"
        assert published_event["object_ref"].startswith("PRJ-")
        assert published_event["payload"]["impact"]["q_task_number"]
        assert published_event["payload"]["impact"]["estimated_q"] == 5.0
        released_event = next(
            item for item in events if item["event_type"] == "execution_contract_released"
        )
        assert released_event["reason"]
        assert released_event["payload"]["impact"]["q_task_number"]

        print(
            "Execution contract smoke OK: capability gate, options, link, publish, "
            "draft publication gate, baseline activation, idempotency, one-to-one "
            "protection, workspace projection, release, "
            "started-task guard, cancelled-task recovery, acceptance snapshot, "
            "live contract refresh, viewer projection, and project history"
        )
    finally:
        await cleanup(fixtures["user_ids"])


if __name__ == "__main__":
    asyncio.run(run())
