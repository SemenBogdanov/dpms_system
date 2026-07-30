"""Local multi-user API smoke for the redesigned project workspace."""
import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, update

from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.user import League, User, UserRole
from app.models.work_entity import WorkEntity, WorkEntityMilestone, WorkEntityTask
from app.schemas.work_entity import (
    WorkEntityArtifactUpdate,
    WorkEntityLinkUpdate,
    WorkEntityMilestoneUpdate,
    WorkEntityStageUpdate,
    WorkEntityTaskUpdate,
    WorkEntityUpdate,
)


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


def verify_patch_null_guards() -> None:
    cases = {
        WorkEntityUpdate: {
            "entity_type",
            "title",
            "status",
            "visibility",
            "planning_mode",
            "tags",
        },
        WorkEntityLinkUpdate: {"relation_type", "position"},
        WorkEntityStageUpdate: {"title", "status", "position"},
        WorkEntityTaskUpdate: {"title", "status", "priority", "position"},
        WorkEntityMilestoneUpdate: {
            "title",
            "status",
            "criticality",
            "acceptance_criteria",
            "position",
        },
        WorkEntityArtifactUpdate: {"artifact_type", "title", "status"},
    }
    for schema, fields in cases.items():
        for field in fields:
            try:
                schema.model_validate({field: None})
            except ValidationError:
                continue
            raise AssertionError(
                f"{schema.__name__} accepted null for required field {field}"
            )


async def create_fixtures() -> dict[str, Any]:
    marker = str(int(time.time()))
    async with AsyncSessionLocal() as db:
        users = {
            name: User(
                full_name=f"Schedule smoke {name}",
                email=f"schedule-smoke-{name}-{marker}@example.invalid",
                league=League.C,
                role=UserRole.executor,
                task_workspace_enabled=True,
                is_active=True,
            )
            for name in ("owner", "editor", "participant", "viewer", "outsider")
        }
        db.add_all(users.values())
        await db.flush()
        db.add_all(
            Contact(
                requester_id=users["owner"].id,
                recipient_id=users[name].id,
                status="accepted",
            )
            for name in ("editor", "participant", "viewer", "outsider")
        )
        await db.commit()
        return {
            "users": users,
            "user_ids": [user.id for user in users.values()],
            "tokens": {
                name: create_access_token(
                    {"sub": str(user.id), "ver": user.auth_version}
                )
                for name, user in users.items()
            },
        }


async def cleanup(user_ids: list[UUID]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(WorkEntity).where(WorkEntity.owner_id.in_(user_ids))
        )
        await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def force_inconsistent_started_task(task_id: UUID) -> None:
    """Simulate imported legacy data that violates current dependency gating."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(WorkEntityTask)
            .where(WorkEntityTask.id == task_id)
            .values(
                status="in_progress",
                actual_starts_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def force_legacy_cancelled_target(
    milestone_id: UUID,
    *,
    cancelled: bool,
) -> None:
    """Simulate a pre-hardening route to a cancelled checkpoint."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(WorkEntityMilestone)
            .where(WorkEntityMilestone.id == milestone_id)
            .values(
                status="cancelled" if cancelled else "planned",
                actual_at=None,
                cancelled_at=datetime.now(timezone.utc) if cancelled else None,
            )
        )
        await db.commit()


def iso(value: datetime) -> str:
    return value.isoformat()


