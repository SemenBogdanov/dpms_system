"""Usage contract/API tests; PostgreSQL cases only use an opt-in disposable DB."""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi.errors import RateLimitExceeded
from sqlalchemy import Column, MetaData, String, Table, Uuid, func, insert, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CTE

from app.api.deps import get_current_user, get_db
from app.api.routes import usage
from app.api.routes import activity as activity_routes
from app.models.activity import ActivityEvent
from app.models.user import League, User, UserRole
from app.schemas.usage import SectionViewCreate, USAGE_SECTION_IDS
from app.services import usage as service
from app.services import activity as activity_service
from app.services.activity import list_activity_events
from app.services.sidebar_menu import accessible_sidebar_item_ids


def actor(role=UserRole.executor, **flags):
    return SimpleNamespace(
        id=uuid4(), role=role, task_workspace_enabled=flags.get("task_workspace_enabled", False),
        audit_enabled=flags.get("audit_enabled", False),
        audit_calendar_enabled=flags.get("audit_calendar_enabled", False),
        competency_development_enabled=flags.get("competency_development_enabled", False),
        competency_constructor_enabled=flags.get("competency_constructor_enabled", False),
        feedback_enabled=flags.get("feedback_enabled", False),
    )


def empty_snapshot():
    return {
        "login_count": 0, "login_users": 0, "section_view_count": 0, "section_users": 0,
        "first_login_at": None, "first_section_view_at": None,
        "sections": None, "users": None, "daily": None, "login_total": 0, "login_items": None,
    }


