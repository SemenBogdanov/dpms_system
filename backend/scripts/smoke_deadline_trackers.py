#!/usr/bin/env python3
"""Local PostgreSQL/API smoke with real concurrent workers and fixture cleanup.

Run in the local backend container:
    python scripts/smoke_deadline_trackers.py --allow-local-db

No schema changes, HTTP calls, credentials, or preexisting trackers are touched.
Fixture commits are necessary to exercise independent worker transactions.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import importlib.util
from pathlib import Path
import sys
import traceback
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException, Request
import httpx
from sqlalchemy import delete, func, select, text, update

from app.api.deps import get_current_user, get_db
from app.api.routes.deadline_trackers import router
from app.database import AsyncSessionLocal, engine
from app.models.catalog import Complexity
from app.models.deadline_tracker import DeadlineTracker, DeadlineTrackerDelivery, DeadlineTrackerOccurrence, DeadlineTrackerReminder
from app.models.messages import CommunicationEvent, UserAttentionItem
from app.models.notification import Notification
from app.models.personal_task import PersonalTask
from app.models.task import Task, TaskStatus, TaskType
from app.models.user import League, User, UserRole
from app.services.deadline_tracker_schedule import sync_tracker_schedule
from app.services.deadline_tracker_calendar import occurrence_due
from app.workers.deadline_reminders import deliver_due, run_once


def require_local(allowed):
    if not allowed or engine.url.host not in {"localhost", "127.0.0.1", "::1", "db", "postgres"}:
        raise RuntimeError("local_database_guard")


async def legacy_backfill_smoke():
    """Connection-local temporary copies, rolled back; never alter public schema."""
    path = Path(__file__).resolve().parents[1] / "alembic/versions/079_deadline_tracker_organization.py"
    spec = importlib.util.spec_from_file_location("tracker_079_smoke", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    owner, personal, task = uuid4(), uuid4(), uuid4()
    identities = [uuid4() for _ in range(4)]
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text("CREATE TEMP TABLE users (id uuid PRIMARY KEY) ON COMMIT DROP"))
            for name in ("deadline_tracker_categories", "deadline_tracker_occurrences", "deadline_tracker_events", "deadline_trackers"):
                options = "INCLUDING ALL" if name == "deadline_tracker_categories" else "INCLUDING DEFAULTS"
                await connection.execute(text(f"CREATE TEMP TABLE {name} (LIKE {name} {options}) ON COMMIT DROP"))
            await connection.execute(text("INSERT INTO users(id) VALUES (:id)"), {"id": owner})
            for index, identity in enumerate(identities):
                await connection.execute(text("""
                    INSERT INTO deadline_trackers
                    (id, owner_id, title, tracker_type, status, starts_at, due_at, paused_seconds, tags,
                     personal_task_id, linked_task_id, created_at, updated_at, responsible)
                    VALUES (:id, :owner, 'Legacy retained', 'payment', 'active', now(), now() + interval '1 day',
                      0, '{}', :personal, :task, now() + :position * interval '1 second', now(), 'Legacy retained')
                """), {"id": identity, "owner": owner, "personal": personal if index < 2 else None,
                    "task": task if index != 1 else None, "position": index})
            await connection.run_sync(migration.backfill_legacy)
            rows = (await connection.execute(text("SELECT id, personal_task_id, linked_task_id, responsible, category_id FROM deadline_trackers"))).all()
            assert {row.id for row in rows} == set(identities), "legacy UUIDs preserved"
            assert sum(row.personal_task_id is not None for row in rows) == 1
            assert sum(row.linked_task_id is not None for row in rows) == 1
            assert all(row.responsible == "Legacy retained" and row.category_id is not None for row in rows)
            assert await connection.scalar(text("SELECT count(*) FROM deadline_tracker_events WHERE event_type = 'legacy_links_snapshot'")) == 4
            assert await connection.scalar(text("SELECT count(*) FROM deadline_tracker_occurrences")) == 4
            snapshot = await connection.scalar(text("SELECT details FROM deadline_tracker_events WHERE tracker_id = :id"), {"id": identities[0]})
            assert snapshot == {"personal_task_id": str(personal), "linked_task_id": str(task)}
        finally:
            await transaction.rollback()


async def smoke():
    marker = uuid4().hex
    ids = [uuid4(), uuid4(), uuid4()]
    task_ids, personal_ids, tracker_ids = [], [], []
    users = {}
    checks = []
    await legacy_backfill_smoke()
    checks.append("legacy_dual_duplicate_links_preserve_ids_backfill")
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=2)
    app = FastAPI()
    app.include_router(router, prefix="/api/deadline-trackers")

    async def fixture_user(request: Request):
        try:
            identity = UUID(request.headers.get("x-fixture-user", ""))
        except ValueError:
            raise HTTPException(401)
        if identity not in users:
            raise HTTPException(401)
        return users[identity]

    async def fixture_session():
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_current_user] = fixture_user
    app.dependency_overrides[get_db] = fixture_session
    try:
        async with AsyncSessionLocal() as db, db.begin():
            for index, identity in enumerate(ids):
                user = User(id=identity, full_name=f"Tracker smoke {index}", email=f"tracker-{marker}-{index}@example.invalid",
                    role=UserRole.executor, league=League.C, task_workspace_enabled=index < 2, is_active=True)
                db.add(user)
                users[identity] = user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            async def call(method, path, body=None, *, owner=0, expected=200):
                response = await client.request(method, f"/api/deadline-trackers{path}", json=body,
                    headers={"x-fixture-user": str(ids[owner])})
                assert response.status_code == expected, f"{method} {path}: status={response.status_code}, expected={expected}"
                return response.json()

            async def create(**extra):
                result = await call("POST", "", {"title": "Smoke tracker", "starts_at": now.isoformat(), "due_at": due.isoformat(),
                    "reminders": [{"value": 1, "unit": "hour"}], **extra})
                tracker_ids.append(UUID(result["id"]))
                return result

            group = await call("POST", "/groups", {"name": "Personal", "color": "#448866"})
            category = await call("POST", "/categories", {"name": "Classification"})
            await call("PATCH", f"/groups/{group['id']}", {"name": "Forbidden"}, owner=1, expected=404)
            await call("DELETE", f"/categories/{category['id']}", owner=1, expected=404)
            await call("POST", "", {"title": "Forbidden", "starts_at": now.isoformat(), "due_at": due.isoformat(), "group_id": group["id"]}, owner=1, expected=404)
            await call("POST", "/groups/reorder", {"ids": [group["id"], group["id"]]}, expected=422)
            await call("PATCH", f"/groups/{group['id']}", {"is_collapsed": True})
            first = await create(group_id=group["id"], category_id=category["id"])
            second = await create(title="Unrelated alerts")
            await call("PATCH", f"/categories/{category['id']}", {"is_archived": True})
            await call("DELETE", f"/groups/{group['id']}")
            detail = await call("GET", f"/{first['id']}")
            assert detail["group_id"] is None and detail["category_id"] == category["id"]
            await call("GET", f"/{first['id']}", owner=1, expected=404)
            await call("GET", f"/{first['id']}/history", owner=1, expected=404)
            await call("POST", f"/{first['id']}/alerts/read", owner=1, expected=404)
            checks.append("organization_owner_archive_delete")

            at = due - timedelta(hours=1) + timedelta(seconds=2)
            active_ids = tracker_ids.copy()
            # A worker abort after all DB writes must roll back all projections and delivery.
            async with AsyncSessionLocal() as db:
                await deliver_due(db, now=at, tracker_ids=active_ids)
                await db.rollback()
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id.in_(ids))) == 0
            counts = await asyncio.gather(
                run_once(AsyncSessionLocal, now=at, tracker_ids=active_ids),
                run_once(AsyncSessionLocal, now=at, tracker_ids=active_ids),
            )
            assert sum(counts) == 2, "concurrent delivery count"
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == ids[0])) == 2
                assert await db.scalar(select(func.count()).select_from(UserAttentionItem).where(UserAttentionItem.user_id == ids[0], UserAttentionItem.kind == "important")) == 2
            assert (await call("GET", f"/{first['id']}/alerts"))[0]["status"] == "sent"
            await call("GET", f"/{first['id']}")
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(UserAttentionItem).where(UserAttentionItem.user_id == ids[0], UserAttentionItem.is_read.is_(False))) == 1
            assert await run_once(AsyncSessionLocal, now=at, tracker_ids=active_ids) == 0
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(UserAttentionItem).where(UserAttentionItem.user_id == ids[0], UserAttentionItem.is_read.is_(False))) == 1
            checks.append("atomic_delivery_concurrent_restart_scoped_read")

            series = await create(recurrence={"frequency": "day", "timezone": "Europe/Moscow", "end_type": "count", "count": 3})
            occurrence = series["current_occurrence"]
            result = await call("POST", f"/{series['id']}/occurrences/{occurrence['id']}/complete")
            assert result["status"] == "active" and result["current_occurrence"]["sequence"] == 2
            result = await call("POST", f"/{series['id']}/finish-series")
            assert result["status"] == "done" and result["current_occurrence"] is None
            history = await call("GET", f"/{series['id']}/history")
            assert {"occurrence_completed", "series_finished"} <= {e["event_type"] for e in history}
            checks.append("recurrence_completion_history")

            annual = await create(recurrence={"frequency": "year", "timezone": "UTC"})
            result = await call("POST", f"/{annual['id']}/occurrences/{annual['current_occurrence']['id']}/complete")
            assert result["status"] == "active" and not result["series_exhausted"]
            assert result["current_occurrence"]["sequence"] == 2
            expected_next_year = occurrence_due(due, {"frequency": "year", "timezone": "UTC"}, 2)
            assert datetime.fromisoformat(result["current_occurrence"]["due_at"].replace("Z", "+00:00")) == expected_next_year
            reread = await call("GET", f"/{annual['id']}")
            assert reread["current_occurrence"]["id"] == result["current_occurrence"]["id"]
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                    DeadlineTrackerOccurrence.tracker_id == UUID(annual["id"]),
                )) == 2, "annual series must materialize only one distant frontier"
            finite = await create(recurrence={"frequency": "year", "timezone": "UTC", "end_type": "count", "count": 1})
            assert not finite["series_exhausted"]
            result = await call("POST", f"/{finite['id']}/occurrences/{finite['current_occurrence']['id']}/complete")
            assert result["status"] == "active" and result["series_exhausted"] and result["current_occurrence"] is None
            reread = await call("GET", f"/{finite['id']}")
            assert reread["series_exhausted"] and reread["current_occurrence"] is None
            listed = await call("GET", "?limit=300")
            finite_row = next(row for row in listed if row["id"] == finite["id"])
            assert finite_row["series_exhausted"] and finite_row["current_occurrence"] is None
            finished = await call("POST", f"/{finite['id']}/finish-series")
            assert finished["status"] == "done"
            checks.append("annual_frontier_and_finite_series_exhaustion")

            async with AsyncSessionLocal() as db, db.begin():
                source = PersonalTask(owner_id=ids[0], title="Personal source", due_at=due, start_at=now, next_step="Next step", notes="Source notes")
                db.add(source)
                await db.flush()
                personal_ids.append(source.id)
                task = Task(title="Delegated source", task_type=TaskType.docs, complexity=list(Complexity)[0],
                    min_league=League.C, estimator_id=ids[0], acceptance_owner_id=ids[0], assignee_id=ids[1], due_date=due, status=TaskStatus.in_progress)
                db.add(task)
                await db.flush()
                task_ids.append(task.id)
            await call("POST", f"/from-personal-task/{personal_ids[0]}", owner=1, expected=404)
            await call("POST", f"/from-task/{task_ids[0]}", owner=2, expected=404)
            linked = await call("POST", f"/from-personal-task/{personal_ids[0]}")
            tracker_ids.append(UUID(linked["id"]))
            q_linked = await call("POST", f"/from-task/{task_ids[0]}")
            tracker_ids.append(UUID(q_linked["id"]))
            assert q_linked["source_available"] and q_linked["source"] == "task"
            again = await call("POST", f"/from-personal-task/{personal_ids[0]}")
            assert again["id"] == linked["id"]
            await call("POST", "", {"title": "Duplicate source", "starts_at": now.isoformat(), "due_at": due.isoformat(), "personal_task_id": str(personal_ids[0])}, expected=409)
            await call("PATCH", f"/{linked['id']}", {"due_at": (due + timedelta(days=1)).isoformat()}, expected=409)
            await call("PATCH", f"/{linked['id']}", {"recurrence": {"frequency": "day"}}, expected=409)
            saved_versions = {}
            for result in (linked, q_linked):
                opened = await call("GET", f"/{result['id']}")
                fresh = await call("GET", f"/{result['id']}")
                assert opened["updated_at"] == fresh["updated_at"], "unchanged linked GET must keep editor version"
                saved = await call("PATCH", f"/{result['id']}", {"reminders": [{"value": 1, "unit": "hour"}]})
                assert saved["updated_at"] != fresh["updated_at"], "reminder edits must advance editor version"
                saved_versions[result["id"]] = saved["updated_at"]
                reread = await call("GET", f"/{result['id']}")
                assert reread["updated_at"] == saved["updated_at"], "GET after save must keep saved version"
            async with AsyncSessionLocal() as db, db.begin():
                source = await db.get(PersonalTask, personal_ids[0])
                source.title = "Meaningful changed source title"
            changed = await call("GET", f"/{linked['id']}")
            assert changed["updated_at"] != saved_versions[linked["id"]], "source title must advance editor version"
            assert changed["source_title"] == "Meaningful changed source title"
            unchanged = await call("GET", f"/{linked['id']}")
            assert changed["updated_at"] == unchanged["updated_at"], "unchanged source GET must retain value and timezone representation"
            checks.append("linked_get_version_stable_editor_save_source_change")
            async with AsyncSessionLocal() as db, db.begin():
                source = await db.get(PersonalTask, personal_ids[0])
                source.due_at = due + timedelta(days=1)
                tracker = await db.get(DeadlineTracker, UUID(linked["id"]))
                tracker.due_at = source.due_at
                await sync_tracker_schedule(db, tracker)
                moved = await db.scalar(select(DeadlineTrackerOccurrence.due_at).where(DeadlineTrackerOccurrence.tracker_id == tracker.id))
                assert moved == source.due_at
                source.status = "done"
                task = await db.get(Task, task_ids[0])
                task.status = TaskStatus.cancelled
            assert await run_once(AsyncSessionLocal, now=due + timedelta(days=2), tracker_ids=[UUID(linked["id"]), UUID(q_linked["id"])]) == 0
            async with AsyncSessionLocal() as db:
                for identity in (UUID(linked["id"]), UUID(q_linked["id"])):
                    assert (await db.get(DeadlineTracker, identity)).status == "done"
                    assert await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "pending")) == 0
            checks.append("source_acl_duplicate_readonly_reschedule_done_cancel")

            deleted_trackers = []
            for personal in (True, False):
                async with AsyncSessionLocal() as db, db.begin():
                    if personal:
                        source = PersonalTask(owner_id=ids[0], title="Deleted personal source", due_at=due, start_at=now)
                    else:
                        source = Task(title="Deleted Q source", task_type=TaskType.docs, complexity=list(Complexity)[0],
                            min_league=League.C, estimator_id=ids[0], due_date=due, status=TaskStatus.in_progress)
                    db.add(source)
                    await db.flush()
                    source_id = source.id
                    (personal_ids if personal else task_ids).append(source_id)
                result = await call("POST", f"/from-{'personal-task' if personal else 'task'}/{source_id}")
                identity = UUID(result["id"])
                tracker_ids.append(identity)
                deleted_trackers.append(identity)
                await call("PATCH", f"/{identity}", {"reminders": [{"value": 1, "unit": "hour"}]})
                async with AsyncSessionLocal() as db, db.begin():
                    model = PersonalTask if personal else Task
                    await db.execute(delete(model).where(model.id == source_id))
                async with AsyncSessionLocal() as db:
                    orphan = await db.get(DeadlineTracker, identity)
                    assert orphan.personal_task_id is None and orphan.linked_task_id is None
                    assert orphan.source_check_at is not None
            counts = await asyncio.gather(
                run_once(AsyncSessionLocal, now=at, tracker_ids=deleted_trackers),
                run_once(AsyncSessionLocal, now=at, tracker_ids=deleted_trackers),
            )
            assert sum(counts) == 0, "deleted sources must not alert"
            for identity in deleted_trackers:
                detail = await call("GET", f"/{identity}")
                assert detail["status"] == "archived" and not detail["source_available"]
                await call("PATCH", f"/{identity}", {"status": "active"}, expected=409)
                await call("PATCH", f"/{identity}", {"recurrence": {"frequency": "day"}}, expected=409)
                history = await call("GET", f"/{identity}/history")
                assert sum(row["event_type"] == "source_deleted" for row in history) == 1
                alerts = await call("GET", f"/{identity}/alerts")
                assert all(row["status"] == "cancelled" and row["notification_id"] is None for row in alerts)
            assert await run_once(AsyncSessionLocal, now=at, tracker_ids=deleted_trackers) == 0
            checks.append("actual_source_delete_cancels_without_reactivation")

            # Ensure moving an unsent deadline changes future points, not delivered history.
            future = await create()
            await call("PATCH", f"/{future['id']}", {"due_at": (due + timedelta(days=1)).isoformat()})
            alerts = await call("GET", f"/{future['id']}/alerts")
            assert datetime.fromisoformat(alerts[0]["scheduled_for"].replace("Z", "+00:00")) == due + timedelta(days=1, hours=-1)
            checks.append("future_reminder_reschedule")

            recurrence = {"frequency": "day", "timezone": "UTC", "end_type": "count", "count": 3}
            replay = await create(recurrence=recurrence, reminders=[{"value": 0, "unit": "minute"}])
            replay_id = UUID(replay["id"])
            passed_due = now - timedelta(minutes=1)
            async with AsyncSessionLocal() as db, db.begin():
                tracker = await db.get(DeadlineTracker, replay_id)
                tracker.starts_at = now - timedelta(hours=2)
                tracker.due_at = passed_due
                occurrences = list((await db.execute(select(DeadlineTrackerOccurrence).where(
                    DeadlineTrackerOccurrence.tracker_id == replay_id,
                ))).scalars())
                by_id = {row.id: row for row in occurrences}
                for row in occurrences:
                    row.due_at = passed_due + timedelta(days=row.sequence - 1)
                for row in (await db.execute(select(DeadlineTrackerReminder).where(DeadlineTrackerReminder.tracker_id == replay_id))).scalars():
                    row.created_at = now - timedelta(hours=2)
                for row in (await db.execute(select(DeadlineTrackerDelivery).where(DeadlineTrackerDelivery.tracker_id == replay_id))).scalars():
                    row.scheduled_for = by_id[row.occurrence_id].due_at
                await db.flush()
                assert await deliver_due(db, now=now, tracker_ids=[replay_id]) == 1
            await call("PATCH", f"/{replay_id}", {"recurrence": {**recurrence, "count": 4}})
            counts = await asyncio.gather(
                run_once(AsyncSessionLocal, now=datetime.now(timezone.utc), tracker_ids=[replay_id]),
                run_once(AsyncSessionLocal, now=datetime.now(timezone.utc), tracker_ids=[replay_id]),
            )
            assert sum(counts) == 0, "recurrence edit must not replay a passed sent occurrence"
            assert await run_once(AsyncSessionLocal, now=datetime.now(timezone.utc), tracker_ids=[replay_id]) == 0
            async with AsyncSessionLocal() as db:
                assert await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                    DeadlineTrackerDelivery.tracker_id == replay_id, DeadlineTrackerDelivery.status == "sent",
                )) == 1, "only the original delivery remains sent"
                assert await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                    DeadlineTrackerOccurrence.tracker_id == replay_id, DeadlineTrackerOccurrence.due_at <= passed_due,
                )) == 1, "new recurrence revision must not recreate past dates"
            checks.append("recurrence_edit_nonretroactive_sent_boundary")

            reopen_due = due + timedelta(days=2)
            for terminal in ("done", "archived"):
                one_time = await create()
                identity = one_time["id"]
                original_id = one_time["current_occurrence"]["id"]
                await call("PATCH", f"/{identity}", {"status": terminal})
                reopened = await call("PATCH", f"/{identity}", {"status": "active", "due_at": reopen_due.isoformat()})
                pending = reopened["current_occurrence"]
                assert reopened["status"] == "active" and reopened["completed_at"] is None
                assert pending is not None and pending["status"] == "pending" and pending["id"] != original_id
                assert datetime.fromisoformat(pending["due_at"].replace("Z", "+00:00")) == reopen_due
                repeated = await call("PATCH", f"/{identity}", {"status": "active"})
                reread = await call("GET", f"/{identity}")
                assert repeated["current_occurrence"]["id"] == reread["current_occurrence"]["id"] == pending["id"]
                occurrences = await call("GET", f"/{identity}/occurrences")
                assert len(occurrences) == 2
                historical = next(row for row in occurrences if row["id"] == original_id)
                assert historical["status"] == ("completed" if terminal == "done" else "cancelled")
                assert await run_once(AsyncSessionLocal, now=reopen_due, tracker_ids=[UUID(identity)]) == 1
                assert await run_once(AsyncSessionLocal, now=reopen_due, tracker_ids=[UUID(identity)]) == 0
            checks.append("one_time_explicit_reopen_retains_history_and_reschedules")
            return {"status": "passed", "checks": checks}
    finally:
        async with AsyncSessionLocal() as db, db.begin():
            attention_events = list((await db.execute(select(UserAttentionItem.event_id).where(UserAttentionItem.user_id.in_(ids)))).scalars())
            await db.execute(delete(UserAttentionItem).where(UserAttentionItem.user_id.in_(ids)))
            if attention_events:
                await db.execute(delete(CommunicationEvent).where(CommunicationEvent.id.in_(attention_events)))
            await db.execute(delete(DeadlineTracker).where(DeadlineTracker.owner_id.in_(ids)))
            await db.execute(delete(Notification).where(Notification.user_id.in_(ids)))
            if personal_ids:
                await db.execute(delete(PersonalTask).where(PersonalTask.id.in_(personal_ids)))
            if task_ids:
                await db.execute(delete(Task).where(Task.id.in_(task_ids)))
            await db.execute(delete(User).where(User.id.in_(ids)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-local-db", action="store_true")
    args = parser.parse_args()
    try:
        require_local(args.allow_local_db)
        print(json.dumps(asyncio.run(smoke())))
    except Exception as exc:
        # Do not print SQLAlchemy exceptions: parameters may include operational data.
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
            "assertion": str(exc) if isinstance(exc, AssertionError) else None,
            "location": f"{Path(frame.filename).name}:{frame.lineno}"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