def parsed(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def run() -> None:
    verify_patch_null_guards()
    fixtures = await create_fixtures()
    users = fixtures["users"]
    tokens = fixtures["tokens"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    project_start = now + timedelta(days=1)
    project_due = now + timedelta(days=30)
    try:
        status, payload = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Invalid active project",
                "status": "active",
            },
        )
        expect(status, 400, payload, "new project must start as draft")

        status, methodology_entity = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Malformed methodology project",
                "status": "draft",
                "starts_at": iso(project_start),
                "due_at": iso(project_due),
                "planning_mode": "methodology",
                "methodology_title": "Broken import",
                "methodology_version": "1.0",
                "methodology_snapshot": {"schemaVersion": 1, "stages": []},
            },
        )
        methodology_entity = expect(
            status,
            201,
            methodology_entity,
            "create malformed methodology draft",
        )
        status, methodology_readiness = request(
            "GET",
            f"/api/work-entities/{methodology_entity['id']}/readiness",
            tokens["owner"],
        )
        methodology_readiness = expect(
            status,
            200,
            methodology_readiness,
            "validate malformed methodology snapshot",
        )
        assert any(
            issue["code"] == "methodology_snapshot_invalid"
            for issue in methodology_readiness["issues"]
        )

        methodology_snapshot = {
            "schemaVersion": 1,
            "version": "1.0",
            "stages": [{"id": "discovery", "title": "Discovery"}],
        }
        status, methodology_projection = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Methodology projection smoke",
                "status": "draft",
                "starts_at": iso(project_start),
                "due_at": iso(project_due),
                "planning_mode": "methodology",
                "methodology_title": "Projection test",
                "methodology_version": "1.0",
                "methodology_snapshot": methodology_snapshot,
            },
        )
        methodology_projection = expect(
            status,
            201,
            methodology_projection,
            "create methodology projection draft",
        )
        status, payload = request(
            "POST",
            f"/api/work-entities/{methodology_projection['id']}/stages",
            tokens["owner"],
            {
                "title": "Unrelated stage",
                "completion_criteria": "Explicit result.",
                "source_type": "methodology",
                "source_key": "unrelated",
                "source_snapshot": {
                    "id": "unrelated",
                    "title": "Unrelated stage",
                },
            },
        )
        expect(status, 201, payload, "create mismatched methodology stage")
        status, methodology_readiness = request(
            "GET",
            f"/api/work-entities/{methodology_projection['id']}/readiness",
            tokens["owner"],
        )
        methodology_readiness = expect(
            status,
            200,
            methodology_readiness,
            "validate methodology stage projection",
        )
        assert any(
            issue["code"] == "stage_source_key_mismatch"
            for issue in methodology_readiness["issues"]
        )

        status, entity = request(
            "POST",
            "/api/work-entities",
            tokens["owner"],
            {
                "entity_type": "project",
                "title": "Controlled schedule smoke",
                "status": "draft",
                "outcome_statement": "Controlled package is accepted and published.",
                "success_criteria": "All planned decisions are recorded and work is accepted.",
                "starts_at": iso(project_start),
                "due_at": iso(project_due),
                "planning_mode": "free",
            },
        )
        entity = expect(status, 201, entity, "create project")
        entity_id = entity["id"]
        assert parsed(entity["forecast_due_at"]) == project_due
        assert entity["baseline_locked_at"] is None
        assert entity["schedule_revision"] == 0
        status, entity = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
            {"due_at": iso(project_due + timedelta(days=1))},
        )
        entity = expect(status, 200, entity, "change draft project boundary")
        assert entity["schedule_revision"] == 1
        status, entity = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
            {"due_at": iso(project_due)},
        )
        entity = expect(status, 200, entity, "restore draft project boundary")
        assert entity["schedule_revision"] == 2
        status, readiness = request(
            "GET",
            f"/api/work-entities/{entity_id}/readiness",
            tokens["owner"],
        )
        readiness = expect(status, 200, readiness, "empty draft readiness")
        assert not readiness["can_activate"]
        readiness_codes = {issue["code"] for issue in readiness["issues"]}
        assert "project_work_missing" in readiness_codes
        assert "project_milestones_missing" in readiness_codes
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
            {"status": "active"},
        )
        expect(status, 409, payload, "empty draft activation blocked")

        for name, role in (
            ("editor", "editor"),
            ("participant", "participant"),
            ("viewer", "viewer"),
        ):
            status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/members",
                tokens["owner"],
                {"user_id": str(users[name].id), "role": role},
            )
            expect(status, 201, payload, f"add {role}")

        for name in ("owner", "editor", "participant", "viewer"):
            status, workspace = request(
                "GET",
                f"/api/work-entities/{entity_id}/workspace",
                tokens[name],
            )
            workspace = expect(status, 200, workspace, f"{name} reads workspace")
            assert workspace["current_access_role"] == name
            assert {
                "stages",
                "tasks",
                "milestones",
                "dependencies",
                "artifacts",
            }.issubset(workspace)
        status, payload = request(
            "GET",
            f"/api/work-entities/{entity_id}/workspace",
            tokens["outsider"],
        )
        expect(status, 404, payload, "outsider isolation")

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/stages",
            tokens["viewer"],
            {"title": "Viewer stage"},
        )
        expect(status, 403, payload, "viewer cannot plan")

        status, stage = request(
            "POST",
            f"/api/work-entities/{entity_id}/stages",
            tokens["owner"],
            {
                "title": "Delivery",
                "description": "A methodology-neutral stage.",
                "completion_criteria": "Release decision recorded.",
                "guidance": "Keep deliverables and decisions explicit.",
            },
        )
        stage = expect(status, 201, stage, "create stage")

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Invalid key milestone",
                "criticality": "key",
                "acceptance_criteria": "Decision recorded",
                "baseline_at": iso(now + timedelta(days=5)),
            },
        )
        expect(status, 422, payload, "key milestone needs rationale")

        status, gate = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Architecture approved",
                "description": "Formal decision point, not executable work.",
                "criticality": "key",
                "criticality_reason": "Opens implementation work.",
                "acceptance_criteria": "Decision protocol is signed.",
                "decision_owner_id": str(users["editor"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=5)),
            },
        )
        gate = expect(status, 201, gate, "create milestone")
        assert "baseline_at" in gate and "forecast_at" in gate
        assert "starts_at" not in gate and "assignee_id" not in gate
        assert gate["display_status"] == "planned"

        status, delivery = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Delivery accepted",
                "criticality": "control",
                "acceptance_criteria": "Acceptance suite result is approved.",
                "decision_owner_id": str(users["owner"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=11)),
            },
        )
        delivery = expect(status, 201, delivery, "create delivery milestone")

        status, task = request(
            "POST",
            f"/api/work-entities/{entity_id}/tasks",
            tokens["editor"],
            {
                "title": "Implement delivery",
                "assignee_id": str(users["participant"].id),
                "stage_id": stage["id"],
                "acceptance_criteria": "Acceptance suite is green.",
                "baseline_starts_at": iso(now + timedelta(days=6)),
                "baseline_due_at": iso(now + timedelta(days=10)),
                "target_milestone_id": delivery["id"],
            },
        )
        task = expect(status, 201, task, "create task")
        assert "item_type" not in task
        assert task["baseline_due_at"] == task["forecast_due_at"]
        assert task["target_milestone_id"] == delivery["id"]

        status, workspace = request(
            "GET",
            f"/api/work-entities/{entity_id}/workspace",
            tokens["owner"],
        )
        workspace = expect(status, 200, workspace, "read target dependency")
        target_dependency = next(
            item
            for item in workspace["dependencies"]
            if item["predecessor_type"] == "task"
            and item["predecessor_id"] == task["id"]
            and item["successor_type"] == "milestone"
            and item["successor_id"] == delivery["id"]
        )
        status, payload = request(
            "DELETE",
            (
                f"/api/work-entities/{entity_id}/dependencies/"
                f"{target_dependency['id']}"
            ),
            tokens["owner"],
        )
        expect(status, 409, payload, "last task target cannot be deleted")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/milestones/{delivery['id']}",
            tokens["owner"],
            {
                "status": "cancelled",
                "change_reason": "Verify route integrity.",
            },
        )
        expect(status, 409, payload, "linked target cannot be cancelled")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{task['id']}",
            tokens["owner"],
            {"status": "cancelled"},
        )
        expect(status, 200, payload, "cancel task before target")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/milestones/{delivery['id']}",
            tokens["owner"],
            {
                "status": "cancelled",
                "change_reason": "Target is no longer required.",
            },
        )
        expect(status, 200, payload, "cancel target after task")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{task['id']}",
            tokens["owner"],
            {"status": "planned"},
        )
        expect(status, 409, payload, "cancelled target blocks task reopen")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/milestones/{delivery['id']}",
            tokens["owner"],
            {
                "status": "planned",
                "change_reason": "Restore the target route.",
            },
        )
        expect(status, 200, payload, "restore target before task")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{task['id']}",
            tokens["owner"],
            {"status": "planned"},
        )
        task = expect(status, 200, payload, "reopen task with planned target")
        await force_legacy_cancelled_target(
            UUID(delivery["id"]),
            cancelled=True,
        )
        status, readiness = request(
            "GET",
            f"/api/work-entities/{entity_id}/readiness",
            tokens["owner"],
        )
        readiness = expect(
            status,
            200,
            readiness,
            "legacy cancelled target readiness",
        )
        assert any(
            issue["code"] == "task_milestone_missing"
            and issue["scope_id"] == task["id"]
            for issue in readiness["issues"]
        )
        await force_legacy_cancelled_target(
            UUID(delivery["id"]),
            cancelled=False,
        )

        status, dependency = request(
            "POST",
            f"/api/work-entities/{entity_id}/dependencies",
            tokens["owner"],
            {
                "predecessor_type": "milestone",
                "predecessor_id": gate["id"],
                "successor_type": "task",
                "successor_id": task["id"],
                "lag_days": 1,
            },
        )
        dependency = expect(status, 201, dependency, "milestone to task dependency")

        status, readiness = request(
            "GET",
            f"/api/work-entities/{entity_id}/readiness",
            tokens["owner"],
        )
        readiness = expect(status, 200, readiness, "completed draft readiness")
        assert readiness["can_activate"], readiness
        assert readiness["blocking_count"] == 0
        status, entity = request(
            "PATCH",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
            {"status": "active"},
        )
        entity = expect(status, 200, entity, "activate ready project")
        assert entity["baseline_locked_at"] is not None

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{task['id']}",
            tokens["participant"],
            {"status": "in_progress"},
        )
        expect(status, 409, payload, "milestone blocks task")

        status, gate = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/milestones/{gate['id']}",
            tokens["editor"],
            {"status": "achieved", "change_reason": "Protocol signed."},
        )
        gate = expect(status, 200, gate, "achieve milestone")
        assert gate["actual_at"] is not None
        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/tasks",
            tokens["owner"],
            {
                "title": "Invalid work after checkpoint",
                "assignee_id": str(users["participant"].id),
                "stage_id": stage["id"],
                "acceptance_criteria": "Must be rejected.",
                "baseline_starts_at": iso(now + timedelta(days=2)),
                "baseline_due_at": iso(now + timedelta(days=3)),
                "target_milestone_id": gate["id"],
            },
        )
        expect(status, 409, payload, "achieved target rejects new work")

        status, task = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{task['id']}",
            tokens["participant"],
            {"status": "in_progress", "next_step": "Run acceptance suite."},
        )
        task = expect(status, 200, task, "participant starts assigned task")
        assert task["actual_starts_at"] is not None

        status, source = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Committee decision",
                "criticality": "critical",
                "criticality_reason": "External governance commitment.",
                "acceptance_criteria": "Committee protocol is approved.",
                "decision_owner_id": str(users["owner"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=12)),
            },
        )
        source = expect(status, 201, source, "create reschedule source")

        status, finish = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Package published",
                "criticality": "key",
                "criticality_reason": "Closes the delivery stage.",
                "acceptance_criteria": "Package is available to stakeholders.",
                "decision_owner_id": str(users["owner"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=17)),
            },
        )
        finish = expect(status, 201, finish, "create finish milestone")

        status, future_task = request(
            "POST",
            f"/api/work-entities/{entity_id}/tasks",
            tokens["owner"],
            {
                "title": "Publish approved package",
                "assignee_id": str(users["participant"].id),
                "stage_id": stage["id"],
                "acceptance_criteria": "Published package is accepted.",
                "baseline_starts_at": iso(now + timedelta(days=13)),
                "baseline_due_at": iso(now + timedelta(days=16)),
                "target_milestone_id": finish["id"],
            },
        )
        future_task = expect(status, 201, future_task, "create future task")

        status, future_task = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["participant"],
            {"status": "waiting", "waiting_for": "Committee decision."},
        )
        future_task = expect(status, 200, future_task, "wait before work starts")
        assert future_task["actual_starts_at"] is None
        status, future_task = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {"status": "planned"},
        )
        future_task = expect(status, 200, future_task, "return waiting task to plan")

        status, future_task = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {"assignee_id": str(users["editor"].id)},
        )
        future_task = expect(status, 200, future_task, "reassign future task")
        status, future_task = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {"assignee_id": str(users["participant"].id)},
        )
        future_task = expect(status, 200, future_task, "restore future assignee")

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/dependencies",
            tokens["owner"],
            {
                "predecessor_type": "task",
                "predecessor_id": future_task["id"],
                "successor_type": "milestone",
                "successor_id": gate["id"],
            },
        )
        expect(
            status,
            409,
            payload,
            "achieved milestone rejects incomplete predecessor",
        )

        chain_dependencies = []
        for predecessor_type, predecessor_id, successor_type, successor_id in (
            ("milestone", source["id"], "task", future_task["id"]),
        ):
            status, payload = request(
                "POST",
                f"/api/work-entities/{entity_id}/dependencies",
                tokens["owner"],
                {
                    "predecessor_type": predecessor_type,
                    "predecessor_id": predecessor_id,
                    "successor_type": successor_type,
                    "successor_id": successor_id,
                },
            )
            chain_dependencies.append(
                expect(status, 201, payload, "create schedule chain")
            )

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/dependencies",
            tokens["owner"],
            {
                "predecessor_type": "milestone",
                "predecessor_id": finish["id"],
                "successor_type": "milestone",
                "successor_id": source["id"],
            },
        )
        expect(status, 409, payload, "cycle rejected")

        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(status, 200, entity, "read schedule revision")
        reschedule_body = {
            "forecast_at": iso(now + timedelta(days=15)),
            "reason": "Committee moved the decision meeting.",
            "cascade": True,
            "expected_revision": entity["schedule_revision"],
        }
        status, preview = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/preview"
            ),
            tokens["owner"],
            reschedule_body,
        )
        preview = expect(status, 200, preview, "reschedule preview")
        assert preview["schedule_revision"] == entity["schedule_revision"]
        assert preview["conflicts"] == []
        assert {item["node_type"] for item in preview["changes"]} == {
            "task",
            "milestone",
        }
        assert len(preview["changes"]) == 3

        status, payload = request(
            "DELETE",
            (
                f"/api/work-entities/{entity_id}/dependencies/"
                f"{chain_dependencies[0]['id']}"
            ),
            tokens["owner"],
        )
        expect(status, 204, payload, "mutate graph after preview")
        status, payload = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/apply"
            ),
            tokens["owner"],
            reschedule_body,
        )
        expect(status, 409, payload, "preview invalidated by dependency change")

        status, payload = request(
            "POST",
            f"/api/work-entities/{entity_id}/dependencies",
            tokens["owner"],
            {
                "predecessor_type": "milestone",
                "predecessor_id": source["id"],
                "successor_type": "task",
                "successor_id": future_task["id"],
            },
        )
        expect(status, 201, payload, "restore schedule chain")
        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(status, 200, entity, "refresh schedule revision")
        reschedule_body["expected_revision"] = entity["schedule_revision"]
        status, preview = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/preview"
            ),
            tokens["owner"],
            reschedule_body,
        )
        preview = expect(status, 200, preview, "repeat reschedule preview")
        wrong_revision = dict(
            reschedule_body,
            expected_revision=entity["schedule_revision"] + 1,
        )
        status, payload = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/apply"
            ),
            tokens["owner"],
            wrong_revision,
        )
        expect(status, 409, payload, "stale preview rejected")

        status, applied = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/apply"
            ),
            tokens["owner"],
            reschedule_body,
        )
        applied = expect(status, 200, applied, "apply reschedule")
        assert applied["schedule_revision"] == entity["schedule_revision"] + 1

        status, workspace = request(
            "GET",
            f"/api/work-entities/{entity_id}/workspace",
            tokens["owner"],
        )
        workspace = expect(status, 200, workspace, "read shifted workspace")
        shifted_source = next(
            item for item in workspace["milestones"] if item["id"] == source["id"]
        )
        shifted_task = next(
            item for item in workspace["tasks"] if item["id"] == future_task["id"]
        )
        assert shifted_source["baseline_at"] == source["baseline_at"]
        assert shifted_source["forecast_at"] != source["forecast_at"]
        assert shifted_source["display_status"] == "rescheduled"
        assert shifted_task["baseline_due_at"] == future_task["baseline_due_at"]
        assert shifted_task["forecast_due_at"] != future_task["forecast_due_at"]

        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {
                "forecast_starts_at": iso(now + timedelta(days=31)),
                "forecast_due_at": iso(now + timedelta(days=35)),
                "change_reason": "Verify forecast roll-up extension.",
            },
        )
        expect(
            status,
            400,
            payload,
            "reject task forecast after target milestone",
        )
        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(
            status,
            200,
            entity,
            "read revision before target milestone extension",
        )
        finish_reschedule_body = {
            "forecast_at": iso(now + timedelta(days=36)),
            "reason": "Committee explicitly extended the acceptance checkpoint.",
            "cascade": True,
            "expected_revision": entity["schedule_revision"],
        }
        status, payload = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{finish['id']}/reschedule/apply"
            ),
            tokens["owner"],
            finish_reschedule_body,
        )
        expect(status, 200, payload, "extend target milestone first")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {
                "forecast_starts_at": iso(now + timedelta(days=31)),
                "forecast_due_at": iso(now + timedelta(days=35)),
                "change_reason": "Verify forecast roll-up extension.",
            },
        )
        expect(status, 200, payload, "extend latest task forecast")
        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(status, 200, entity, "read extended project forecast")
        assert parsed(entity["forecast_due_at"]) == now + timedelta(days=36), (
            entity["forecast_due_at"],
            iso(now + timedelta(days=36)),
        )
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{future_task['id']}",
            tokens["owner"],
            {
                "forecast_starts_at": iso(now + timedelta(days=21)),
                "forecast_due_at": iso(now + timedelta(days=25)),
                "change_reason": "Verify forecast roll-up contraction.",
            },
        )
        expect(status, 200, payload, "contract latest task forecast")
        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(status, 200, entity, "read contracted project forecast")
        assert parsed(entity["forecast_due_at"]) == now + timedelta(days=36)
        finish_acceleration_body = {
            "forecast_at": iso(now + timedelta(days=26)),
            "reason": "Committee confirmed the earlier acceptance checkpoint.",
            "cascade": True,
            "expected_revision": entity["schedule_revision"],
        }
        status, payload = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{finish['id']}/reschedule/apply"
            ),
            tokens["owner"],
            finish_acceleration_body,
        )
        expect(status, 200, payload, "contract target milestone after task")
        status, entity = request(
            "GET",
            f"/api/work-entities/{entity_id}",
            tokens["owner"],
        )
        entity = expect(
            status,
            200,
            entity,
            "read project forecast after target contraction",
        )
        assert parsed(entity["forecast_due_at"]) == now + timedelta(days=26)

        await force_inconsistent_started_task(UUID(future_task["id"]))

        conflict_body = {
            "forecast_at": iso(now + timedelta(days=24)),
            "reason": "Second committee shift.",
            "cascade": True,
            "expected_revision": entity["schedule_revision"],
        }
        status, conflict_preview = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/preview"
            ),
            tokens["owner"],
            conflict_body,
        )
        conflict_preview = expect(
            status,
            200,
            conflict_preview,
            "preview active-work conflict",
        )
        assert any(
            item["code"] == "work_already_started"
            for item in conflict_preview["conflicts"]
        )
        status, payload = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{source['id']}/reschedule/apply"
            ),
            tokens["owner"],
            conflict_body,
        )
        expect(status, 409, payload, "conflicted cascade not applied")

        status, artifact = request(
            "POST",
            f"/api/work-entities/{entity_id}/artifacts",
            tokens["participant"],
            {
                "artifact_type": "decision",
                "title": "Committee protocol",
                "body": "Decision and rationale.",
                "milestone_id": source["id"],
            },
        )
        artifact = expect(status, 201, artifact, "milestone artifact")
        assert artifact["milestone_id"] == source["id"]
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/artifacts/{artifact['id']}",
            tokens["participant"],
            {"body": None, "url": None},
        )
        expect(status, 400, payload, "artifact cannot lose all content")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/artifacts/{artifact['id']}",
            tokens["participant"],
            {"url": "invalid-link"},
        )
        expect(status, 400, payload, "artifact rejects invalid URL")

        status, cancelled_predecessor = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Cancelled predecessor",
                "criticality": "control",
                "acceptance_criteria": "Decision is recorded.",
                "decision_owner_id": str(users["owner"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=26)),
            },
        )
        cancelled_predecessor = expect(
            status,
            201,
            cancelled_predecessor,
            "create cancellation predecessor",
        )
        status, waiver_target = request(
            "POST",
            f"/api/work-entities/{entity_id}/milestones",
            tokens["owner"],
            {
                "title": "Exception outcome accepted",
                "criticality": "control",
                "acceptance_criteria": "Exception result is accepted.",
                "decision_owner_id": str(users["owner"].id),
                "stage_id": stage["id"],
                "baseline_at": iso(now + timedelta(days=29)),
            },
        )
        waiver_target = expect(
            status,
            201,
            waiver_target,
            "create cancellation successor target",
        )
        status, waiver_successor = request(
            "POST",
            f"/api/work-entities/{entity_id}/tasks",
            tokens["owner"],
            {
                "title": "Successor after cancellation",
                "assignee_id": str(users["participant"].id),
                "stage_id": stage["id"],
                "acceptance_criteria": "Exception decision is traceable.",
                "baseline_starts_at": iso(now + timedelta(days=27)),
                "baseline_due_at": iso(now + timedelta(days=28)),
                "target_milestone_id": waiver_target["id"],
            },
        )
        waiver_successor = expect(
            status,
            201,
            waiver_successor,
            "create cancellation successor",
        )
        status, waived_dependency = request(
            "POST",
            f"/api/work-entities/{entity_id}/dependencies",
            tokens["owner"],
            {
                "predecessor_type": "milestone",
                "predecessor_id": cancelled_predecessor["id"],
                "successor_type": "task",
                "successor_id": waiver_successor["id"],
            },
        )
        waived_dependency = expect(
            status,
            201,
            waived_dependency,
            "create cancellable dependency",
        )
        status, payload = request(
            "PATCH",
            (
                f"/api/work-entities/{entity_id}/milestones/"
                f"{cancelled_predecessor['id']}"
            ),
            tokens["owner"],
            {
                "status": "cancelled",
                "change_reason": "Governance body removed this decision.",
            },
        )
        expect(status, 200, payload, "cancel dependency predecessor")
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{waiver_successor['id']}",
            tokens["participant"],
            {"status": "in_progress"},
        )
        expect(status, 409, payload, "cancelled predecessor remains blocking")
        status, waived_dependency = request(
            "POST",
            (
                f"/api/work-entities/{entity_id}/dependencies/"
                f"{waived_dependency['id']}/waive"
            ),
            tokens["owner"],
            {
                "reason": (
                    "Committee removed the prerequisite and approved "
                    "continuing without it."
                )
            },
        )
        waived_dependency = expect(
            status,
            200,
            waived_dependency,
            "waive cancelled predecessor dependency",
        )
        assert waived_dependency["status"] == "waived"
        assert waived_dependency["waiver_reason"]
        status, payload = request(
            "PATCH",
            f"/api/work-entities/{entity_id}/tasks/{waiver_successor['id']}",
            tokens["participant"],
            {"status": "in_progress"},
        )
        expect(status, 200, payload, "waiver unblocks successor")

        status, project_map = request(
            "GET",
            f"/api/work-entities/{entity_id}/map",
            tokens["viewer"],
        )
        project_map = expect(status, 200, project_map, "read project map")
        milestone_node = next(
            node
            for node in project_map["nodes"]
            if node["id"] == f"milestone:{source['id']}"
        )
        assert milestone_node["baseline_due_at"] != milestone_node["forecast_due_at"]
        assert milestone_node["criticality"] == "critical"
        assert not any(
            edge["id"] == f"dependency:{waived_dependency['id']}"
            for edge in project_map["edges"]
        )

        status, events = request(
            "GET",
            f"/api/work-entities/{entity_id}/events?limit=300",
            tokens["owner"],
        )
        events = expect(status, 200, events, "read detailed journal")
        schedule_events = [
            event
            for event in events
            if event["event_type"] == "project_schedule_item_shifted"
            and event["reason"] == reschedule_body["reason"]
        ]
        assert len(schedule_events) == 3
        assert len({event["correlation_id"] for event in schedule_events}) == 1
        assert all(
            event["object_title"]
            and event["action"] == "forecast_shifted"
            and event["reason"]
            and event["payload"]["changes"]
            for event in schedule_events
        )
        assignee_event = next(
            event
            for event in events
            if event["event_type"] == "project_task_updated"
            and event["object_id"] == future_task["id"]
            and any(
                change["field"] == "assignee_id"
                for change in event["payload"]["changes"]
            )
        )
        assignee_change = next(
            change
            for change in assignee_event["payload"]["changes"]
            if change["field"] == "assignee_id"
        )
        assert assignee_change["from"].startswith("Schedule smoke ")
        assert assignee_change["to"].startswith("Schedule smoke ")
        assert assignee_change["from_id"] and assignee_change["to_id"]
        waiver_event = next(
            event
            for event in events
            if event["event_type"] == "project_dependency_waived"
        )
        assert waiver_event["actor_name"]
        assert waiver_event["object_title"]
        assert waiver_event["reason"]

        print(
            "Work entity workspace smoke OK: separate tasks/milestones, "
            "roles, typed dependencies, baseline/forecast, controlled "
            "cascade, conflicts, artifacts, map, and detailed journal"
        )
    finally:
        await cleanup(fixtures["user_ids"])


if __name__ == "__main__":
    asyncio.run(run())
