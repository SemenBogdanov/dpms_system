"""SQL contract for scoped transfer locks; real races run in the PG smoke."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.services.audit_legacy_locks import lock_legacy_targets


class LegacyLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_locks_only_selected_roots_children_and_actors(self):
        db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), execute=AsyncMock())
        case_id, actor_id = uuid4(), uuid4()
        await lock_legacy_targets(db, [case_id], [actor_id])
        statements = [call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
                      for call in db.execute.await_args_list]
        self.assertEqual(len(statements), 7)
        for index, statement in enumerate(statements):
            sql = str(statement)
            self.assertIn(" WHERE ", sql.replace("\n", " "))
            self.assertIn("ORDER BY", sql)
            self.assertNotIn("LOCK TABLE", sql)
            self.assertIn(str(case_id if index < 5 else actor_id), sql)
            self.assertIn("FOR UPDATE" if index < 5 else "FOR SHARE", sql)

    async def test_empty_scope_does_not_lock_unrelated_tables(self):
        db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), execute=AsyncMock())
        await lock_legacy_targets(db, [])
        db.execute.assert_not_awaited()

    async def test_non_postgres_is_for_isolated_unit_tests_only(self):
        db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")), execute=AsyncMock())
        await lock_legacy_targets(db, [uuid4()])
        db.execute.assert_not_awaited()
