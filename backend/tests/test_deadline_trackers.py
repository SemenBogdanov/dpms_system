"""Isolated SQLite persistence tests; PostgreSQL races live in the smoke script."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Boolean, Column, JSON, MetaData, Table, delete, event, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import deadline_trackers as api
from app.models import Base
from app.models.deadline_tracker import (
    DeadlineTracker, DeadlineTrackerCategory, DeadlineTrackerDelivery, DeadlineTrackerEvent,
    DeadlineTrackerGroup, DeadlineTrackerOccurrence, DeadlineTrackerReminder,
)
from app.models.notification import Notification
from app.models.user import UserRole
from app.schemas.deadline_tracker import (
    DeadlineTrackerCreate, DeadlineTrackerUpdate, TrackerGroupUpdate,
    TrackerOrganizationCreate, TrackerRecurrence, TrackerReminderInput, TrackerReorder,
)
from app.services.deadline_tracker_calendar import effective_due, first_occurrence_after, occurrence_due, utc
from app.services.deadline_tracker_schedule import (
    expand_tracker, reset_series_schedule, set_reminders, suppress_due_deliveries, sync_tracker_schedule,
    tracker_source_deleted,
)
from app.services.deadline_tracker_sources import reconcile_linked_tracker, task_access_clause
from app.workers.deadline_reminders import due_delivery_query, run_once

UTC = timezone.utc
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


class CalendarTests(unittest.TestCase):
    def test_first_future_occurrence_keeps_count_and_skips_old_dates_efficiently(self):
        rule = {"frequency": "day", "timezone": "UTC"}
        anchor = datetime(1970, 1, 1, 12, tzinfo=UTC)
        with patch("app.services.deadline_tracker_calendar.occurrence_due", wraps=occurrence_due) as compute:
            sequence, due = first_occurrence_after(anchor, rule, NOW)
            self.assertEqual(due, NOW + timedelta(days=1))
            self.assertEqual(sequence, (NOW - anchor).days + 2)
            self.assertLess(compute.call_count, 40)
        finite = {**rule, "end_type": "count", "count": 3}
        self.assertEqual(first_occurrence_after(NOW, finite, NOW), (2, NOW + timedelta(days=1)))
        self.assertEqual(first_occurrence_after(NOW, finite, NOW + timedelta(days=3)), (4, None))

    def test_migration_revision_and_sql_bind_parameters(self):
        path = Path(__file__).resolve().parents[1] / "alembic/versions/079_deadline_tracker_organization.py"
        spec = importlib.util.spec_from_file_location("tracker_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.revision, "079_tracker_organization")
        self.assertEqual(module.down_revision, "078_start_menu_knowledge_layout")
        self.assertLessEqual(len(module.revision), 32)
        bind = Mock()
        module.backfill_legacy(bind)
        for call in bind.execute.call_args_list:
            self.assertEqual(list(call.args[0]._bindparams), [])

    def test_anchored_month_end_and_interval(self):
        anchor = datetime(2024, 1, 31, 9, tzinfo=UTC)
        rule = {"frequency": "month", "timezone": "UTC"}
        self.assertEqual([occurrence_due(anchor, rule, n).day for n in range(1, 5)], [31, 29, 31, 30])
        self.assertEqual(occurrence_due(anchor, {**rule, "interval": 2}, 2), datetime(2024, 3, 31, 9, tzinfo=UTC))

    def test_feb29_returns_in_leap_year(self):
        anchor = datetime(2024, 2, 29, 9, tzinfo=UTC)
        rule = {"frequency": "year", "timezone": "UTC"}
        self.assertEqual([occurrence_due(anchor, rule, n).day for n in range(1, 6)], [29, 28, 28, 28, 29])

    def test_dst_gap_forward_and_no_permanent_hour_drift(self):
        anchor = datetime(2026, 3, 7, 7, 30, tzinfo=UTC)
        rule = {"frequency": "day", "timezone": "America/New_York"}
        self.assertEqual(occurrence_due(anchor, rule, 2), datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
        self.assertEqual(occurrence_due(anchor, rule, 3), datetime(2026, 3, 9, 6, 30, tzinfo=UTC))

    def test_overlap_uses_first_fold(self):
        anchor = datetime(2026, 10, 31, 5, 30, tzinfo=UTC)
        self.assertEqual(occurrence_due(anchor, {"frequency": "day", "timezone": "America/New_York"}, 2), datetime(2026, 11, 1, 5, 30, tzinfo=UTC))

    def test_count_until_inclusive_one_time_and_year_overflow(self):
        self.assertIsNone(occurrence_due(NOW, None, 2))
        self.assertEqual(occurrence_due(NOW, {"frequency": "week", "end_type": "count", "count": 1}, 1), NOW)
        self.assertIsNone(occurrence_due(NOW, {"frequency": "week", "end_type": "count", "count": 1}, 2))
        until = NOW + timedelta(days=7)
        rule = {"frequency": "week", "end_type": "until", "until": until.isoformat(), "timezone": "UTC"}
        self.assertEqual(occurrence_due(NOW, rule, 2), until)
        self.assertIsNone(occurrence_due(NOW, rule, 3))
        self.assertIsNone(occurrence_due(datetime(9999, 12, 31, tzinfo=UTC), {"frequency": "year"}, 2))

    def test_schema_rejects_equivalent_offsets_linked_series_and_naive_dates(self):
        valid = {"title": "Calendar", "starts_at": NOW, "due_at": NOW + timedelta(days=1)}
        for changes in (
            {"reminders": [{"value": 60, "unit": "minute"}, {"value": 1, "unit": "hour"}]},
            {"reminders": [{"value": n, "unit": "minute"} for n in range(11)]},
            {"linked_task_id": uuid4(), "recurrence": {"frequency": "month"}},
            {"personal_task_id": uuid4(), "linked_task_id": uuid4()},
            {"due_at": NOW.replace(tzinfo=None)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                DeadlineTrackerCreate(**(valid | changes))
        for payload in ({"due_at": None}, {"reminders": None}, {"status": None}):
            with self.assertRaises(ValidationError):
                DeadlineTrackerUpdate(**payload)
        with self.assertRaises(ValidationError):
            TrackerRecurrence(frequency="day", timezone="not/a/zone")
        with self.assertRaises(ValidationError):
            TrackerReminderInput(value=367, unit="day")
        with self.assertRaises(ValidationError):
            TrackerOrganizationCreate(name="   ")

    def test_q_acl_matches_get_not_project_link_capability(self):
        for role, enabled, allowed in ((UserRole.executor, False, False), (UserRole.executor, True, True), (UserRole.admin, False, True)):
            self.assertEqual(task_access_clause(SimpleNamespace(role=role, task_workspace_enabled=enabled, can_link_queue_tasks_to_projects=True)), allowed)

    def test_worker_query_uses_index_columns_and_locks(self):
        sql = str(due_delivery_query(NOW, 50).compile(dialect=dialect()))
        self.assertIn("deadline_tracker_deliveries.status", sql)
        self.assertIn("deadline_tracker_deliveries.scheduled_for <=", sql)
        lock = str(select(DeadlineTracker).with_for_update(skip_locked=True).compile(dialect=dialect()))
        self.assertIn("FOR UPDATE SKIP LOCKED", lock)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dpms-tracker-test-")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.tmp.name}/test.db")
        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        metadata = MetaData()
        self.users = Table("users", metadata, Column("id", UUID(as_uuid=True), primary_key=True), Column("is_active", Boolean, nullable=False))
        for name in ("tasks", "personal_tasks"):
            Table(name, metadata, Column("id", UUID(as_uuid=True), primary_key=True))
        models = [DeadlineTrackerGroup, DeadlineTrackerCategory, DeadlineTracker, DeadlineTrackerOccurrence,
                  DeadlineTrackerReminder, Notification, DeadlineTrackerDelivery, DeadlineTrackerEvent]
        for model in models:
            for column in model.__table__.columns:
                if isinstance(column.type, (ARRAY, JSONB)) and "sqlite" not in column.type._variant_mapping:
                    column.type = column.type.with_variant(JSON(none_as_null=True), "sqlite")
            model.__table__.to_metadata(metadata)
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.owner = SimpleNamespace(id=uuid4(), role=UserRole.executor, task_workspace_enabled=True, is_active=True)
        self.other = SimpleNamespace(id=uuid4(), role=UserRole.executor, task_workspace_enabled=False, is_active=True)
        async with self.sessions() as db, db.begin():
            await db.execute(self.users.insert(), [{"id": u.id, "is_active": True} for u in (self.owner, self.other)])

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmp.cleanup()

    async def make_tracker(self, *, rule=None, reminders=None, due=None):
        async with self.sessions() as db, db.begin():
            tracker = DeadlineTracker(owner_id=self.owner.id, title="Calendar", starts_at=NOW - timedelta(days=1), due_at=due or NOW + timedelta(hours=2), recurrence=rule, status="active", tags=[])
            db.add(tracker)
            await db.flush()
            await set_reminders(db, tracker, reminders or [TrackerReminderInput(value=1, unit="hour")], now=NOW)
            await sync_tracker_schedule(db, tracker, now=NOW)
            return tracker.id

    async def test_groups_owner_archive_collapse_reorder_delete_preserves_trackers(self):
        async with self.sessions() as db:
            group = await api.create_tracker_group(TrackerOrganizationCreate(name="Group"), user=self.owner, db=db)
            group_id = group.id
            with self.assertRaises(HTTPException) as caught:
                await api.update_tracker_group(group_id, TrackerGroupUpdate(name="Stolen"), user=self.other, db=db)
            self.assertEqual(caught.exception.status_code, 404)
            await db.rollback()
            await api.update_tracker_group(group_id, TrackerGroupUpdate(is_collapsed=True, is_archived=True), user=self.owner, db=db)
            result = await api.reorder_tracker_groups(TrackerReorder(ids=[group_id]), user=self.owner, db=db)
            self.assertTrue(result[0].is_collapsed)
        identity = await self.make_tracker()
        async with self.sessions() as db:
            row = await db.get(DeadlineTracker, identity)
            row.group_id = group_id
            await db.commit()
            await api.delete_tracker_group(group_id, user=self.owner, db=db)
        async with self.sessions() as db:
            self.assertIsNone((await db.get(DeadlineTracker, identity)).group_id)

    async def test_seed_once_and_category_owner_guard(self):
        async with self.sessions() as db:
            first = await api.list_tracker_categories(include_archived=True, user=self.owner, db=db)
            second = await api.list_tracker_categories(include_archived=True, user=self.owner, db=db)
            self.assertEqual({x.id for x in first}, {x.id for x in second})
            self.assertEqual(len(first), 7)
            with self.assertRaises(HTTPException):
                await api.delete_tracker_category(first[0].id, user=self.other, db=db)

    async def test_restart_delivery_and_crash_rollback(self):
        identity = await self.make_tracker()
        at = NOW + timedelta(hours=1, seconds=1)
        with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock) as emit:
            emit.side_effect = RuntimeError("simulated crash after notification flush")
            with self.assertRaises(RuntimeError):
                await run_once(self.sessions, now=at)
            async with self.sessions() as db:
                self.assertEqual(await db.scalar(select(func.count()).select_from(Notification)), 0)
                self.assertEqual(await db.scalar(select(DeadlineTrackerDelivery.status)), "pending")
            emit.side_effect = None
            self.assertEqual(await run_once(self.sessions, now=at), 1)
            # Fresh sessions model a restarted process; the read projection must not reopen.
            self.assertEqual(await run_once(self.sessions, now=at + timedelta(seconds=1)), 0)
            self.assertEqual(emit.await_count, 2)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Notification)), 1)
            delivery = await db.scalar(select(DeadlineTrackerDelivery))
            self.assertEqual(delivery.tracker_id, identity)
            duplicate = DeadlineTrackerDelivery(tracker_id=identity, occurrence_id=delivery.occurrence_id, reminder_id=delivery.reminder_id, scheduled_for=at)
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                await db.flush()

    async def test_reschedule_only_future_and_keeps_sent_identity(self):
        identity = await self.make_tracker(reminders=[TrackerReminderInput(value=60, unit="minute"), TrackerReminderInput(value=30, unit="minute")])
        with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock):
            await run_once(self.sessions, now=NOW + timedelta(hours=1, seconds=1))
        async with self.sessions() as db, db.begin():
            before = list((await db.execute(select(DeadlineTrackerDelivery).order_by(DeadlineTrackerDelivery.scheduled_for))).scalars())
            first_id, first_when = before[0].id, utc(before[0].scheduled_for)
            tracker = await db.get(DeadlineTracker, identity)
            tracker.due_at = NOW + timedelta(days=1)
            await sync_tracker_schedule(db, tracker, now=NOW + timedelta(hours=1, seconds=2))
            await db.refresh(before[0])
            await db.refresh(before[1])
            self.assertEqual(before[0].id, first_id)
            self.assertEqual(utc(before[0].scheduled_for), first_when)
            self.assertEqual(utc(before[1].scheduled_for), NOW + timedelta(days=1, minutes=-30))

    async def test_recurrence_reset_does_not_replay_passed_sent_occurrence(self):
        anchor = NOW + timedelta(hours=2)
        rule = {"frequency": "day", "timezone": "UTC", "end_type": "count", "count": 3}
        identity = await self.make_tracker(rule=rule, due=anchor, reminders=[TrackerReminderInput(value=0, unit="minute")])
        with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock):
            self.assertEqual(await run_once(self.sessions, now=anchor + timedelta(seconds=1), tracker_ids=[identity]), 1)
            async with self.sessions() as db, db.begin():
                tracker = await db.get(DeadlineTracker, identity)
                tracker.recurrence = {**rule, "count": 4}
                await reset_series_schedule(db, tracker, now=anchor + timedelta(seconds=2))
                self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                    DeadlineTrackerOccurrence.tracker_id == identity, DeadlineTrackerOccurrence.due_at <= anchor,
                )), 1)
                self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                    DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "sent",
                )), 1)
            for _ in range(2):
                self.assertEqual(await run_once(self.sessions, now=anchor + timedelta(seconds=3), tracker_ids=[identity]), 0)
            self.assertEqual(await run_once(self.sessions, now=anchor + timedelta(days=1, seconds=1), tracker_ids=[identity]), 1)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "sent",
            )), 2)

    async def test_recurrence_reset_suppresses_past_reminder_for_future_occurrence(self):
        rule = {"frequency": "day", "timezone": "UTC", "end_type": "count", "count": 3}
        identity = await self.make_tracker(rule=rule)
        sent_at = NOW + timedelta(hours=1, seconds=1)
        with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock):
            self.assertEqual(await run_once(self.sessions, now=sent_at, tracker_ids=[identity]), 1)
            async with self.sessions() as db, db.begin():
                tracker = await db.get(DeadlineTracker, identity)
                tracker.recurrence = {**rule, "count": 4}
                await reset_series_schedule(db, tracker, now=sent_at)
            self.assertEqual(await run_once(self.sessions, now=sent_at + timedelta(seconds=1), tracker_ids=[identity]), 0)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "sent",
            )), 1)

    async def test_explicit_one_time_reopen_has_new_pending_and_retains_terminal_history(self):
        future = datetime.now(UTC) + timedelta(days=90)
        for status in ("done", "archived"):
            with self.subTest(status=status):
                identity = await self.make_tracker()
                async with self.sessions() as db:
                    original = await db.scalar(select(DeadlineTrackerOccurrence).where(DeadlineTrackerOccurrence.tracker_id == identity))
                    original_id = original.id
                    await api.update_deadline_tracker(identity, DeadlineTrackerUpdate(status=status), user=self.owner, db=db)
                    terminal_status = original.status
                    completed_at = original.completed_at
                    result = await api.update_deadline_tracker(identity, DeadlineTrackerUpdate(status="active", due_at=future), user=self.owner, db=db)
                    self.assertEqual(result.status, "active")
                    self.assertIsNone(result.completed_at)
                    self.assertEqual(result.current_occurrence.status, "pending")
                    self.assertEqual(utc(result.current_occurrence.due_at), future)
                    self.assertNotEqual(result.current_occurrence.id, original_id)
                    pending_id = result.current_occurrence.id
                    await db.refresh(original)
                    self.assertEqual(original.status, terminal_status)
                    self.assertEqual(
                        utc(original.completed_at) if original.completed_at else None,
                        utc(completed_at) if completed_at else None,
                    )
                    reread = await api.get_deadline_tracker(identity, user=self.owner, db=db)
                    repeated = await api.update_deadline_tracker(identity, DeadlineTrackerUpdate(status="active"), user=self.owner, db=db)
                    self.assertEqual(reread.current_occurrence.id, pending_id)
                    self.assertEqual(repeated.current_occurrence.id, pending_id)
                    self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                        DeadlineTrackerOccurrence.tracker_id == identity,
                    )), 2)
                with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock):
                    self.assertEqual(await run_once(self.sessions, now=future, tracker_ids=[identity]), 1)

    async def test_pause_suppresses_without_shifting_recurrence(self):
        identity = await self.make_tracker(rule={"frequency": "day", "timezone": "UTC", "end_type": "count", "count": 3})
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            tracker.status = "paused"
            tracker.pause_started_at = NOW
        self.assertEqual(await run_once(self.sessions, now=NOW + timedelta(hours=1, seconds=1)), 0)
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            await suppress_due_deliveries(db, tracker, now=NOW + timedelta(hours=2))
            tracker.status = "active"
            tracker.paused_seconds = 7200
            tracker.pause_started_at = None
            await sync_tracker_schedule(db, tracker, now=NOW + timedelta(hours=2))
            self.assertEqual(effective_due(tracker), NOW + timedelta(hours=2))
            self.assertEqual(await db.scalar(select(DeadlineTrackerDelivery.status).order_by(DeadlineTrackerDelivery.scheduled_for)), "suppressed")

    async def test_completion_separate_from_finish_and_owner_isolation(self):
        identity = await self.make_tracker(rule={"frequency": "day", "timezone": "UTC", "end_type": "count", "count": 3})
        async with self.sessions() as db:
            occurrence = await db.scalar(select(DeadlineTrackerOccurrence).where(DeadlineTrackerOccurrence.tracker_id == identity).order_by(DeadlineTrackerOccurrence.sequence))
            with self.assertRaises(HTTPException):
                await api.complete_tracker_occurrence(identity, occurrence.id, user=self.other, db=db)
            result = await api.complete_tracker_occurrence(identity, occurrence.id, user=self.owner, db=db)
            self.assertEqual(result.status, "active")
            self.assertEqual(result.current_occurrence.sequence, 2)
            result = await api.finish_tracker_series(identity, user=self.owner, db=db)
            self.assertEqual(result.status, "done")
            self.assertIsNone(result.current_occurrence)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(DeadlineTrackerOccurrence.status == "completed")), 1)

    async def test_annual_completion_keeps_one_frontier_beyond_horizon(self):
        anchor = NOW + timedelta(hours=2)
        identity = await self.make_tracker(rule={"frequency": "year", "timezone": "UTC"}, due=anchor)
        async with self.sessions() as db:
            first = await db.scalar(select(DeadlineTrackerOccurrence).where(DeadlineTrackerOccurrence.tracker_id == identity))
            result = await api.complete_tracker_occurrence(identity, first.id, user=self.owner, db=db)
            self.assertEqual(result.status, "active")
            self.assertFalse(result.series_exhausted)
            self.assertEqual(result.current_occurrence.sequence, 2)
            self.assertEqual(utc(result.current_occurrence.due_at), occurrence_due(anchor, {"frequency": "year", "timezone": "UTC"}, 2))
            tracker = await db.get(DeadlineTracker, identity)
            for _ in range(3):
                await expand_tracker(db, tracker, now=NOW)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                DeadlineTrackerOccurrence.tracker_id == identity,
            )), 2)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "pending",
            )), 1)
            reread = await api.get_deadline_tracker(identity, user=self.owner, db=db)
            self.assertEqual(reread.current_occurrence.id, result.current_occurrence.id)
            self.assertFalse(reread.series_exhausted)

    async def test_finite_single_occurrence_exhaustion_keeps_explicit_finish(self):
        identity = await self.make_tracker(rule={"frequency": "year", "timezone": "UTC", "end_type": "count", "count": 1})
        async with self.sessions() as db:
            before = await api.get_deadline_tracker(identity, user=self.owner, db=db)
            self.assertFalse(before.series_exhausted)
            result = await api.complete_tracker_occurrence(identity, before.current_occurrence.id, user=self.owner, db=db)
            self.assertEqual(result.status, "active")
            self.assertIsNone(result.current_occurrence)
            self.assertTrue(result.series_exhausted)
            reread = await api.get_deadline_tracker(identity, user=self.owner, db=db)
            self.assertTrue(reread.series_exhausted)
            self.assertIsNone(reread.current_occurrence)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence).where(
                DeadlineTrackerOccurrence.tracker_id == identity,
            )), 1)
            finished = await api.finish_tracker_series(identity, user=self.owner, db=db)
            self.assertEqual(finished.status, "done")

    async def test_link_uniqueness_and_sql_null_default(self):
        task_id = uuid4()
        async with self.engine.begin() as connection:
            await connection.execute(Table("tasks", MetaData(), Column("id", UUID(as_uuid=True))).insert().values(id=task_id))
        async with self.sessions() as db, db.begin():
            db.add(DeadlineTracker(owner_id=self.owner.id, title="linked", starts_at=NOW, due_at=NOW + timedelta(days=1), linked_task_id=task_id, recurrence=None))
        async with self.sessions() as db:
            db.add(DeadlineTracker(owner_id=self.owner.id, title="duplicate", starts_at=NOW, due_at=NOW + timedelta(days=1), linked_task_id=task_id, recurrence=None))
            with self.assertRaises(IntegrityError):
                await db.flush()

    async def test_actual_source_delete_cancels_and_cannot_reenable_tracker(self):
        for source_table, field in (("tasks", "linked_task_id"), ("personal_tasks", "personal_task_id")):
            with self.subTest(source=source_table):
                source_id = uuid4()
                source = Table(source_table, MetaData(), Column("id", UUID(as_uuid=True)))
                async with self.engine.begin() as connection:
                    await connection.execute(source.insert().values(id=source_id))
                identity = await self.make_tracker()
                async with self.sessions() as db, db.begin():
                    tracker = await db.get(DeadlineTracker, identity)
                    setattr(tracker, field, source_id)
                    await sync_tracker_schedule(db, tracker, now=NOW)
                async with self.engine.begin() as connection:
                    await connection.execute(delete(source).where(source.c.id == source_id))
                with patch("app.services.deadline_tracker_notifications.emit_attention_event", new_callable=AsyncMock) as emit:
                    self.assertEqual(await run_once(self.sessions, now=NOW + timedelta(hours=2), tracker_ids=[identity]), 0)
                    emit.assert_not_awaited()
                async with self.sessions() as db:
                    result = await api.get_deadline_tracker(identity, user=self.owner, db=db)
                    self.assertEqual(result.status, "archived")
                    self.assertFalse(result.source_available)
                    tracker = await db.get(DeadlineTracker, identity)
                    self.assertIsNone(getattr(tracker, field))
                    self.assertTrue(tracker_source_deleted(tracker))
                    tracker.status = "active"
                    await reset_series_schedule(db, tracker, now=NOW)
                    await db.commit()
                    self.assertEqual(tracker.status, "archived")
                    self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerDelivery).where(
                        DeadlineTrackerDelivery.tracker_id == identity, DeadlineTrackerDelivery.status == "pending",
                    )), 0)
                    self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerEvent).where(
                        DeadlineTrackerEvent.tracker_id == identity, DeadlineTrackerEvent.event_type == "source_deleted",
                    )), 1)
                    with self.assertRaises(HTTPException) as caught:
                        await api.update_deadline_tracker(identity, DeadlineTrackerUpdate(status="active"), user=self.owner, db=db)
                    self.assertEqual(caught.exception.status_code, 409)

    async def test_terminal_link_keeps_provenance_after_actual_source_delete(self):
        source_id = uuid4()
        source = Table("tasks", MetaData(), Column("id", UUID(as_uuid=True)))
        async with self.engine.begin() as connection:
            await connection.execute(source.insert().values(id=source_id))
        identity = await self.make_tracker()
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            tracker.linked_task_id = source_id
            tracker.status = "done"
            await sync_tracker_schedule(db, tracker, now=NOW)
            self.assertIsNotNone(tracker.source_check_at)
        async with self.engine.begin() as connection:
            await connection.execute(delete(source).where(source.c.id == source_id))
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            self.assertTrue(tracker_source_deleted(tracker))
            tracker.status = "active"
            await sync_tracker_schedule(db, tracker, now=NOW)
            self.assertEqual(tracker.status, "archived")

    async def test_scheduler_telemetry_keeps_editor_version_but_content_changes_advance(self):
        identity = await self.make_tracker()
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            version = utc(tracker.updated_at)
            tracker.schedule_check_at = NOW + timedelta(days=1)
            tracker.next_sequence += 1
            await db.flush()
            await db.refresh(tracker)
            self.assertEqual(utc(tracker.updated_at), version)
            tracker.title = "Meaningfully changed title"
            tracker.schedule_check_at = NOW + timedelta(days=2)
            await db.flush()
            await db.refresh(tracker)
            self.assertNotEqual(utc(tracker.updated_at), version)
            changed_version = utc(tracker.updated_at)
            explicit_version = changed_version + timedelta(seconds=1)
            tracker.updated_at = explicit_version
            tracker.next_sequence += 1
            await db.flush()
            await db.refresh(tracker)
            self.assertEqual(utc(tracker.updated_at), explicit_version)

    async def test_linked_reconcile_keeps_timestamp_unless_source_changes(self):
        source_id = uuid4()
        source_table = Table("personal_tasks", MetaData(), Column("id", UUID(as_uuid=True)))
        async with self.engine.begin() as connection:
            await connection.execute(source_table.insert().values(id=source_id))
        identity = await self.make_tracker()
        source = SimpleNamespace(id=source_id, title="Source title", task_number=123, description=None,
            notes="Notes", due_at=NOW + timedelta(hours=2), start_at=NOW - timedelta(days=1),
            created_at=NOW - timedelta(days=1), responsible="Owner", next_step="Next step", status="active")
        with patch("app.services.deadline_tracker_sources.get_source", new_callable=AsyncMock, return_value=source):
            async with self.sessions() as db, db.begin():
                tracker = await db.get(DeadlineTracker, identity)
                tracker.personal_task_id = source_id
                await reconcile_linked_tracker(db, tracker, user=self.owner, now=NOW)
                await db.refresh(tracker)
                version = utc(tracker.updated_at)
            async with self.sessions() as db, db.begin():
                tracker = await db.get(DeadlineTracker, identity)
                await reconcile_linked_tracker(db, tracker, user=self.owner, now=NOW + timedelta(seconds=5))
                await db.refresh(tracker)
                self.assertEqual(utc(tracker.updated_at), version)
                self.assertEqual(utc(tracker.source_check_at), NOW + timedelta(seconds=65))
                source.title = "Changed source title"
                await reconcile_linked_tracker(db, tracker, user=self.owner, now=NOW + timedelta(seconds=10))
                await db.refresh(tracker)
                self.assertNotEqual(utc(tracker.updated_at), version)
                self.assertEqual(tracker.title, "PT-123 Changed source title")
                changed_version = utc(tracker.updated_at)
                await reconcile_linked_tracker(db, tracker, user=self.owner, now=NOW + timedelta(seconds=15))
                await db.refresh(tracker)
                self.assertEqual(utc(tracker.updated_at), changed_version)
                source.status = "done"
                await reconcile_linked_tracker(db, tracker, user=self.owner, now=NOW + timedelta(seconds=20))
                await db.refresh(tracker)
                self.assertNotEqual(utc(tracker.updated_at), changed_version)
                self.assertEqual(tracker.status, "done")

    async def test_worker_expansion_preserves_series_editor_version(self):
        identity = await self.make_tracker(rule={"frequency": "day", "timezone": "UTC"})
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            version = utc(tracker.updated_at)
            cursor = tracker.next_sequence
            await expand_tracker(db, tracker, now=NOW + timedelta(days=15))
            await db.refresh(tracker)
            self.assertGreater(tracker.next_sequence, cursor)
            self.assertEqual(utc(tracker.updated_at), version)

    async def test_expansion_is_batched_and_durable_cursor(self):
        statements = []
        def count_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.engine.sync_engine, "before_cursor_execute", count_sql)
        identity = await self.make_tracker(rule={"frequency": "day", "timezone": "UTC"}, reminders=[TrackerReminderInput(value=366, unit="day")])
        event.remove(self.engine.sync_engine, "before_cursor_execute", count_sql)
        # 397 occurrences must not produce 397 database round trips.
        self.assertLess(len(statements), 40, [s[:80] for s in statements])
        async with self.sessions() as db, db.begin():
            tracker = await db.get(DeadlineTracker, identity)
            count = await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence))
            self.assertGreater(count, 390)
            before_cursor = tracker.next_sequence
            await expand_tracker(db, tracker, now=NOW)
            self.assertEqual(tracker.next_sequence, before_cursor)
            self.assertEqual(await db.scalar(select(func.count()).select_from(DeadlineTrackerOccurrence)), count)


if __name__ == "__main__":
    unittest.main()
