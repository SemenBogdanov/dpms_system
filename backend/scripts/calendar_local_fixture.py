"""Public synthetic fixture for the isolated, loopback-only calendar candidate."""
import asyncio
import os
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import get_password_hash
from app.models.user import User, UserRole, League
from app.models.audit_calendar import AuditCalendarScope
from app.schemas.audit_calendar import Setup, MemberSave, command_adapter
from app.services.audit_calendar import CalendarService

PEOPLE = [
    ('admin', 'Администратор календарного стенда', None, False),
    ('helper', 'Помощник календарного стенда', 'observer', True),
    ('employee', 'Аудитор Анна', 'auditor', False),
    ('auditor2', 'Аудитор Борис', 'auditor', False),
    ('tech', 'Технический специалист', 'tech', False),
    ('speaker', 'Докладчик Виктор', 'speaker', False),
    ('outsider', 'Сотрудник вне контура', None, False),
]


async def main():
    url = make_url(os.environ['DATABASE_URL'])
    if (os.getenv('DPMS_CALENDAR_LOCAL_FIXTURE') != '1'
            or url.database != 'dpms_calendar_v5_candidate'
            or url.host not in {'dpms-local-db-1', 'db', '127.0.0.1', 'localhost'}):
        raise RuntimeError('Only the dedicated local calendar candidate database is allowed')
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as db:
            if await db.scalar(select(func.count()).select_from(User)):
                raise RuntimeError('Fixture requires an empty user directory; existing data will not be changed')
            if await db.scalar(select(func.count()).select_from(AuditCalendarScope)):
                raise RuntimeError('Fixture requires an empty calendar')
            people = {}
            # This is intentionally a public test-only password, not an environment secret.
            password_hash = get_password_hash('Calendar-local-2026!')
            for code, name, _, _ in PEOPLE:
                user = User(id=uuid5(NAMESPACE_URL, f'dpms-calendar-local:{code}'),
                    full_name=name, email=f'calendar.{code}@example.com',
                    role=UserRole.admin if code == 'admin' else UserRole.executor,
                    league=League.C, mpw=0, wip_limit=2, is_active=True,
                    password_hash=password_hash, password_change_required=False,
                    audit_calendar_enabled=True, audit_enabled=False,
                    task_workspace_enabled=False, competency_development_enabled=False,
                    auth_version=0)
                db.add(user)
                people[code] = user
            await db.flush()
            today = datetime.now(ZoneInfo('Europe/Moscow')).date()
            result = await CalendarService(db, people['admin']).setup(
                Setup(request_id=uuid4(), name='Календарь аудита · локальная проверка', baseline=today))
            version = result['version']
            for code, _, role, helper in PEOPLE:
                if role:
                    result = await CalendarService(db, people['admin']).save_member(MemberSave(
                        request_id=uuid4(), expected_version=version, user_id=people[code].id,
                        code={'employee':'А1', 'auditor2':'А2', 'tech':'Т1', 'speaker':'Д1', 'helper':'П1'}[code],
                        role=role, can_manage=helper, active=True))
                    version = result['version']
            async def command(operation, payload):
                nonlocal version
                request = command_adapter.validate_python(dict(request_id=uuid4(), expected_version=version,
                    operation=operation, payload=payload))
                answer = await CalendarService(db, people['helper']).command(request)
                version = answer['version']
                return answer['result']
            group = await command('group.save', dict(code='G1', label='Первая группа', effective_from=today,
                auditor_id=people['employee'].id, tech_id=people['tech'].id, reason='Синтетический локальный пример'))
            await command('group.save', dict(code='G2', label='Вторая группа', effective_from=today,
                auditor_id=people['auditor2'].id, tech_id=people['tech'].id, reason='Пример общего технического специалиста'))
            for offset, start, duration, activity in [(1,600,90,'И43'), (2,750,60,'Проверка длинного названия цифрового продукта')]:
                await command('plan.save', dict(date=today+timedelta(days=offset), start=start, duration=duration,
                    group_id=group['id'], activity=activity, speaker_id=people['speaker'].id,
                    status='planned', reason='Синтетический пример; доступность не заполнена'))
        print('Synthetic calendar fixture created: 7 users, 5 members, 2 groups, 2 plans. No real data or external calls.')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
