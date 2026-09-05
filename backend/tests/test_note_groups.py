"""ID65 isolated SQL/API tests. Only an in-memory SQLite database is used.

Run from a directory without an .env file, with backend on PYTHONPATH:
python -m unittest discover -s /path/to/backend/tests -p test_note_groups.py -v
Requires aiosqlite in the test environment. PostgreSQL row-lock/upsert semantics
remain a separate integration gate; this suite never touches configured storage.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import Column, JSON, MetaData, Table, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes import note_groups, quick_notes
from app.models.contact import Contact
from app.models.note_group import NoteContextLink, NoteGroup, NoteShareBatch
from app.models.personal_task import PersonalTask
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.user import User
from app.models.work_entity import WorkEntity, WorkEntityLink, WorkEntityMember
from app.schemas.note_group import NoteBulkMove, NoteGroupOrder, NoteSharePreviewCreate
from app.services import note_groups as service


class NoteGroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        @event.listens_for(self.engine.sync_engine, "connect")
        def sqlite_functions(connection, _):
            connection.create_function("num_nonnulls", -1, lambda *args: sum(arg is not None for arg in args), deterministic=True)
            connection.execute("PRAGMA foreign_keys=ON")

        models = [User, Contact, NoteGroup, QuickNote, PersonalTask, WorkEntity, WorkEntityMember,
                  WorkEntityLink, NoteContextLink, QuickNoteShare, QuickNoteComment, QuickNoteAttachment, NoteShareBatch]
        self.restores = []
        schema = MetaData()
        for model in models:
            for column in model.__table__.columns:
                if isinstance(column.type, (ARRAY, JSONB)):
                    self.restores.append((column, "type", column.type))
                    column.type = JSON()
                if column.server_default is not None and "nextval" in str(column.server_default.arg):
                    self.restores.append((column, "server_default", column.server_default))
                    column.server_default = None
            model.__table__.to_metadata(schema)
        for table in list(schema.tables.values()):
            for foreign in table.foreign_keys:
                table_name = foreign.target_fullname.rsplit(".", 1)[0]
                if table_name not in schema.tables:
                    Table(table_name, schema, Column("id", UUID(as_uuid=True), primary_key=True))
        async with self.engine.begin() as connection:
            await connection.run_sync(schema.create_all)
        self.db = AsyncSession(self.engine, expire_on_commit=False)
        self.owner = User(id=uuid4(), full_name="Owner", email="owner@example.invalid", league="A", role="executor", task_workspace_enabled=True)
        self.other = User(id=uuid4(), full_name="Other", email="other@example.invalid", league="A", role="admin", task_workspace_enabled=True)
        self.stranger = User(id=uuid4(), full_name="Stranger", email="stranger@example.invalid", league="A", role="executor", task_workspace_enabled=True)
        self.db.add_all([self.owner, self.other, self.stranger]); await self.db.flush()
        self.group = NoteGroup(id=uuid4(), owner_id=self.owner.id, title="Private group")
        self.project = WorkEntity(id=uuid4(), owner_id=self.owner.id, title="Project", entity_type="project", visibility="shared")
        self.db.add_all([self.group, self.project]); await self.db.flush()
        self.note = QuickNote(id=uuid4(), owner_id=self.owner.id, title="Private note", body="Private body", group_id=self.group.id)
        self.foreign = QuickNote(id=uuid4(), owner_id=self.other.id, title="Foreign", body="Other body")
        self.task = PersonalTask(id=uuid4(), task_number=1, owner_id=self.owner.id, title="Own task")
        self.contact = Contact(id=uuid4(), requester_id=self.owner.id, recipient_id=self.other.id, status="accepted")
        self.db.add_all([self.note, self.foreign, self.task, self.contact,
            WorkEntityMember(entity_id=self.project.id, user_id=self.other.id, role="viewer")])
        await self.db.commit()
        self.user = self.owner
        app = FastAPI()
        app.include_router(note_groups.router, prefix="/api/note-groups")
        app.include_router(quick_notes.router, prefix="/api/quick-notes")
        async def current_user():
            await self.db.refresh(self.user)
            return self.user
        async def database():
            try:
                yield self.db
                await self.db.commit()
            except Exception:
                await self.db.rollback()
                raise
        app.dependency_overrides[get_current_user] = current_user
        app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose(); await self.db.close(); await self.engine.dispose()
        for obj, attribute, value in reversed(self.restores): setattr(obj, attribute, value)

    async def request(self, method, path, **kwargs):
        return await self.client.request(method, "/api/note-groups" + path, **kwargs)

    async def test_owner_only_groups_and_links_even_for_admin(self):
        group_id, note_id, task_id = self.group.id, self.note.id, self.task.id
        self.user = self.other
        self.assertEqual((await self.request("GET", "")).json(), [])
        for method, path, body in [
            ("PATCH", f"/{group_id}", {"base_revision": 1, "title": "Stolen"}),
            ("DELETE", f"/{group_id}?base_revision=1", None),
            ("POST", f"/sources/group/{group_id}/links", {"target_type": "personal_task", "target_id": str(task_id)}),
            ("POST", f"/sources/note/{note_id}/links", {"target_type": "personal_task", "target_id": str(task_id)}),
        ]:
            response = await self.request(method, path, **({"json": body} if body else {}))
            self.assertEqual(response.status_code, 404, response.text)

    async def test_bulk_move_is_atomic_and_never_moves_incoming_note(self):
        note_id, foreign_id, group_id = self.note.id, self.foreign.id, self.group.id
        response = await self.request("POST", "/move", json={"note_ids": [str(note_id), str(foreign_id)], "group_id": None})
        self.assertEqual(response.status_code, 404)
        await self.db.refresh(self.note)
        self.assertEqual(self.note.group_id, group_id)
        response = await self.request("POST", "/move", json={"note_ids": [str(note_id)], "group_id": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.note.group_id)

    async def test_archive_delete_preserves_notes_and_removes_context(self):
        group_id, note_id = self.group.id, self.note.id
        self.db.add(NoteContextLink(group_id=group_id, entity_id=self.project.id)); await self.db.commit()
        response = await self.request("PATCH", f"/{group_id}", json={"base_revision": 1, "archived": True})
        self.assertEqual(response.status_code, 200)
        response = await self.request("DELETE", f"/{group_id}?base_revision=2")
        self.assertEqual(response.json(), {"deleted": True, "notes_preserved": True})
        await self.db.refresh(self.note)
        self.assertIsNone(self.note.group_id)
        self.assertIsNotNone(await self.db.get(QuickNote, note_id))
        self.assertEqual(list((await self.db.execute(select(NoteContextLink))).scalars()), [])

    async def test_dynamic_context_and_private_backlinks(self):
        self.db.add(NoteContextLink(group_id=self.group.id, entity_id=self.project.id)); await self.db.commit()
        response = await self.client.post("/api/quick-notes", json={"body": "New note", "group_id": str(self.group.id)})
        self.assertEqual(response.status_code, 200, response.text)
        new_id = response.json()["id"]
        links = (await self.request("GET", f"/sources/note/{new_id}/links")).json()
        self.assertEqual(len(links), 1); self.assertTrue(links[0]["inherited"])
        path = f"/backlinks?target_type=entity&target_id={self.project.id}"
        self.user = self.other
        response = await self.request("GET", path)
        self.assertEqual(response.json(), {"notes": [], "groups": []})
        self.db.add(QuickNoteShare(note_id=self.note.id, owner_id=self.owner.id, recipient_id=self.other.id)); await self.db.commit()
        response = await self.request("GET", path)
        self.assertEqual(response.json(), {"notes": [{"id": str(self.note.id), "title": self.note.title}], "groups": []})
        response = await self.client.get("/api/quick-notes/shared")
        self.assertIsNone(response.json()[0]["note"]["group_id"])
        response = await self.client.get(f"/api/quick-notes/{self.note.id}")
        self.assertIsNone(response.json()["note"]["group_id"])

    async def test_targets_are_validated_and_legacy_links_are_not_duplicated(self):
        own_note, foreign_note, task_id, project_id = self.note.id, self.foreign.id, self.task.id, self.project.id
        self.db.add(WorkEntityLink(entity_id=project_id, quick_note_id=own_note)); await self.db.commit()
        response = await self.request("POST", f"/sources/note/{own_note}/links", json={"target_type": "entity", "target_id": str(project_id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([link["origin"] for link in response.json()], ["legacy"])
        self.assertEqual(list((await self.db.execute(select(NoteContextLink))).scalars()), [])
        self.user = self.other
        response = await self.request("POST", f"/sources/note/{foreign_note}/links", json={"target_type": "personal_task", "target_id": str(task_id)})
        self.assertEqual(response.status_code, 404)

    async def test_stale_revision_and_invalid_group_creation(self):
        group_id = self.group.id
        response = await self.request("PATCH", f"/{group_id}", json={"base_revision": 5, "title": "Stale"})
        self.assertEqual(response.status_code, 409)
        response = await self.request("POST", "", json={"title": "  "})
        self.assertEqual(response.status_code, 422)

    async def preview(self, **changes):
        payload = {"group_id": str(self.group.id), "recipient_ids": [str(self.other.id)], **changes}
        response = await self.request("POST", "/share/preview", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_project_membership_does_not_bypass_contact_policy(self):
        self.contact.status = "pending"; await self.db.commit()
        response = await self.request("POST", "/share/preview", json={"group_id": str(self.group.id), "recipient_ids": [str(self.other.id)], "project_id": str(self.project.id)})
        self.assertEqual(response.status_code, 403)

    async def test_snapshot_change_blocks_apply(self):
        preview = await self.preview()
        self.note.body = "Changed confidential text"; self.note.revision += 1; await self.db.commit()
        with patch.object(service, "activate_quick_note_shares", new_callable=AsyncMock) as activate:
            response = await self.request("POST", f"/share/{preview['id']}/apply")
            self.assertEqual(response.status_code, 409, response.text); activate.assert_not_awaited()

    async def test_group_membership_change_blocks_apply(self):
        preview = await self.preview()
        self.db.add(QuickNote(owner_id=self.owner.id, title="Late addition", body="Never previewed", group_id=self.group.id)); await self.db.commit()
        response = await self.request("POST", f"/share/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)

    async def test_comments_change_blocks_apply(self):
        preview = await self.preview()
        self.db.add(QuickNoteComment(note_id=self.note.id, author_id=self.owner.id, body="New discussion")); await self.db.commit()
        response = await self.request("POST", f"/share/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)

    async def test_file_change_blocks_apply(self):
        preview = await self.preview()
        self.db.add(QuickNoteAttachment(note_id=self.note.id, uploaded_by_id=self.owner.id,
            original_filename="new.txt", stored_filename="id65-test-only.txt", content_type="text/plain", size_bytes=5))
        await self.db.commit()
        response = await self.request("POST", f"/share/{preview['id']}/apply")
        self.assertEqual(response.status_code, 409, response.text)

    async def test_contact_revocation_between_preview_and_apply(self):
        preview = await self.preview()
        self.contact.status = "pending"; await self.db.commit()
        response = await self.request("POST", f"/share/{preview['id']}/apply")
        self.assertEqual(response.status_code, 403)

    async def test_inaccessible_entity_rejected_and_reordering_persists(self):
        private = WorkEntity(owner_id=self.stranger.id, title="Hidden", entity_type="goal")
        self.db.add(private); await self.db.commit()
        group_id = self.group.id
        response = await self.request("POST", f"/sources/group/{group_id}/links", json={"target_type": "entity", "target_id": str(private.id)})
        self.assertEqual(response.status_code, 404)
        second = (await self.request("POST", "", json={"title": "Second"})).json()
        response = await self.request("POST", "/order", json={"groups": [{"id": second["id"], "base_revision": 1}, {"id": str(group_id), "base_revision": 1}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([group["title"] for group in response.json()], ["Second", "Private group"])
        response = await self.request("PATCH", f"/{group_id}", json={"base_revision": 2, "collapsed": True})
        self.assertTrue(response.json()["collapsed"])

    async def test_apply_is_audited_and_replay_never_reshare_or_notify(self):
        preview = await self.preview()
        recipient_id = self.other.id
        with patch.object(service, "activate_quick_note_shares", new_callable=AsyncMock, return_value=[recipient_id]) as activate, patch.object(service, "emit_attention_event", new_callable=AsyncMock) as emit:
            first = await self.request("POST", f"/share/{preview['id']}/apply")
            second = await self.request("POST", f"/share/{preview['id']}/apply")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), second.json())
            activate.assert_awaited_once(); emit.assert_awaited_once()
        audit = (await self.request("GET", "/share/audit")).json()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["result"]["note_ids"], [str(self.note.id)])
        self.user = self.other
        self.assertEqual((await self.request("GET", "/share/audit")).json(), [])
        self.assertEqual((await self.request("POST", f"/share/{preview['id']}/apply")).status_code, 404)

    async def test_expired_preview(self):
        preview = await self.preview()
        batch = (await self.db.execute(select(NoteShareBatch))).scalar_one()
        batch.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); await self.db.commit()
        self.assertEqual((await self.request("POST", f"/share/{preview['id']}/apply")).status_code, 409)

    def test_duplicate_and_unknown_input_guards(self):
        id = uuid4()
        for schema, data in [
            (NoteBulkMove, {"note_ids": [id, id]}),
            (NoteSharePreviewCreate, {"note_ids": [id], "recipient_ids": [id, id]}),
            (NoteGroupOrder, {"groups": [{"id": id, "base_revision": 1}] * 2}),
            (NoteBulkMove, {"note_ids": [id], "owner_id": id}),
        ]:
            with self.assertRaises(ValidationError): schema.model_validate(data)


class MigrationContractTests(unittest.TestCase):
    def test_migration_chain_and_protected_article(self):
        path = Path(__file__).parents[1] / "alembic/versions/080_note_groups.py"
        spec = importlib.util.spec_from_file_location("note_groups_migration", path)
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        self.assertEqual(migration.revision, "080_note_groups")
        self.assertEqual(migration.down_revision, "079_tracker_organization")
        self.assertLessEqual(len(migration.down_revision), 32)
        self.assertEqual(migration.ARTICLE["slug"], "lichnye-gruppy-zametok-i-kontekst")


if __name__ == "__main__": unittest.main()
