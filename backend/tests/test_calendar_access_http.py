"""Opt-in real HTTP/CalendarService access checks on isolated PostgreSQL.

Run from backend with the already migrated disposable database:
  DPMS_CALENDAR_HTTP_TESTS=1 python -m unittest discover -s tests \
      -p 'test_calendar_access_http.py' -v

DATABASE_URL must name dpms_calendar_v5_http_test on an approved local host.
Only actor identification is replaced; both routers and their access guards,
CalendarService, and persistence are real. No application/settings imports
occur without opt-in. The reused fixture rolls back all synthetic test data;
this module never creates, drops, resets, or migrates a database/schema.
"""
import os
from types import SimpleNamespace
import unittest
from uuid import UUID, uuid4


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarAccessHTTPTests(unittest.IsolatedAsyncioTestCase):
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

        import httpx
        from fastapi import FastAPI
        import test_calendar_http_integration as fixture
        from app.api.deps import get_current_user, get_db
        from app.api.routes.audit import router as audit_router
        from app.api.routes.audit_calendar import router as calendar_router

        # Reuse setup/rollback without inheriting the fixture's test methods.
        self.fixture = fixture.CalendarHTTPTests
        await self.fixture.asyncSetUp(self)
        self.addAsyncCleanup(self.fixture.asyncTearDown, self)
        await self.client.aclose()

        app = FastAPI()
        app.include_router(calendar_router, prefix="/api/audit-calendar")
        app.include_router(audit_router, prefix="/api/audit")

        async def actor():
            return self.actor

        async def db_session():
            async with self.factory.begin() as db:
                yield db

        app.dependency_overrides[get_current_user] = actor
        app.dependency_overrides[get_db] = db_session
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://calendar.test"
        )

    async def persisted_actor(self):
        from sqlalchemy import select
        from app.models.user import User

        # Project access fields only, never credential-bearing user columns.
        async with self.factory() as db:
            row = (await db.execute(select(
                User.id, User.role, User.is_active, User.auth_version,
                User.audit_enabled, User.audit_calendar_enabled,
                User.task_workspace_enabled, User.feedback_enabled,
                User.competency_development_enabled, User.competency_constructor_enabled,
            ).where(User.id == self.people["employee"].id))).one()
            return SimpleNamespace(**row._mapping)

    async def assert_audit_denied(self):
        from fastapi import HTTPException
        from app.api.deps import ensure_audit_access

        # Match the grant gate's denial, not an unrelated audit-team 403.
        with self.assertRaises(HTTPException) as denial:
            ensure_audit_access(self.actor)
        response = await self.client.get("/api/audit/cases")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json(), {"detail": denial.exception.detail})

    async def check_independent_access(self, *, development):
        from sqlalchemy import select, update
        from app.models.audit_calendar import AuditCalendarMember
        from app.models.user import User, UserRole

        async with self.factory.begin() as db:
            await db.execute(update(User).where(User.id == self.people["employee"].id).values(
                role=UserRole.executor, is_active=True, audit_calendar_enabled=True,
                audit_enabled=False, task_workspace_enabled=False,
                can_link_queue_tasks_to_projects=False, feedback_enabled=False,
                competency_development_enabled=development, competency_constructor_enabled=False,
            ))
        self.actor = await self.persisted_actor()
        self.assertEqual(self.actor.role, UserRole.executor)
        self.assertTrue(self.actor.audit_calendar_enabled)
        self.assertFalse(self.actor.audit_enabled)
        self.assertFalse(self.actor.task_workspace_enabled)
        self.assertFalse(self.actor.feedback_enabled)
        self.assertIs(self.actor.competency_development_enabled, development)
        self.assertFalse(self.actor.competency_constructor_enabled)

        response = await self.fixture.state(self)
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state["actor"]["user_id"], str(self.actor.id))
        self.assertFalse(state["actor"]["can_manage"])
        member = next(item for item in state["members"] if item["user_id"] == str(self.actor.id))
        self.assertTrue(member["active"])
        self.assertEqual(member["role"], "auditor")
        await self.assert_audit_denied()
        admin = await self.client.get("/api/audit-calendar/admin")
        self.assertEqual(admin.status_code, 403, admin.text)

        async with self.factory.begin() as db:
            await db.execute(update(User).where(User.id == self.actor.id).values(
                audit_calendar_enabled=False,
            ))
        revoked = await self.persisted_actor()
        self.assertFalse(revoked.audit_calendar_enabled)
        self.assertEqual(revoked.auth_version, self.actor.auth_version)
        self.assertTrue(revoked.is_active)
        self.assertEqual(revoked.role, UserRole.executor)
        self.assertFalse(revoked.audit_enabled)
        self.assertFalse(revoked.task_workspace_enabled)
        async with self.factory() as db:
            persisted_member = (await db.execute(select(
                AuditCalendarMember.active, AuditCalendarMember.role, AuditCalendarMember.can_manage,
            ).where(
                AuditCalendarMember.scope_id == UUID(state["scope"]["id"]),
                AuditCalendarMember.user_id == self.actor.id,
            ))).one()
        self.assertEqual(tuple(persisted_member), (True, "auditor", False))
        # Keep the old actor snapshot: CalendarService must recheck the DB grant.
        self.assertTrue(self.actor.audit_calendar_enabled)
        response = await self.fixture.state(self)
        self.assertEqual(response.status_code, 403, response.text)
        await self.assert_audit_denied()

        self.actor = self.people["helper"]
        response = await self.fixture.state(self)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"]["version"], state["scope"]["version"])

    async def test_executor_calendar_member_without_audit_or_tasks(self):
        await self.check_independent_access(development=False)

    async def test_development_only_executor_calendar_member_without_audit_or_tasks(self):
        await self.check_independent_access(development=True)

    async def test_admin_edit_preserves_membership_during_temporary_grant_revocation(self):
        from sqlalchemy import select, update
        from app.models.audit_calendar import AuditCalendarMember
        from app.models.user import User

        employee = self.people["employee"]
        async with self.factory.begin() as db:
            await db.execute(update(User).where(User.id == employee.id).values(audit_calendar_enabled=False))
        self.actor = self.people["helper"]
        state = (await self.fixture.state(self)).json()
        member = next(item for item in state["members"] if item["user_id"] == str(employee.id))
        self.assertFalse(member["active"])

        self.actor = self.people["admin"]
        response = await self.client.get("/api/audit-calendar/admin")
        self.assertEqual(response.status_code, 200, response.text)
        admin = response.json()
        member = next(item for item in admin["members"] if item["user_id"] == str(employee.id))
        self.assertTrue(member["active"])
        payload = {key: member[key] for key in ("user_id", "code", "role", "can_manage", "active")}
        payload.update(code="EDIT", request_id=str(uuid4()), expected_version=admin["scope"]["version"])
        saved = await self.client.post("/api/audit-calendar/admin/members", json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        async with self.factory() as db:
            row = (await db.execute(select(AuditCalendarMember.active, AuditCalendarMember.code).where(
                AuditCalendarMember.user_id == employee.id,
            ))).one()
            self.assertEqual(tuple(row), (True, "EDIT"))

        self.actor = employee
        self.assertEqual((await self.fixture.state(self)).status_code, 403)
        async with self.factory.begin() as db:
            await db.execute(update(User).where(User.id == employee.id).values(audit_calendar_enabled=True))
        self.assertEqual((await self.fixture.state(self)).status_code, 200)

        # Explicit deactivation remains possible, but reactivation needs a grant.
        self.actor = self.people["admin"]
        async with self.factory.begin() as db:
            await db.execute(update(User).where(User.id == employee.id).values(audit_calendar_enabled=False))
        payload.update(active=False, request_id=str(uuid4()), expected_version=saved.json()["version"])
        disabled = await self.client.post("/api/audit-calendar/admin/members", json=payload)
        self.assertEqual(disabled.status_code, 200, disabled.text)
        payload.update(active=True, request_id=str(uuid4()), expected_version=disabled.json()["version"])
        denied = await self.client.post("/api/audit-calendar/admin/members", json=payload)
        self.assertEqual(denied.status_code, 422, denied.text)


if __name__ == "__main__":
    unittest.main()