class UsageUnitTests(unittest.TestCase):
    def test_moscow_inclusive_days_are_half_open_utc(self):
        start, end = service.period_bounds(date(2026, 1, 2), date(2026, 1, 3))
        self.assertEqual(start, datetime(2026, 1, 1, 21, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 1, 3, 21, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(days=2))

    def test_maximum_inclusive_period_and_invalid_dates(self):
        today = date(2026, 9, 27)
        service.period_bounds(today - timedelta(days=365), today, today=today)
        for start, end in (
            (today - timedelta(days=366), today), (today, today - timedelta(days=1)),
            (today, today + timedelta(days=1)), (date.max, date.max), (date.min, date.min),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                service.period_bounds(start, end, today=today)
        with self.assertRaises(ValueError):
            service.period_bounds(date.max, date.max, today=date.max)

    def test_payload_forbids_metadata_and_only_accepts_known_exact_ids(self):
        payload = {"event_id": str(uuid4()), "section": "graphs"}
        self.assertEqual(SectionViewCreate(**payload).section, "graphs")
        for section in ("/graphs", "graphs?private=yes", "Graphs", " graphs", "", None, 4, b"graphs"):
            with self.subTest(section=section), self.assertRaises(ValidationError):
                SectionViewCreate(**{**payload, "section": section})
        for field, value in (
            ("actor_id", str(uuid4())), ("occurred_at", "2000-01-01T00:00:00Z"),
            ("metadata", {}), ("url", "/graphs/private"), ("query", "private=yes"),
            ("user_agent", "private"), ("client_host", "192.0.2.2"),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                SectionViewCreate(**payload, **{field: value})
        with self.assertRaises(ValidationError):
            SectionViewCreate(event_id="not-a-uuid", section="graphs")

    def test_idempotency_is_stable_and_actor_scoped(self):
        user_id, event_id = uuid4(), uuid4()
        stored_id = service.section_view_id(user_id, event_id)
        self.assertEqual(stored_id.version, 5)
        self.assertEqual(stored_id, service.section_view_id(user_id, event_id))
        self.assertNotEqual(stored_id, service.section_view_id(uuid4(), event_id))
        self.assertNotEqual(stored_id, service.section_view_id(user_id, uuid4()))

    def test_all_known_sections_have_labels(self):
        self.assertEqual(set(service.SECTION_LABELS), set(USAGE_SECTION_IDS))

    def test_coarse_browser_os_device_with_precedence_and_no_model_or_version(self):
        for ua, expected in (
            ("Mozilla/5.0 (iPad; CPU OS 17) Version/17 Safari/605", ("Планшет", "Safari", "iPadOS")),
            ("Mozilla/5.0 (iPhone; CPU iPhone OS 17) CriOS/120 Safari/605", ("Телефон", "Chrome", "iOS")),
            ("Mozilla/5.0 (iPhone) FxiOS/120 Safari/605", ("Телефон", "Firefox", "iOS")),
            ("Mozilla/5.0 (Linux; Android 14; ExactPhoneModel) Chrome/120 Mobile Safari/537", ("Телефон", "Chrome", "Android")),
            ("Mozilla/5.0 (Linux; Android 14; ExactTabletModel) Chrome/120 Safari/537", ("Планшет", "Chrome", "Android")),
            ("Mozilla/5.0 (Windows NT 10) Chrome/120 Safari/537 Edg/120", ("Компьютер", "Edge", "Windows")),
            ("Mozilla/5.0 (Windows NT 10) Chrome/120 Safari/537 OPR/105", ("Компьютер", "Opera", "Windows")),
            ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14) Version/17 Safari/605", ("Компьютер", "Safari", "macOS")),
            ("Mozilla/5.0 (X11; Linux x86_64) Firefox/120", ("Компьютер", "Firefox", "Linux")),
        ):
            with self.subTest(ua=ua):
                answer = service.classify_user_agent(ua)
                self.assertEqual((answer["device"], answer["browser"], answer["os"]), expected)
        for ua in (None, "", "private-data-example", {}, ["Chrome/120"], "x" * 2048 + "Chrome/120"):
            self.assertEqual(service.classify_user_agent(ua), dict.fromkeys(("device", "browser", "os"), service.UNKNOWN))

    def test_query_aggregates_and_only_pages_raw_user_agent(self):
        start, end = service.period_bounds(date(2026, 1, 1), date(2026, 1, 2))
        statement = service.report_statement(start, end, uuid4(), 25, 10)
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        self.assertRegex(sql.lower(), r"count\(\s*distinct\b")
        self.assertIn("GROUP BY", sql)
        self.assertIn("jsonb_agg", sql)
        self.assertIn("jsonb_build_object(CAST(", sql)
        self.assertIn("timezone(", sql)
        self.assertIn("LIMIT", sql)
        self.assertIn("OFFSET", sql)
        self.assertIn("activity_events.occurred_at DESC, activity_events.id DESC", sql)
        ctes = {node.name: node for node in visitors.iterate(statement) if isinstance(node, CTE)}
        page = ctes["usage_login_page"].element
        self.assertIn("user_agent", page.selected_columns.keys())
        for name, cte in ctes.items():
            if name != "usage_login_page":
                self.assertNotIn("user_agent", cte.element.selected_columns.keys(), name)
        page_sql = str(page.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("->> 'user_agent'", page_sql)
        self.assertRegex(page_sql, r"LIMIT\s+25\b")
        self.assertRegex(page_sql, r"OFFSET\s+10\b")
        self.assertNotIn("client_host", compiled.params.values())


class UsageServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_is_immutable_server_owned_and_metadata_minimal(self):
        db, user = AsyncMock(), actor()
        payload = SectionViewCreate(event_id=uuid4(), section="graphs")
        before = datetime.now(timezone.utc)
        await service.record_section_view(db, user, payload)
        statement = db.execute.call_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertIn("ON CONFLICT (id) DO NOTHING", str(compiled))
        self.assertNotIn("DO UPDATE", str(compiled))
        self.assertEqual(compiled.params["id"], service.section_view_id(user.id, payload.event_id))
        self.assertEqual(compiled.params["actor_id"], user.id)
        self.assertEqual(compiled.params["event_type"], "usage_section_view")
        self.assertEqual(compiled.params["metadata"], {"section": "graphs"})
        self.assertGreaterEqual(compiled.params["occurred_at"], before)
        self.assertLessEqual(compiled.params["occurred_at"], datetime.now(timezone.utc))
        db.commit.assert_not_called()

    async def test_capture_matches_sidebar_permissions_and_special_sections(self):
        for role in UserRole:
            for granted in (False, True):
                user = actor(role, task_workspace_enabled=granted, audit_enabled=granted,
                             audit_calendar_enabled=granted, competency_development_enabled=granted,
                             feedback_enabled=granted)
                allowed = accessible_sidebar_item_ids(user) | {"settings"}
                if role == UserRole.admin or granted:
                    allowed |= {"profile"}
                if role == UserRole.admin:
                    allowed |= {"admin-users", "admin-integrations"}
                for section in USAGE_SECTION_IDS:
                    with self.subTest(role=role, granted=granted, section=section):
                        db = AsyncMock()
                        payload = SectionViewCreate(event_id=uuid4(), section=section)
                        if section in allowed:
                            await service.record_section_view(db, user, payload)
                            db.execute.assert_awaited_once()
                        else:
                            with self.assertRaises(HTTPException) as error:
                                await service.record_section_view(db, user, payload)
                            self.assertEqual(error.exception.status_code, 403)
                            db.execute.assert_not_called()

    async def test_one_query_empty_days_and_selected_page_privacy(self):
        db = AsyncMock()
        raw = empty_snapshot()
        raw.update(login_count=7, login_users=3, login_total=2, login_items=[{
            "id": str(uuid4()), "user_id": str(uuid4()), "name": "Person", "email": "person@example.invalid",
            "occurred_at": "2026-01-02T00:30:00+00:00", "user_agent": "ExactPrivateModel Chrome/123",
        }])
        result = Mock()
        result.mappings.return_value.one.return_value = raw
        db.execute.return_value = result
        report = await service.get_usage_report(
            db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 3), user_id=uuid4(), limit=1,
        )
        db.execute.assert_awaited_once()
        self.assertEqual(report.login_count, 7)
        self.assertEqual(report.logins.total, 2)
        self.assertEqual(len(report.logins.items), 1)
        self.assertEqual(len(report.daily), 3)
        self.assertTrue(all(day.logins == day.section_views == 0 for day in report.daily))
        output = report.model_dump_json()
        self.assertNotIn("user_agent", output)
        self.assertNotIn("ExactPrivateModel", output)
        self.assertEqual(report.logins.items[0].browser, "Chrome")

    async def test_generic_activity_hides_usage_in_items_and_count_by_default(self):
        for event_type in (None, "login_success", "usage_section_view"):
            for include_usage in (False, True):
                result, count = Mock(), Mock()
                result.scalars.return_value.all.return_value = []
                count.scalar.return_value = 0
                db = AsyncMock()
                db.execute.side_effect = [result, count]
                options = {"include_usage": True} if include_usage else {}
                await list_activity_events(db, event_type=event_type, **options)
                for call in db.execute.call_args_list:
                    sql = str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                    if include_usage:
                        self.assertNotIn("NOT IN", sql)
                    else:
                        self.assertIn("NOT IN", sql)
                        self.assertIn("'login_success'", sql)
                        self.assertIn("'usage_section_view'", sql)

    async def test_employee_summary_excludes_usage_in_sql_before_recent_activity_slice(self):
        user = actor()
        user.full_name, user.league, user.mpw = "Employee", League.C, 0
        user.is_new_employee, user.plan_started_at = False, None
        user_result, empty = Mock(), Mock()
        user_result.scalar_one_or_none.return_value = user
        empty.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [user_result, empty, empty, empty, empty, empty]
        with patch.object(activity_service, "absence_dates_for_user", new_callable=AsyncMock, return_value=set()):
            report = await activity_service.generate_employee_period_summary(
                db, user_id=user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 3),
            )
        sql = str(db.execute.call_args_list[1].args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        ))
        self.assertIn("NOT IN", sql)
        self.assertIn("'login_success'", sql)
        self.assertIn("'usage_section_view'", sql)
        self.assertLess(sql.index("NOT IN"), sql.index("ORDER BY"))
        if "LIMIT" in sql:
            self.assertLess(sql.index("NOT IN"), sql.index("LIMIT"))
        self.assertEqual(report.recent_activity, [])


class UsageAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user, self.db = actor(), AsyncMock()
        result = Mock()
        result.mappings.return_value.one.return_value = empty_snapshot()
        self.db.execute.return_value = result
        app = FastAPI()
        app.include_router(usage.router, prefix="/api/usage")
        app.include_router(usage.admin_router, prefix="/api/admin/usage")
        app.include_router(activity_routes.router, prefix="/api/activity")

        async def current_user():
            if self.user is None:
                raise HTTPException(status_code=401, detail="Sign in required")
            return self.user

        async def database():
            yield self.db

        async def rate_limited(request, exc):
            return JSONResponse(status_code=429, content={"detail": "Rate limited"})

        app.dependency_overrides[get_current_user] = current_user
        app.dependency_overrides[get_db] = database
        app.add_exception_handler(RateLimitExceeded, rate_limited)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://usage.test")
        self.params = {"start_date": "2026-01-01", "end_date": "2026-01-03"}

    async def asyncTearDown(self):
        await self.client.aclose()

    async def view(self, **payload):
        return await self.client.post("/api/usage/section-views", json={
            "event_id": str(uuid4()), "section": "graphs", **payload,
        })

    async def test_admin_only_report_including_teamlead_with_all_flags(self):
        for role in UserRole:
            self.user = actor(role, task_workspace_enabled=True, audit_enabled=True,
                              audit_calendar_enabled=True, feedback_enabled=True)
            response = await self.client.get("/api/admin/usage", params=self.params)
            self.assertEqual(response.status_code, 200 if role == UserRole.admin else 403, response.text)
        self.user = None
        self.assertEqual((await self.client.get("/api/admin/usage", params=self.params)).status_code, 401)
        self.assertEqual((await self.view()).status_code, 401)

    async def test_report_bounds_validate_before_sql(self):
        self.user = actor(UserRole.admin)
        for params in (
            {"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 100001},
            {"start_date": "2026-01-04"}, {"end_date": "9999-12-31"},
            {"start_date": "0001-01-01", "end_date": "0001-01-01"},
            {"start_date": "2024-01-01", "end_date": "2025-01-01"},
            {"start_date": "bad-date"}, {"user_id": "bad-uuid"},
        ):
            with self.subTest(params=params):
                response = await self.client.get("/api/admin/usage", params={**self.params, **params})
                self.assertEqual(response.status_code, 422, response.text)
        self.db.execute.assert_not_called()

    async def test_capture_permission_and_payload_boundaries(self):
        self.assertEqual((await self.view()).status_code, 204)
        self.assertEqual((await self.view(section="settings")).status_code, 204)
        self.assertEqual((await self.view(section="profile")).status_code, 403)
        for section in ("admin-users", "admin-integrations", "audit", "my-tasks"):
            self.assertEqual((await self.view(section=section)).status_code, 403)
        for payload in ({"section": "/graphs?data=private"}, {"actor_id": str(uuid4())},
                        {"metadata": {"client_host": "192.0.2.1"}}, {"event_id": "invalid"}):
            self.assertEqual((await self.view(**payload)).status_code, 422)
        self.assertEqual(self.db.execute.await_count, 2)
        self.user.task_workspace_enabled = True
        self.assertEqual((await self.view(section="profile")).status_code, 204)

    async def test_generic_activity_route_only_enables_usage_for_admin(self):
        with patch.object(activity_routes, "list_activity_events", new_callable=AsyncMock) as listing:
            listing.return_value = {"items": [], "total": 0, "limit": 200}
            for role in (UserRole.teamlead, UserRole.admin):
                self.user = actor(role, task_workspace_enabled=True)
                for event_type in (None, "login_success", "usage_section_view"):
                    params = {"event_type": event_type} if event_type else {}
                    response = await self.client.get("/api/activity", params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(listing.call_args.kwargs["include_usage"], role == UserRole.admin)

    async def test_rate_limit_is_per_actor_not_shared_ip(self):
        for _ in range(120):
            response = await self.view()
            self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual((await self.view()).status_code, 429)
        self.user = actor()
        self.assertEqual((await self.view()).status_code, 204)
        self.assertEqual(self.db.execute.await_count, 121)


@unittest.skipUnless(os.getenv("DPMS_USAGE_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required")
class UsagePostgreSQLTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ["DPMS_USAGE_TEST_DATABASE_URL"])
        if (not url.database or not url.database.startswith("dpms_usage_test_")
                or url.database == "dpms_usage_test_"
                or url.host not in {"localhost", "127.0.0.1", "db", "dpms-local-db-1", "dpms-graphs-storage-db-1"}
                or url.drivername != "postgresql+asyncpg"):
            raise RuntimeError("Only a disposable dpms_usage_test_* PostgreSQL database is allowed")
        self.engine = create_async_engine(url)
        self.addAsyncCleanup(self.engine.dispose)
        self.connection = await self.engine.connect()
        self.addAsyncCleanup(self.connection.close)
        self.transaction = await self.connection.begin()
        self.addAsyncCleanup(self.transaction.rollback)
        schema = "usage_test_" + uuid4().hex
        await self.connection.execute(CreateSchema(schema))
        await self.connection.execution_options(schema_translate_map={User.__table__.schema: schema})
        metadata = MetaData(schema=User.__table__.schema)
        self.people_table = Table(
            "users", metadata, Column("id", Uuid, primary_key=True),
            Column("full_name", String(255), nullable=False), Column("email", String(255), nullable=False),
        )
        Table("tasks", metadata, Column("id", Uuid, primary_key=True))
        ActivityEvent.__table__.to_metadata(metadata)
        await self.connection.run_sync(metadata.create_all)
        self.db = AsyncSession(self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.addAsyncCleanup(self.db.close)
        self.alice, self.bob = actor(), actor()
        self.user = self.alice
        await self.db.execute(insert(self.people_table), [
            {"id": self.alice.id, "full_name": "Alice", "email": "alice@example.invalid"},
            {"id": self.bob.id, "full_name": "Bob", "email": "bob@example.invalid"},
        ])
        app = FastAPI()
        app.include_router(usage.router, prefix="/api/usage")
        app.include_router(usage.admin_router, prefix="/api/admin/usage")

        async def current_user():
            return self.user

        async def database():
            yield self.db
            await self.db.flush()

        app.dependency_overrides[get_current_user] = current_user
        app.dependency_overrides[get_db] = database
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://usage.test")
        self.addAsyncCleanup(self.client.aclose)

    async def event(self, who, at, kind=service.LOGIN_EVENT, data=None, event_id=None):
        event = ActivityEvent(id=event_id or uuid4(), actor_id=who.id, event_type=kind,
                              occurred_at=at, event_data=data)
        self.db.add(event)
        await self.db.flush()
        return event

    async def test_replays_are_immutable_and_same_uuid_is_independent_for_two_actors(self):
        event_id = uuid4()
        payload = {"event_id": str(event_id), "section": "graphs"}
        before = datetime.now(timezone.utc)
        self.assertEqual((await self.client.post("/api/usage/section-views", json=payload)).status_code, 204)
        stored_id = service.section_view_id(self.alice.id, event_id)
        original = (await self.db.execute(select(ActivityEvent).where(ActivityEvent.id == stored_id))).scalar_one()
        original_time = original.occurred_at
        for section in ("graphs", "settings"):
            self.assertEqual((await self.client.post("/api/usage/section-views", json={**payload, "section": section})).status_code, 204)
        await self.db.refresh(original)
        self.assertEqual(original.occurred_at, original_time)
        self.assertGreaterEqual(original_time, before)
        self.assertEqual(original.event_data, {"section": "graphs"})
        self.assertEqual(original.actor_id, self.alice.id)
        self.user = self.bob
        self.assertEqual((await self.client.post("/api/usage/section-views", json=payload)).status_code, 204)
        self.assertEqual((await self.db.execute(select(func.count()).select_from(ActivityEvent))).scalar_one(), 2)

    async def test_moscow_boundaries_filter_independence_and_privacy_over_http(self):
        utc = timezone.utc
        history = datetime(2025, 12, 1, tzinfo=utc)
        await self.event(self.alice, history)
        first_view = datetime(2025, 12, 2, tzinfo=utc)
        await self.event(self.alice, first_view, service.SECTION_VIEW_EVENT, {"section": "graphs"})
        await self.event(self.alice, datetime(2026, 1, 1, 20, 59, 59, tzinfo=utc))
        same_time = datetime(2026, 1, 1, 21, tzinfo=utc)
        first_id, second_id = UUID(int=1), UUID(int=2)
        metadata = {"user_agent": "Mozilla/5.0 (iPhone; ExactPrivateModel) Version/17 Safari/605", "client_host": "192.0.2.123"}
        await self.event(self.alice, same_time, data=metadata, event_id=first_id)
        await self.event(self.alice, same_time, data=metadata, event_id=second_id)
        await self.event(self.bob, datetime(2026, 1, 2, 20, 59, 59, tzinfo=utc))
        await self.event(self.bob, datetime(2026, 1, 2, 21, tzinfo=utc))
        await self.event(self.alice, same_time, "login_failure", metadata)
        await self.event(self.alice, same_time, "task_created")
        await self.event(self.alice, same_time, service.SECTION_VIEW_EVENT, {"section": "graphs"})
        await self.event(self.bob, same_time, service.SECTION_VIEW_EVENT, {"section": "graphs"})
        await self.event(self.bob, same_time, service.SECTION_VIEW_EVENT, {"section": "settings"})
        self.user = actor(UserRole.admin)
        params = {"start_date": "2026-01-02", "end_date": "2026-01-02", "limit": 1}
        response = await self.client.get("/api/admin/usage", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        whole = response.json()
        response = await self.client.get("/api/admin/usage", params={**params, "user_id": str(self.alice.id)})
        self.assertEqual(response.status_code, 200, response.text)
        filtered = response.json()
        self.assertEqual({k: v for k, v in whole.items() if k != "logins"},
                         {k: v for k, v in filtered.items() if k != "logins"})
        self.assertEqual(whole["login_count"], 3)
        self.assertEqual(whole["login_users"], 2)
        self.assertEqual(whole["section_view_count"], 3)
        self.assertEqual(whole["section_users"], 2)
        self.assertEqual(whole["logins"]["total"], 3)
        self.assertEqual(filtered["logins"]["total"], 2)
        self.assertEqual(filtered["logins"]["items"][0]["id"], str(second_id))
        self.assertEqual(filtered["logins"]["items"][0]["device"], "Телефон")
        self.assertEqual(filtered["logins"]["items"][0]["os"], "iOS")
        self.assertEqual(whole["daily"], [{"date": "2026-01-02", "logins": 3, "section_views": 3}])
        self.assertEqual([(s["section"], s["views"], s["users"]) for s in whole["sections"]],
                         [("graphs", 2, 2), ("settings", 1, 1)])
        self.assertEqual([u["logins"] for u in whole["users"]], [2, 1])
        self.assertEqual(datetime.fromisoformat(whole["first_login_at"]), history)
        self.assertEqual(datetime.fromisoformat(whole["first_section_view_at"]), first_view)
        for private in ("user_agent", "client_host", "192.0.2.123", "ExactPrivateModel", "Safari/605"):
            self.assertNotIn(private, response.text)
        second = await self.client.get("/api/admin/usage", params={**params, "user_id": str(self.alice.id), "offset": 1})
        self.assertEqual(second.json()["logins"]["items"][0]["id"], str(first_id))
        beyond = await self.client.get("/api/admin/usage", params={**params, "user_id": str(self.alice.id), "offset": 100000})
        self.assertEqual(beyond.json()["logins"], {"total": 2, "items": []})
        unknown = await self.client.get("/api/admin/usage", params={**params, "user_id": str(uuid4())})
        self.assertEqual(unknown.json()["logins"], {"total": 0, "items": []})
        self.assertEqual(unknown.json()["login_count"], 3)

    async def test_empty_history_has_no_invented_coverage(self):
        report = await service.get_usage_report(self.db, start_date=date(2026, 1, 1), end_date=date(2026, 1, 3))
        self.assertEqual(report.login_count, 0)
        self.assertEqual(report.section_view_count, 0)
        self.assertEqual(report.sections, [])
        self.assertEqual(report.users, [])
        self.assertEqual(report.logins.items, [])
        self.assertIsNone(report.first_login_at)
        self.assertIsNone(report.first_section_view_at)
        self.assertEqual(len(report.daily), 3)

    async def test_generic_activity_cannot_reveal_usage_even_with_explicit_filter(self):
        at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        await self.event(self.alice, at, data={"user_agent": "Private", "client_host": "192.0.2.2"})
        await self.event(self.alice, at, service.SECTION_VIEW_EVENT, {"section": "graphs"})
        for event_type in (None, "login_success", "usage_section_view"):
            response = await list_activity_events(self.db, event_type=event_type)
            self.assertEqual(response.items, [])
            self.assertEqual(response.total, 0)


if __name__ == "__main__":
    unittest.main()
