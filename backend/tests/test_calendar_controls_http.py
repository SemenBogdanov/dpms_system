"""Opt-in HTTP regressions against the migrated disposable PostgreSQL database.

Run from backend after the integrator applies calendar migration 091:
  DPMS_CALENDAR_HTTP_TESTS=1 python -m unittest discover -s tests \
      -p 'test_calendar_controls_http.py' -v

DATABASE_URL must already name dpms_calendar_v5_http_test on an approved local
host. No settings/application imports occur when the suite is not opted in.
The existing HTTP fixture owns the transaction and rolls back all test data;
this module never creates, resets, drops, or migrates a database/schema.
"""
import copy
from datetime import datetime, timedelta, timezone
import os
import unittest
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarControlsHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine import make_url

        try:
            url = make_url(os.environ["DATABASE_URL"])
        except Exception:
            raise RuntimeError("A valid disposable PostgreSQL DATABASE_URL is required") from None
        if (url.database != "dpms_calendar_v5_http_test"
                or url.host not in {"dpms-local-db-1", "localhost", "127.0.0.1"}
                or url.drivername != "postgresql+asyncpg" or url.query):
            raise RuntimeError("Only the local dpms_calendar_v5_http_test asyncpg database is allowed")

        import test_calendar_http_integration as fixture
        from app.models import audit_calendar as models

        # Reuse setup/helpers without inheriting and rerunning the original tests.
        self.fixture = fixture.CalendarHTTPTests
        self.models = models
        await self.fixture.asyncSetUp(self)
        self.addAsyncCleanup(self.fixture.asyncTearDown, self)
        self.day = self.today + timedelta(days=7 - self.today.weekday())
        self.next_day = self.day + timedelta(days=1)
        self.actor = self.people["helper"]
        self.scope_id = UUID((await self.calendar_state())["scope"]["id"])

    def body(self, operation, payload):
        return self.fixture.body(self, operation, payload)

    async def command(self, body):
        return await self.fixture.command(self, body)

    def person_day(self, code="employee", day=None, reason="Synthetic change"):
        return {"user_id": str(self.people[code].id),
                "date": (day or self.day).isoformat(), "reason": reason}

    def patch(self, day=None, start=600, end=1080, value=True):
        return {"date": (day or self.day).isoformat(), "start": start,
                "end": end, "value": value}

    async def send(self, operation, payload, *, actor="helper", status=200):
        self.actor = self.people[actor]
        response = await self.command(self.body(operation, payload))
        self.assertEqual(response.status_code, status, response.text)
        if status == 200:
            self.version = response.json()["version"]
            return response.json()["result"]
        return response

    async def paint(self, code="employee", *, day=None, start=600, end=1080, value=True):
        return await self.send("availability.paint", {
            "user_id": str(self.people[code].id),
            "patches": [self.patch(day, start, end, value)]})

    async def lock_day(self, code="employee", day=None):
        return await self.send("availability.lock", self.person_day(code, day))

    async def request_day(self, code="employee", day=None, *, actor=None):
        return await self.send("availability.request", self.person_day(code, day),
                               actor=actor or code)

    async def resolve(self, identity, action, *, actor="helper", status=200):
        return await self.send("availability.resolve", {
            "id": identity, "action": action, "reason": "Synthetic " + action},
            actor=actor, status=status)

    async def calendar_state(self, *, actor="helper", start=None, end=None, **filters):
        self.actor = self.people[actor]
        response = await self.client.get("/api/audit-calendar/state", params={
            "from": (start or self.day).isoformat(),
            "to": (end or self.next_day).isoformat(), **filters})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def rows(self, model, *conditions):
        from sqlalchemy import select

        async with self.factory() as db:
            return list((await db.scalars(select(model).where(
                model.scope_id == self.scope_id, *conditions))).all())

    async def request_row(self, identity):
        model = self.models.AuditCalendarChangeRequest
        rows = await self.rows(model, model.id == UUID(identity))
        self.assertEqual(len(rows), 1)
        return rows[0]

    async def lock_row(self, code="employee", day=None):
        model = self.models.AuditCalendarAvailabilityLock
        rows = await self.rows(model, model.user_id == self.people[code].id,
                               model.date == (day or self.day))
        self.assertEqual(len(rows), 1)
        return rows[0]

    async def notices(self, kind):
        from sqlalchemy import text

        async with self.factory() as db:
            return list((await db.scalars(text(
                "SELECT to_jsonb(n) FROM notifications n "
                "WHERE n.type = :kind AND n.user_id = ANY(:users) ORDER BY n.id"
            ), {"kind": kind, "users": [actor.id for actor in self.people.values()]})).all())

    async def assert_notices_for(self, notices, codes, *, duration=30, day=None):
        from sqlalchemy import select
        from app.models.messages import CommunicationEvent, UserAttentionItem
        from app.services.messages import notification_is_important
        from app.services.notifications import get_user_notifications

        self.assertCountEqual([notice["user_id"] for notice in notices],
                              [str(self.people[code].id) for code in codes])
        for notice in notices:
            self.assertIn(notice["type"], {
                "calendar_availability_requested", "calendar_availability_resolved",
                "calendar_group_reconcile_requested"})
            self.assertTrue(notification_is_important(notice["type"]))
            link = urlparse(notice["link"])
            self.assertEqual((link.scheme, link.netloc, link.path), ("", "", "/audit-calendar"))
            params = parse_qs(link.query, keep_blank_values=True)
            self.assertEqual(params["view"], ["readiness"])
            self.assertEqual(params["from"], [(day or self.day).isoformat()])
            self.assertEqual(params["to"], [(day or self.day).isoformat()])
            if notice["type"] == "calendar_group_reconcile_requested":
                self.assertEqual(params["summary_tab"], ["groups"])
                self.assertEqual(params["duration"], [str(duration)])
            else:
                self.assertEqual(params["summary_tab"], ["requests"])
                self.assertNotIn("duration", params)
            self.assertFalse(notice["is_read"])
        # The whitelist must produce real Important inbox rows, not only notifications.
        async with self.factory() as db:
            attention = (await db.execute(select(
                UserAttentionItem.user_id, UserAttentionItem.kind, UserAttentionItem.is_read,
                CommunicationEvent.event_type, CommunicationEvent.source_type,
                CommunicationEvent.source_key, CommunicationEvent.idempotency_key,
                CommunicationEvent.actor_id, CommunicationEvent.link,
            ).join(CommunicationEvent, CommunicationEvent.id == UserAttentionItem.event_id).where(
                UserAttentionItem.user_id.in_([actor.id for actor in self.people.values()]),
                CommunicationEvent.event_type.in_({notice["type"] for notice in notices}),
            ))).all()
            self.assertCountEqual(
                [(str(row.user_id), row.event_type, row.source_key) for row in attention],
                [(notice["user_id"], notice["type"], notice["id"]) for notice in notices],
            )
            notice_links = {notice["id"]: notice["link"] for notice in notices}
            for row in attention:
                self.assertEqual(row.kind, "important")
                self.assertFalse(row.is_read)
                self.assertEqual(row.source_type, "notification")
                self.assertEqual(row.idempotency_key, "notification:" + row.source_key)
                self.assertNotEqual(row.actor_id, row.user_id)
                self.assertEqual(row.link, notice_links[row.source_key])
            for code in set(codes):
                delivered = await get_user_notifications(db, self.people[code].id)
                expected_ids = {notice["id"] for notice in notices
                                if notice["user_id"] == str(self.people[code].id)}
                self.assertTrue(expected_ids.issubset({str(row.id) for row in delivered}))

    def assert_server_time(self, value, before, after):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        self.assertIsNotNone(value.utcoffset())
        self.assertLessEqual(before, value)
        self.assertLessEqual(value, after)

    async def test_lock_request_approve_close_persist_snapshots_and_server_history(self):
        await self.paint()
        before_lock = datetime.now(timezone.utc)
        await self.lock_day()
        locked = await self.lock_row()
        self.assertTrue(locked.locked)
        self.assertEqual(locked.locked_by_id, self.people["helper"].id)
        self.assert_server_time(locked.locked_at, before_lock, datetime.now(timezone.utc))
        initial = copy.deepcopy(locked.snapshot)
        self.assertTrue(initial)

        before_request = datetime.now(timezone.utc)
        answer = await self.request_day()
        requested = await self.request_row(answer["id"])
        self.assertEqual(requested.status, "pending")
        self.assertEqual(requested.user_id, self.people["employee"].id)
        self.assertEqual(requested.requested_by_id, self.people["employee"].id)
        self.assertEqual(requested.before, initial)
        self.assertIsNone(requested.after)
        self.assert_server_time(requested.requested_at, before_request, datetime.now(timezone.utc))
        self.assertTrue((await self.lock_row()).locked)
        state = await self.calendar_state(actor="employee")
        wire = next(row for row in state["change_requests"] if row["id"] == answer["id"])
        self.assertEqual(wire["before"], initial)
        self.assert_server_time(wire["requested_at"], before_request, datetime.now(timezone.utc))

        before_open = datetime.now(timezone.utc)
        await self.resolve(answer["id"], "approve")
        opened = await self.request_row(answer["id"])
        self.assertEqual(opened.status, "approved")
        self.assertEqual(opened.opened_by_id, self.people["helper"].id)
        self.assert_server_time(opened.opened_at, before_open, datetime.now(timezone.utc))
        self.assertFalse((await self.lock_row()).locked)
        await self.send("availability.paint", {
            "user_id": str(self.people["employee"].id),
            "patches": [self.patch(start=720, end=780, value=False)]}, actor="employee")

        before_close = datetime.now(timezone.utc)
        await self.resolve(answer["id"], "close")
        closed = await self.request_row(answer["id"])
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.before, initial)
        self.assertNotEqual(closed.after, initial)
        self.assertEqual(closed.requested_at, requested.requested_at)
        self.assertEqual(closed.opened_at, opened.opened_at)
        self.assertEqual(closed.closed_by_id, self.people["helper"].id)
        self.assert_server_time(closed.closed_at, before_close, datetime.now(timezone.utc))
        self.assertTrue((await self.lock_row()).locked)

        self.actor = self.people["helper"]
        history = await self.client.get("/api/audit-calendar/history")
        self.assertEqual(history.status_code, 200, history.text)
        events = await self.rows(self.models.AuditCalendarEvent)
        history_by_id = {item["id"]: item for item in history.json()["items"]}
        for action, count in [("availability.lock", 1), ("availability.request", 1),
                              ("availability.resolve", 2)]:
            selected = [event for event in events if event.action == action]
            self.assertEqual(len(selected), count)
            for event in selected:
                wire_event = history_by_id[str(event.id)]
                self.assertEqual(wire_event["action"], action)
                self.assertEqual(wire_event["detail"], event.detail)
                self.assert_server_time(event.occurred_at, before_lock, datetime.now(timezone.utc))
                self.assert_server_time(wire_event["occurred_at"], before_lock, datetime.now(timezone.utc))
        request_event = next(event for event in events if event.action == "availability.request")
        self.assertEqual(request_event.actor_id, self.people["employee"].id)
        self.assertEqual(request_event.detail["result"]["before"], initial)
        self.assertEqual(request_event.detail["result"]["status"], "pending")

    async def test_approval_unlocks_only_target_user_day(self):
        for code, day in [("employee", self.day), ("employee", self.next_day), ("tech", self.day)]:
            await self.lock_day(code, day)
        request = await self.request_day()
        await self.resolve(request["id"], "approve")
        self.assertFalse((await self.lock_row()).locked)
        self.assertTrue((await self.lock_row("employee", self.next_day)).locked)
        self.assertTrue((await self.lock_row("tech")).locked)
        await self.paint()
        for code, day in [("employee", self.next_day), ("tech", self.day)]:
            await self.send("availability.paint", {"user_id": str(self.people[code].id),
                "patches": [self.patch(day)]}, status=409)

    async def test_request_requires_locked_day_and_repeated_lock_cannot_reclose_approval(self):
        version = self.version
        await self.send("availability.request", self.person_day(), actor="employee", status=409)
        self.assertEqual((await self.calendar_state())["scope"]["version"], version)
        self.assertEqual(await self.notices("calendar_availability_requested"), [])
        await self.lock_day()
        await self.send("availability.lock", self.person_day(), status=409)
        request = await self.request_day()
        await self.resolve(request["id"], "approve")
        await self.send("availability.lock", self.person_day(), status=409)
        self.assertFalse((await self.lock_row()).locked)
        self.assertEqual((await self.request_row(request["id"])).status, "approved")

    async def test_request_permissions_helper_on_behalf_and_private_state(self):
        await self.lock_day()
        await self.lock_day("tech")
        for code in ["tech", "speaker", "admin", "outsider", "denied"]:
            await self.send("availability.request", self.person_day(), actor=code, status=403)
        own = await self.request_day()
        on_behalf = await self.request_day("tech", actor="helper")
        row = await self.request_row(on_behalf["id"])
        self.assertEqual(row.user_id, self.people["tech"].id)
        self.assertEqual(row.requested_by_id, self.people["helper"].id)
        for code, identities in [("helper", [own["id"], on_behalf["id"]]),
                                 ("employee", [own["id"]]), ("tech", [on_behalf["id"]]),
                                 ("speaker", [])]:
            with self.subTest(actor=code):
                state = await self.calendar_state(actor=code)
                self.assertCountEqual([item["id"] for item in state["change_requests"]], identities)
                self.assertIn("availability_locks", state)
        filtered = await self.calendar_state(actor="employee", person=str(self.people["tech"].id))
        self.assertNotIn(on_behalf["id"], [row["id"] for row in filtered["change_requests"]])

    async def test_lock_resolve_notify_require_explicit_helper_not_admin(self):
        await self.lock_day()
        request = await self.request_day()
        operations = [
            ("availability.lock", self.person_day("tech")),
            ("availability.resolve", {"id": request["id"], "action": "approve", "reason": "Attempt"}),
            ("availability.notify", {"group_id": self.group_id,
                                     "date": self.day.isoformat(), "reason": "Attempt"}),
        ]
        version = self.version
        for actor in ["employee", "tech", "speaker", "admin", "outsider", "denied"]:
            for operation, payload in operations:
                with self.subTest(actor=actor, operation=operation):
                    await self.send(operation, payload, actor=actor, status=403)
        self.assertEqual((await self.calendar_state())["scope"]["version"], version)
        self.assertEqual((await self.request_row(request["id"])).status, "pending")
        self.assertEqual(await self.notices("calendar_group_reconcile_requested"), [])

    async def test_admin_with_calendar_membership_still_is_not_implicitly_helper(self):
        self.actor = self.people["admin"]
        response = await self.client.post("/api/audit-calendar/admin/members", json={
            "request_id": str(uuid4()), "expected_version": self.version,
            "user_id": str(self.people["admin"].id), "code": "ADMIN-OBSERVER",
            "role": "observer", "can_manage": False, "active": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.version = response.json()["version"]
        await self.calendar_state(actor="admin")
        await self.lock_day()
        request = await self.request_day()
        await self.send("availability.lock", self.person_day("tech"), actor="admin", status=403)
        await self.resolve(request["id"], "approve", actor="admin", status=403)
        await self.send("availability.notify", {"group_id": self.group_id,
            "date": self.day.isoformat(), "reason": "No implicit helper"}, actor="admin", status=403)
        self.assertTrue((await self.lock_row()).locked)

    async def test_client_times_snapshots_status_and_actor_injection_rejected(self):
        await self.lock_day()
        request = await self.request_day()
        cases = [
            ("availability.lock", self.person_day("tech"),
             {"locked_at": "2001-01-01T00:00:00Z", "snapshot": [], "locked_by_id": str(uuid4())}),
            ("availability.request", self.person_day(),
             {"requested_at": "2001-01-01T00:00:00Z", "requested_by_id": str(uuid4()),
              "before": [], "status": "approved"}),
            ("availability.resolve", {"id": request["id"], "action": "approve", "reason": "Attempt"},
             {"opened_at": "2001-01-01T00:00:00Z", "closed_at": "2001-01-01T00:00:00Z",
              "after": [], "opened_by_id": str(uuid4())}),
        ]
        before = await self.calendar_state()
        for operation, payload, extras in cases:
            for field, value in extras.items():
                with self.subTest(operation=operation, field=field):
                    await self.send(operation, {**payload, field: value}, status=422)
            self.actor = self.people["helper"]
            body = self.body(operation, payload)
            body["actor_id"] = str(self.people["admin"].id)
            self.assertEqual((await self.command(body)).status_code, 422)
        after = await self.calendar_state()
        for field in ("availability_locks", "change_requests", "availability"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["scope"]["version"], before["scope"]["version"])

    async def test_single_active_request_replay_stale_and_notifications_do_not_duplicate(self):
        await self.lock_day()
        self.actor = self.people["employee"]
        body = self.body("availability.request", self.person_day())
        first = await self.command(body)
        self.assertEqual(first.status_code, 200, first.text)
        self.version = first.json()["version"]
        sent = await self.notices("calendar_availability_requested")
        await self.assert_notices_for(sent, ["helper"])
        replay = await self.command(body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), first.json())
        changed = copy.deepcopy(body)
        changed["payload"]["reason"] = "Different replay"
        self.assertEqual((await self.command(changed)).status_code, 409)
        stale = {**body, "request_id": str(uuid4())}
        self.assertEqual((await self.command(stale)).status_code, 409)
        await self.send("availability.request", self.person_day(), actor="employee", status=409)
        await self.send("availability.request", self.person_day(), actor="helper", status=409)
        self.assertEqual(await self.notices("calendar_availability_requested"), sent)
        await self.assert_notices_for(sent, ["helper"])
        await self.resolve(first.json()["result"]["id"], "approve")
        await self.send("availability.request", self.person_day(), actor="employee", status=409)
        self.assertEqual(len(await self.rows(self.models.AuditCalendarChangeRequest)), 1)
        events = await self.rows(self.models.AuditCalendarEvent)
        self.assertEqual(sum(event.action == "availability.request" for event in events), 1)

    async def test_resolution_transitions_and_replay_do_not_duplicate_notifications(self):
        await self.lock_day()
        request = await self.request_day()
        await self.resolve(request["id"], "close", status=409)
        self.actor = self.people["helper"]
        body = self.body("availability.resolve", {
            "id": request["id"], "action": "approve", "reason": "Synthetic approval"})
        first = await self.command(body)
        self.assertEqual(first.status_code, 200, first.text)
        self.version = first.json()["version"]
        notices = await self.notices("calendar_availability_resolved")
        await self.assert_notices_for(notices, ["employee"])
        replay = await self.command(body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), first.json())
        stale = {**body, "request_id": str(uuid4())}
        self.assertEqual((await self.command(stale)).status_code, 409)
        await self.resolve(request["id"], "approve", status=409)
        await self.resolve(request["id"], "reject", status=409)
        self.assertEqual(await self.notices("calendar_availability_resolved"), notices)
        await self.resolve(request["id"], "close")
        sent = await self.notices("calendar_availability_resolved")
        await self.assert_notices_for(sent, ["employee", "employee"])
        for action in ["approve", "close", "reject"]:
            await self.resolve(request["id"], action, status=409)
        self.assertEqual(await self.notices("calendar_availability_resolved"), sent)
        await self.assert_notices_for(sent, ["employee", "employee"])

    async def test_reject_pending_preserves_lock_and_allows_a_new_request(self):
        await self.paint()
        await self.lock_day()
        first = await self.request_day()
        await self.resolve(first["id"], "reject")
        rejected = await self.request_row(first["id"])
        self.assertEqual(rejected.status, "rejected")
        self.assertIsNone(rejected.opened_at)
        self.assertIsNotNone(rejected.closed_at)
        self.assertTrue((await self.lock_row()).locked)
        notices = await self.notices("calendar_availability_resolved")
        await self.assert_notices_for(notices, ["employee"])
        second = await self.request_day()
        self.assertNotEqual(first["id"], second["id"])
        for action in ["approve", "close", "reject"]:
            await self.resolve(first["id"], action, status=409)
        self.assertEqual((await self.request_row(second["id"])).status, "pending")
        self.assertEqual((await self.request_row(first["id"])).before, rejected.before)
        self.assertEqual(await self.notices("calendar_availability_resolved"), notices)
        await self.assert_notices_for(notices, ["employee"])

    async def test_new_cycle_keeps_old_snapshots_and_old_id_cannot_close_new_approval(self):
        await self.paint()
        await self.lock_day()
        first = await self.request_day()
        await self.resolve(first["id"], "approve")
        await self.paint(start=720, end=780, value=False)
        await self.resolve(first["id"], "close")
        old = await self.request_row(first["id"])
        second = await self.request_day()
        new = await self.request_row(second["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(new.before, old.after)
        await self.resolve(second["id"], "approve")
        await self.paint(start=840, end=900, value=False)
        for action in ["approve", "close", "reject"]:
            await self.resolve(first["id"], action, status=409)
        self.assertFalse((await self.lock_row()).locked)
        await self.resolve(second["id"], "close")
        preserved = await self.request_row(first["id"])
        for field in ("before", "after", "reason", "requested_at", "opened_at", "closed_at", "status"):
            self.assertEqual(getattr(preserved, field), getattr(old, field), field)

    async def test_closed_request_snapshots_and_history_reject_direct_database_mutation(self):
        from sqlalchemy import update
        from sqlalchemy.exc import DBAPIError

        await self.paint()
        await self.lock_day()
        request = await self.request_day()
        await self.resolve(request["id"], "approve")
        await self.paint(start=720, end=780, value=False)
        await self.resolve(request["id"], "close")
        model = self.models.AuditCalendarChangeRequest
        saved = await self.request_row(request["id"])
        for updates in [{"before": []}, {"after": []}, {"requested_at": saved.requested_at - timedelta(days=1)}]:
            with self.subTest(fields=list(updates)), self.assertRaises(DBAPIError):
                async with self.factory.begin() as db:
                    await db.execute(update(model).where(model.scope_id == self.scope_id,
                        model.id == UUID(request["id"])).values(**updates))
        event_model = self.models.AuditCalendarEvent
        with self.assertRaises(DBAPIError):
            async with self.factory.begin() as db:
                await db.execute(update(event_model).where(event_model.scope_id == self.scope_id,
                    event_model.action == "availability.request").values(detail={"tampered": True}))
        preserved = await self.request_row(request["id"])
        for field in ["before", "after", "requested_at", "status"]:
            self.assertEqual(getattr(preserved, field), getattr(saved, field), field)

    async def test_pending_request_cannot_be_approved_in_db_without_opened_at(self):
        from sqlalchemy import update
        from sqlalchemy.exc import DBAPIError

        await self.lock_day()
        request = await self.request_day()
        saved = await self.request_row(request["id"])
        model = self.models.AuditCalendarChangeRequest
        with self.assertRaises(DBAPIError):
            async with self.factory.begin() as db:
                await db.execute(update(model).where(model.scope_id == self.scope_id,
                    model.id == UUID(request["id"])).values(
                        status="approved", opened_at=None,
                        opened_by_id=self.people["helper"].id, resolution="Missing opening time"))

        preserved = await self.request_row(request["id"])
        for field in ["status", "opened_at", "opened_by_id", "requested_at", "before", "resolution"]:
            self.assertEqual(getattr(preserved, field), getattr(saved, field), field)
        self.assertTrue((await self.lock_row()).locked)
        self.assertEqual((await self.calendar_state())["scope"]["version"], self.version)
        self.assertEqual(await self.notices("calendar_availability_resolved"), [])
        await self.resolve(request["id"], "approve")
        approved = await self.request_row(request["id"])
        self.assertEqual(approved.status, "approved")
        self.assertIsNotNone(approved.opened_at)
        self.assertEqual(approved.opened_by_id, self.people["helper"].id)
        self.assertFalse((await self.lock_row()).locked)

    async def test_locked_multiday_paint_is_atomic_for_owner_and_helper(self):
        await self.paint()
        await self.paint(day=self.next_day)
        await self.lock_day(day=self.next_day)
        before = await self.calendar_state()
        for actor in ["employee", "helper"]:
            for value in [True, False, None]:
                with self.subTest(actor=actor, value=value):
                    await self.send("availability.paint", {
                        "user_id": str(self.people["employee"].id),
                        "patches": [self.patch(value=value), self.patch(self.next_day, value=value)]},
                        actor=actor, status=409)
        after = await self.calendar_state()
        self.assertEqual(after["availability"], before["availability"])
        self.assertEqual(after["scope"]["version"], before["scope"]["version"])
        self.assertEqual(after["availability_locks"], before["availability_locks"])

    async def test_locked_absence_add_and_end_are_atomic(self):
        absence = await self.send("absence.add", {
            "user_id": str(self.people["employee"].id), "start_date": self.day.isoformat(),
            "end_date": self.next_day.isoformat(), "reason": "Existing synthetic absence"})
        await self.lock_day()
        await self.lock_day("tech")
        before = await self.calendar_state()
        for actor in ["tech", "helper"]:
            await self.send("absence.add", {"user_id": str(self.people["tech"].id),
                "start_date": (self.day - timedelta(days=1)).isoformat(),
                "end_date": self.next_day.isoformat(), "reason": "Locked interval"}, actor=actor, status=409)
        for actor in ["employee", "helper"]:
            await self.send("absence.end", {"id": absence["id"], "reason": "Locked interval"},
                            actor=actor, status=409)
        after = await self.calendar_state()
        self.assertEqual(after["absences"], before["absences"])
        self.assertEqual(after["scope"]["version"], before["scope"]["version"])

    async def test_scope_archive_routes_admin_without_membership_and_denies_helper(self):
        payload = {"archived": True, "reason": "Synthetic archive"}
        for actor in ["helper", "employee", "outsider"]:
            await self.send("scope.archive", payload, actor=actor, status=403)
        await self.send("scope.archive", payload, actor="admin")
        self.assertTrue((await self.calendar_state())["scope"]["archived"])
        await self.send("availability.lock", self.person_day(), status=409)
        self.actor = self.people["admin"]
        self.assertEqual((await self.client.get("/api/audit-calendar/state", params={
            "from": self.day.isoformat(), "to": self.day.isoformat()})).status_code, 403)
        await self.send("scope.archive", {**payload, "archived": False}, actor="admin")
        self.assertFalse((await self.calendar_state())["scope"]["archived"])
        await self.lock_day()

    async def test_group_reconcile_notifications_use_shared_service_and_are_replay_safe(self):
        await self.paint(value=False)
        await self.paint("tech")
        self.assertEqual(self.group_status(await self.readiness()), "no_overlap")
        self.actor = self.people["helper"]
        body = self.body("availability.notify", {"group_id": self.group_id,
            "date": self.day.isoformat(), "reason": "Please reconcile this day"})
        first = await self.command(body)
        self.assertEqual(first.status_code, 200, first.text)
        self.version = first.json()["version"]
        sent = await self.notices("calendar_group_reconcile_requested")
        await self.assert_notices_for(sent, ["employee", "tech"])
        replay = await self.command(body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual((await self.command({**body, "request_id": str(uuid4())})).status_code, 409)
        changed = copy.deepcopy(body)
        changed["payload"]["reason"] = "Changed replay"
        self.assertEqual((await self.command(changed)).status_code, 409)
        await self.send("availability.notify", body["payload"], status=409)
        self.assertEqual(await self.notices("calendar_group_reconcile_requested"), sent)
        await self.assert_notices_for(sent, ["employee", "tech"])
        events = await self.rows(self.models.AuditCalendarEvent)
        self.assertEqual(sum(event.action == "availability.notify" for event in events), 1)

    async def test_group_notify_uses_same_duration_as_readiness(self):
        for code in ["employee", "tech"]:
            await self.paint(code, value=False)
        await self.pair_free(start=720, end=750)
        short = await self.readiness(duration=30)
        long = await self.readiness(duration=60)
        for code in ["employee", "tech"]:
            self.assertEqual(self.employee_status(short, code), "filled")
            self.assertEqual(self.employee_status(long, code), "filled")
        self.assertEqual(self.group_status(short), "available")
        self.assertEqual(self.group_day(short)["slots"], [{"start": 720, "end": 750}])
        self.assertEqual(self.group_status(long), "no_overlap")
        self.assertEqual(self.group_day(long)["common_windows"], [{"start": 720, "end": 750}])
        self.assertEqual(self.group_day(long)["slots"], [])

        payload = {"group_id": self.group_id, "date": self.day.isoformat(),
                   "reason": "Reconcile the selected meeting duration"}
        version = self.version
        await self.send("availability.notify", {**payload, "duration": 30}, status=409)
        await self.send("availability.notify", payload, status=409)
        for duration in [True, "60", 0, 45, 510]:
            with self.subTest(invalid_duration=duration):
                await self.send("availability.notify", {**payload, "duration": duration}, status=422)
        self.assertEqual((await self.calendar_state())["scope"]["version"], version)
        self.assertEqual(await self.notices("calendar_group_reconcile_requested"), [])

        result = await self.send("availability.notify", {**payload, "duration": 60})
        self.assertEqual(result["duration"], 60)
        self.assertEqual(self.version, version + 1)
        notices = await self.notices("calendar_group_reconcile_requested")
        await self.assert_notices_for(notices, ["employee", "tech"], duration=60)
        for notice in notices:
            self.assertRegex(notice["message"], r"\b60\b")
        model = self.models.AuditCalendarEvent
        events = await self.rows(model, model.action == "availability.notify")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].detail["command"]["payload"]["duration"], 60)
        self.assertEqual(events[0].detail["result"]["duration"], 60)

    async def test_import_apply_rechecks_lock_after_preview_without_partial_writes(self):
        from test_audit_calendar_schema import source_fixture

        for kind in ["availability", "absence"]:
            with self.subTest(kind=kind):
                target = self.day if kind == "availability" else self.next_day
                source = source_fixture()
                source["data"]["plans"] = []
                if kind == "availability":
                    source["data"]["availability"] = [
                        {"personId": "S1", "date": (target - timedelta(days=1)).isoformat(),
                         "start": 600, "end": 1080, "available": True},
                        {"personId": "S1", "date": target.isoformat(),
                         "start": 600, "end": 1080, "available": True}]
                else:
                    source["data"]["planning"] = {"trackingStart": self.today.isoformat(),
                        "dailyTargets": [{"from": self.today.isoformat(), "value": 6}],
                        "groupTargets": [], "absences": [
                            {"id": "synthetic-absence", "personId": "S1", "from": target.isoformat(),
                             "to": target.isoformat(), "reason": "Synthetic imported absence"}]}
                self.actor = self.people["helper"]
                response = await self.client.post("/api/audit-calendar/imports/preview", json={
                    "request_id": str(uuid4()), "expected_version": self.version, "source": source,
                    "mapping": {"S1": str(self.people["employee"].id)}})
                self.assertEqual(response.status_code, 200, response.text)
                preview = response.json()
                self.assertEqual(preview["status"], "ready", preview)
                self.version = preview["version"]
                await self.lock_day(day=target)
                before = await self.calendar_state(start=self.day - timedelta(days=1))
                self.actor = self.people["helper"]
                response = await self.client.post(
                    f"/api/audit-calendar/imports/{preview['id']}/apply", json={
                        "request_id": str(uuid4()), "expected_version": self.version,
                        "confirm": True, "reason": "Synthetic import"})
                self.assertEqual(response.status_code, 409, response.text)
                after = await self.calendar_state(start=self.day - timedelta(days=1))
                for field in ["availability", "absences", "plans"]:
                    self.assertEqual(after[field], before[field], field)
                self.assertEqual(after["scope"]["version"], before["scope"]["version"])
                model = self.models.AuditCalendarImportApplication
                self.assertEqual(await self.rows(model, model.batch_id == UUID(preview["id"])), [])

    async def test_future_source_draft_with_observer_speaker_blocks_import_preview(self):
        from test_audit_calendar_schema import source_fixture

        source = source_fixture()
        source["data"]["plans"][0].update(
            date=self.day.isoformat(), groupId="G1", status="draft", origin="source")
        self.actor = self.people["helper"]
        response = await self.client.post("/api/audit-calendar/imports/preview", json={
            "request_id": str(uuid4()), "expected_version": self.version, "source": source,
            "mapping": {"S1": str(self.people["helper"].id)}})
        self.assertEqual(response.status_code, 200, response.text)
        blocked = response.json()
        self.version = blocked["version"]
        self.assertEqual(blocked["status"], "blocked", blocked)
        self.assertEqual(blocked["mapping_required"], [])
        self.assertIn("MEMBER_ROLE", [issue["code"] for issue in blocked["issues"]])
        self.assertEqual(await self.rows(self.models.AuditCalendarPlan), [])
        mapping_model = self.models.AuditCalendarImportMapping
        mappings = await self.rows(mapping_model, mapping_model.batch_id == UUID(blocked["id"]))
        self.assertEqual(len(mappings), 1)
        self.assertIn("MEMBER_ROLE", [issue["code"] for issue in mappings[0].summary["issues"]])

        response = await self.client.post("/api/audit-calendar/imports/preview", json={
            "request_id": str(uuid4()), "expected_version": self.version, "source": source,
            "mapping": {"S1": str(self.people["speaker"].id)}})
        self.assertEqual(response.status_code, 200, response.text)
        ready = response.json()
        self.version = ready["version"]
        self.assertEqual(ready["id"], blocked["id"])
        self.assertEqual(ready["status"], "ready", ready)
        self.assertEqual(ready["issues"], [])
        self.assertEqual(await self.rows(self.models.AuditCalendarPlan), [])

    async def readiness(self, *, start=None, end=None, duration=30, actor="helper", status=200):
        self.actor = self.people[actor]
        params = {"from": (start or self.day).isoformat(), "to": (end or self.day).isoformat()}
        if duration is not None:
            params["duration"] = duration
        response = await self.client.get("/api/audit-calendar/readiness", params=params)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def employee_status(self, result, code="employee", day=None):
        employees = [row for row in result["employees"] if row["user_id"] == str(self.people[code].id)]
        self.assertEqual(len(employees), 1, result)
        rows = [row for row in employees[0]["days"] if row["date"] == (day or self.day).isoformat()]
        self.assertEqual(len(rows), 1, result)
        return rows[0]["status"]

    def group_day(self, result, group=None, day=None):
        groups = [row for row in result["groups"] if row["group_id"] == (group or self.group_id)]
        self.assertEqual(len(groups), 1, result)
        rows = [row for row in groups[0]["days"] if row["date"] == (day or self.day).isoformat()]
        self.assertEqual(len(rows), 1, result)
        return rows[0]

    def group_status(self, result, group=None, day=None):
        return self.group_day(result, group, day)["status"]

    async def pair_free(self, start=600, end=1080):
        for code in ["employee", "tech"]:
            await self.paint(code, start=start, end=end)

    async def save_meeting(self, **updates):
        payload = {**self.fixture.meeting(self), "date": self.day.isoformat(), "duration": 30, **updates}
        return await self.send("plan.save", payload)

    async def test_readiness_unknown_is_missing_not_free_or_busy(self):
        result = await self.readiness()
        self.assertEqual(self.employee_status(result), "missing")
        self.assertEqual(self.employee_status(result, "tech"), "missing")
        self.assertEqual(self.group_status(result), "missing")

    async def test_readiness_partial_and_filled_employee_statuses(self):
        await self.paint(end=630)
        self.assertEqual(self.employee_status(await self.readiness()), "partial")
        await self.paint(start=630, value=False)
        self.assertEqual(self.employee_status(await self.readiness()), "filled")

    async def test_readiness_full_busy_is_filled_but_no_overlap_not_missing(self):
        await self.paint(value=False)
        await self.paint("tech")
        result = await self.readiness()
        self.assertEqual(self.employee_status(result), "filled")
        self.assertEqual(self.group_status(result), "no_overlap")

    async def test_readiness_known_free_windows_without_intersection(self):
        for code in ["employee", "tech"]:
            await self.paint(code, value=False)
        await self.paint(end=720)
        await self.paint("tech", start=720, end=840)
        self.assertEqual(self.group_status(await self.readiness()), "no_overlap")

    async def test_readiness_contiguous_thirty_minutes_available_not_fragment_sum(self):
        for code in ["employee", "tech"]:
            await self.paint(code, value=False)
        await self.pair_free(end=630)
        await self.pair_free(start=660, end=690)
        self.assertEqual(self.group_status(await self.readiness()), "available")
        self.assertEqual(self.group_status(await self.readiness(duration=60)), "no_overlap")

    async def test_readiness_absence_overrides_full_free_windows(self):
        await self.pair_free()
        await self.send("absence.add", {"user_id": str(self.people["employee"].id),
            "start_date": self.day.isoformat(), "end_date": self.day.isoformat(), "reason": "Synthetic absence"})
        result = await self.readiness()
        self.assertEqual(self.employee_status(result), "absent")
        self.assertEqual(self.group_status(result), "absent")

    async def test_readiness_group_without_composition(self):
        group = await self.send("group.save", {"code": "FUTURE", "label": "Future composition",
            "effective_from": self.next_day.isoformat(), "auditor_id": str(self.people["employee"].id),
            "tech_id": str(self.people["tech"].id), "reason": "No effective composition on the queried day"})
        self.assertEqual(self.group_status(await self.readiness(), group["id"]), "no_composition")

    async def test_readiness_booked_then_available_after_cancellation(self):
        await self.pair_free(end=630)
        plan = await self.save_meeting()
        self.assertEqual(self.group_status(await self.readiness()), "booked")
        await self.save_meeting(id=plan["id"], status="cancelled")
        self.assertEqual(self.group_status(await self.readiness()), "available")

    async def test_readiness_subtracts_cross_group_draft_with_shared_participants(self):
        await self.pair_free(end=630)
        other = await self.send("group.save", {"code": "G2", "label": "Shared participants",
            "effective_from": self.today.isoformat(), "auditor_id": str(self.people["employee"].id),
            "tech_id": str(self.people["tech"].id), "reason": "Synthetic cross-group booking"})
        plan = await self.save_meeting(group_id=other["id"], status="draft")
        readiness = await self.readiness()
        self.assertEqual(self.group_status(readiness), "booked")
        row = self.group_day(readiness)
        self.assertEqual(row["plans"], [])
        self.assertEqual(row["common_windows"], [{"start": 600, "end": 630}])
        self.assertEqual(row["free_windows"], [])
        self.assertEqual(row["slots"], [])
        await self.save_meeting(id=plan["id"], group_id=other["id"], status="cancelled")
        self.assertEqual(self.group_status(await self.readiness()), "available")

    async def test_readiness_workday_clips_outside_ten_to_eighteen_moscow(self):
        await self.pair_free(start=540, end=600)
        await self.pair_free(start=1080, end=1140)
        result = await self.readiness()
        self.assertEqual(result["working_start"], 600)
        self.assertEqual(result["working_end"], 1080)
        self.assertEqual(self.employee_status(result), "missing")
        self.assertNotEqual(self.group_status(result), "available")
        await self.pair_free(start=1050, end=1080)
        self.assertEqual(self.group_status(await self.readiness()), "available")

    async def test_readiness_weekend_excluded_default_duration_and_permissions(self):
        result = await self.readiness(end=self.day + timedelta(days=6), duration=None)
        explicit = await self.readiness(end=self.day + timedelta(days=6), duration=30)
        self.assertEqual(result, explicit)
        self.assertEqual(result["duration"], 30)
        for collection in ["employees", "groups"]:
            self.assertTrue(result[collection])
            for item in result[collection]:
                self.assertEqual([row["date"] for row in item["days"]], [
                    (self.day + timedelta(days=offset)).isoformat() for offset in range(5)])
        for actor in ["employee", "tech", "speaker"]:
            await self.readiness(actor=actor)
        for actor in ["admin", "outsider", "denied"]:
            await self.readiness(actor=actor, status=403)

    async def test_readiness_range_and_duration_bounds_do_not_write(self):
        before = self.version
        await self.readiness(end=self.day + timedelta(days=30))
        await self.readiness(end=self.day + timedelta(days=31), status=422)
        await self.readiness(end=self.day - timedelta(days=1), status=422)
        for duration in [0, -30, 15, 31, 510, "invalid"]:
            await self.readiness(duration=duration, status=422)
        self.actor = self.people["helper"]
        for start, end in [("1900-01-01", "1900-01-02"), ("2101-01-01", "2101-01-02"),
                           ("2026-09-99", "2026-09-30")]:
            response = await self.client.get("/api/audit-calendar/readiness", params={"from": start, "to": end})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.calendar_state())["scope"]["version"], before)

    async def test_new_plan_defaults_to_thirty_and_draft_rejects_wrong_speaker_role(self):
        payload = {**self.fixture.meeting(self), "date": self.day.isoformat()}
        del payload["duration"]
        saved = await self.send("plan.save", payload)
        self.assertEqual(saved["duration"], 30)
        for code in ["employee", "tech", "helper", "admin", "outsider"]:
            with self.subTest(speaker=code):
                await self.send("plan.save", {**payload, "status": "draft", "start": 720,
                    "speaker_id": str(self.people[code].id)}, status=422)
        rows = await self.rows(self.models.AuditCalendarPlan)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].duration, 30)

    async def test_existing_ninety_minute_plan_update_without_duration_is_rejected_unchanged(self):
        saved = await self.save_meeting(duration=90)
        before = await self.calendar_state()
        history = await self.rows(self.models.AuditCalendarEvent)
        payload = {**self.fixture.meeting(self), "id": saved["id"],
                   "date": self.day.isoformat(), "activity": "Must not replace existing activity"}
        del payload["duration"]
        await self.send("plan.save", payload, status=422)

        after = await self.calendar_state()
        self.assertEqual(after["plans"], before["plans"])
        self.assertEqual(after["scope"]["version"], before["scope"]["version"])
        model = self.models.AuditCalendarPlan
        rows = await self.rows(model, model.id == UUID(saved["id"]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].duration, 90)
        self.assertEqual(rows[0].version, saved["version"])
        self.assertEqual(rows[0].activity, saved["activity"])
        self.assertCountEqual([event.id for event in await self.rows(self.models.AuditCalendarEvent)],
                              [event.id for event in history])


if __name__ == "__main__":
    unittest.main()
