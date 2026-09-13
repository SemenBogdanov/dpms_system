"""Real PostgreSQL route tests; authentication is replaced only with test actors."""
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes.audit_calendar import router
from app.models.user import User, UserRole, League
from app.models.audit_calendar import AuditCalendarEvent, AuditCalendarPlan
from app.schemas.audit_calendar import Setup, MemberSave, command_adapter
from app.services.audit_calendar import CalendarService


@unittest.skipUnless(os.getenv('DPMS_CALENDAR_HTTP_TESTS') == '1', 'isolated PostgreSQL opt-in required')
class CalendarHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(os.environ['DATABASE_URL'])
        if url.database != 'dpms_calendar_v5_http_test' or url.host not in {'dpms-local-db-1', 'localhost', '127.0.0.1'}:
            raise RuntimeError('Only the disposable calendar HTTP test database is allowed')
        self.engine = create_async_engine(url)
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.factory = async_sessionmaker(self.connection, expire_on_commit=False,
            join_transaction_mode='create_savepoint')
        self.today = datetime.now(ZoneInfo('Europe/Moscow')).date()
        self.people = {}
        async with self.factory.begin() as db:
            for code, role in [('admin', None), ('helper', 'observer'), ('employee', 'auditor'),
                               ('tech', 'tech'), ('speaker', 'speaker'), ('outsider', None), ('denied', None)]:
                user = User(id=uuid4(), email=f'{code}-{uuid4()}@example.com', full_name=f'Test {code}',
                    role=UserRole.admin if code == 'admin' else UserRole.executor, league=League.C,
                    is_active=True, audit_calendar_enabled=code != 'denied', auth_version=0)
                db.add(user)
                self.people[code] = SimpleNamespace(id=user.id, auth_version=0)
            await db.flush()
            service = CalendarService(db, self.people['admin'])
            answer = await service.setup(Setup(request_id=uuid4(), name='HTTP fixture', baseline=self.today))
            self.version = answer['version']
            for code, role in [('helper', 'observer'), ('employee', 'auditor'), ('tech', 'tech'), ('speaker', 'speaker')]:
                answer = await CalendarService(db, self.people['admin']).save_member(MemberSave(
                    request_id=uuid4(), expected_version=self.version, user_id=self.people[code].id,
                    code=code, role=role, can_manage=code == 'helper', active=True))
                self.version = answer['version']
            answer = await CalendarService(db, self.people['helper']).command(command_adapter.validate_python({
                'request_id': str(uuid4()), 'expected_version': self.version, 'operation': 'group.save',
                'payload': {'code': 'G1', 'label': 'Test group', 'effective_from': self.today.isoformat(),
                    'auditor_id': str(self.people['employee'].id), 'tech_id': str(self.people['tech'].id),
                    'reason': 'Synthetic test'},
            }))
            self.version, self.group_id = answer['version'], answer['result']['id']
        app = FastAPI()
        app.include_router(router, prefix='/api/audit-calendar')
        self.actor = self.people['employee']

        async def actor():
            return self.actor

        async def db_session():
            async with self.factory.begin() as db:
                yield db

        app.dependency_overrides[get_current_user] = actor
        app.dependency_overrides[get_db] = db_session
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://calendar.test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    def body(self, operation, payload):
        return {'request_id': str(uuid4()), 'expected_version': self.version, 'operation': operation, 'payload': payload}

    async def state(self):
        return await self.client.get('/api/audit-calendar/state', params={
            'from': self.today.isoformat(), 'to': (self.today + timedelta(days=6)).isoformat()})

    async def command(self, body):
        return await self.client.post('/api/audit-calendar/commands', json=body)

    def meeting(self):
        return {'date': (self.today + timedelta(days=1)).isoformat(), 'start': 600, 'duration': 90,
                'group_id': self.group_id, 'activity': 'HTTP test', 'speaker_id': str(self.people['speaker'].id),
                'status': 'planned', 'reason': 'Synthetic meeting'}

    async def test_membership_grant_and_admin_are_separate(self):
        for code, status in [('employee', 200), ('helper', 200), ('admin', 403), ('outsider', 403), ('denied', 403)]:
            self.actor = self.people[code]
            self.assertEqual((await self.state()).status_code, status, code)
            self.assertEqual((await self.client.get('/api/audit-calendar/admin')).status_code,
                             200 if code == 'admin' else 403, code)

    async def test_employee_cannot_manage_or_spoof_another_owner(self):
        for operation, payload in [('norm.set', {'group_id': None, 'effective_from': self.today.isoformat(),
                                                'value': 0, 'reason': 'Attempt'}),
                                   ('plan.save', self.meeting()),
                                   ('absence.add', {'user_id': str(self.people['tech'].id),
                                    'start_date': self.today.isoformat(), 'end_date': self.today.isoformat(), 'reason': 'Attempt'}),
                                   ('availability.paint', {'user_id': str(self.people['tech'].id),
                                    'patches': [{'date': self.today.isoformat(), 'start': 0, 'end': 1440, 'value': True}]})]:
            self.assertEqual((await self.command(self.body(operation, payload))).status_code, 403, operation)
        self.assertEqual((await self.state()).json()['scope']['version'], self.version)

    async def test_own_bulk_edit_and_revoked_account_are_rechecked(self):
        body = self.body('availability.paint', {'user_id': str(self.actor.id), 'patches': [
            {'date': self.today.isoformat(), 'start': 0, 'end': 1440, 'value': True}]})
        self.assertEqual((await self.command(body)).status_code, 200)
        self.assertEqual((await self.state()).json()['scope']['version'], self.version + 1)
        async with self.factory.begin() as db:
            user = await db.get(User, self.actor.id)
            user.audit_calendar_enabled = False
            user.auth_version += 1
        self.assertEqual((await self.state()).status_code, 403)
        self.assertEqual((await self.command(body)).status_code, 403)

    async def test_replay_cas_and_history_no_duplicate_plan(self):
        self.actor = self.people['helper']
        body = self.body('plan.save', self.meeting())
        first = await self.command(body)
        self.assertEqual(first.status_code, 200, first.text)
        second = await self.command(body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())
        stale = self.body('plan.save', {**self.meeting(), 'start': 840})
        self.assertEqual((await self.command(stale)).status_code, 409)
        body['payload']['activity'] = 'Changed body'
        self.assertEqual((await self.command(body)).status_code, 409)
        async with self.factory() as db:
            self.assertEqual(len((await db.scalars(select(AuditCalendarPlan))).all()), 1)
            events = (await db.scalars(select(AuditCalendarEvent).where(AuditCalendarEvent.action == 'plan.save'))).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].actor_id, self.actor.id)

    async def test_bad_range_and_actor_injection_do_not_write(self):
        self.actor = self.people['helper']
        for start, end in [('1900-01-01', '1900-01-02'), ('2101-01-01', '2101-01-02'),
                           ('2026-09-99', '2026-09-30'), ('2026-01-01', '2027-01-02')]:
            response = await self.client.get('/api/audit-calendar/state', params={'from': start, 'to': end})
            self.assertEqual(response.status_code, 422, response.text)
        body = self.body('plan.save', self.meeting())
        body['actor_id'] = str(self.people['admin'].id)
        self.assertEqual((await self.command(body)).status_code, 422)
        self.assertEqual((await self.state()).json()['scope']['version'], self.version)


if __name__ == '__main__':
    unittest.main()
