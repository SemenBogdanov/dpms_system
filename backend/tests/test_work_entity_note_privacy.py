"""Read-model privacy regressions on an explicitly opted-in disposable PostgreSQL DB.

Prefer scripts/smoke_work_entity_note_privacy.py --allow-local-db. Direct runs
accept DPMS_NOTE_PRIVACY_TEST_URL for a local dpms_note_privacy_test database.
Fixtures use an isolated schema, not application migrations or data.
"""
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.routes import work_entities as routes
from app.models.deadline_tracker import DeadlineTracker
from app.models.execution_contract import WorkEntityExecutionContract
from app.models.personal_task import PersonalTask
from app.models.quick_note import QuickNote
from app.models.quick_note_share import QuickNoteShare
from app.models.task import Task
from app.models.user import League, User, UserRole
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityEvent,
    WorkEntityLink,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityStage,
    WorkEntityTask,
)
from app.schemas.work_entity import WorkEntityLinkCreate, WorkEntityLinkUpdate
from app.services.work_entities import build_entity_summary, serialize_links
from app.services.work_entity_workspace import build_project_map


TEST_URL = os.environ.get("DPMS_NOTE_PRIVACY_TEST_URL")


@unittest.skipUnless(TEST_URL, "requires disposable local DPMS_NOTE_PRIVACY_TEST_URL")
class WorkEntityNotePrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(TEST_URL)
        if (
            url.get_backend_name() != "postgresql"
            or url.host not in {"localhost", "127.0.0.1", "::1", "db"}
            or not re.fullmatch(r"dpms_note_privacy_(?:test|[0-9a-f]{32})", url.database or "")
        ):
            raise RuntimeError("Only the disposable local privacy test database is allowed")
        self.schema = f"note_privacy_{uuid4().hex}"
        self.engine = create_async_engine(
            url,
            execution_options={"schema_translate_map": {None: self.schema}},
        )
        self.addAsyncCleanup(self.engine.dispose)

        # These are read-model fixtures, not a substitute for migration/FK tests.
        # Copy columns without pulling unrelated feature FK trees into this suite.
        metadata = MetaData()
        for model in (
            User, QuickNote, QuickNoteShare, PersonalTask, Task, DeadlineTracker,
            WorkEntity, WorkEntityLink, WorkEntityEvent, WorkEntityMember,
            WorkEntityTask, WorkEntityMilestone, WorkEntityStage, WorkEntityArtifact,
            WorkEntityScheduleDependency, WorkEntityExecutionContract,
        ):
            Table(
                model.__tablename__, metadata,
                *(
                    Column(
                        column.name, column.type.copy(),
                        primary_key=column.primary_key, nullable=column.nullable,
                    )
                    for column in model.__table__.columns
                ),
            )
        async with self.engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            await connection.run_sync(metadata.create_all)
        self.addAsyncCleanup(self.drop_schema)
        self.db = AsyncSession(self.engine, expire_on_commit=False)
        self.addAsyncCleanup(self.db.close)
        self.owner, self.member, self.outsider = [
            User(
                id=uuid4(), full_name=label, email=f"{label}@example.test",
                league=next(iter(League)), role=UserRole.executor,
            )
            for label in ("owner", "member", "outsider")
        ]
        self.db.add_all([self.owner, self.member, self.outsider])
        self.entity = WorkEntity(
            id=uuid4(), owner_id=self.owner.id, entity_type="project",
            title="Shared project", visibility="shared",
        )
        self.db.add(self.entity)
        self.db.add(WorkEntityMember(
            entity_id=self.entity.id, user_id=self.member.id, role="editor",
            created_by_id=self.owner.id,
        ))
        self.note = QuickNote(
            id=uuid4(), owner_id=self.owner.id, title="Private note title",
            body="Private note contents", context="Private note context",
        )
        self.db.add(self.note)
        self.link = WorkEntityLink(
            id=uuid4(), entity_id=self.entity.id, quick_note_id=self.note.id,
            notes="Private link comment", created_by_id=self.owner.id,
        )
        self.db.add(self.link)
        self.now = datetime.now(timezone.utc)
        await self.db.flush()

    async def drop_schema(self):
        async with self.engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    async def share(self, user=None):
        share = QuickNoteShare(
            note_id=self.note.id, owner_id=self.owner.id,
            recipient_id=(user or self.member).id,
        )
        self.db.add(share)
        await self.db.flush()
        return share

    async def history(self, user=None, limit=100, before=None):
        return await routes.list_work_entity_events(
            self.entity.id, limit=limit,
            before_created_at=before.created_at if before else None,
            before_id=before.id if before else None,
            user=user or self.member, db=self.db,
        )

    def event(self, event_type, payload=None, *, link_id=None, offset=0, legacy=False):
        identifier = link_id or self.link.id
        event = WorkEntityEvent(
            id=uuid4(), entity_id=self.entity.id, actor_id=self.owner.id,
            event_type=event_type,
            object_type=None if legacy else "link",
            object_id=None if legacy else identifier,
            object_title="Private note title",
            reason="Private history reason",
            payload=payload,
            created_at=self.now + timedelta(seconds=offset),
        )
        self.db.add(event)
        return event

    def seed_history(self, *, legacy=False):
        identity = (
            {"link_id": str(self.link.id)} if legacy
            else {"object": {"id": str(self.link.id), "title": self.note.title}}
        )
        added = self.event("link_added", {
            **identity, "target_type": "quick_note", "target_id": str(self.note.id),
        }, legacy=legacy)
        updated = self.event("link_updated", {
            **identity,
            "changes": [{"field": "notes", "from": None, "to": self.link.notes}],
        }, offset=1, legacy=legacy)
        removed = self.event("link_removed", {
            **identity, "target_type": "quick_note",
        }, offset=2, legacy=legacy)
        return [added, updated, removed]

    async def test_private_note_has_no_link_placeholder_or_summary_count(self):
        items = await routes.list_work_entity_links(
            self.entity.id, user=self.member, db=self.db,
        )
        self.assertEqual(items, [])
        summary = await build_entity_summary(self.db, self.entity.id, [self.link], self.member)
        self.assertEqual(summary.accessible_links, 0)
        self.assertEqual(summary.restricted_links, 0)
        self.assertNotIn("quick_note", summary.counts_by_type)

    async def test_list_and_detail_counts_follow_note_acl_including_revoke(self):
        async def count(user, role):
            detail = await routes._entity_read(self.db, self.entity, role, user.id)
            listing = await routes._entity_reads(self.db, [(self.entity, role)], user.id)
            self.assertEqual(detail.links_count, listing[0].links_count)
            return detail.links_count

        self.assertEqual(await count(self.owner, "owner"), 1)
        self.assertEqual(await count(self.member, "editor"), 0)
        share = await self.share()
        self.assertEqual(await count(self.member, "editor"), 1)
        share.status = "revoked"
        await self.db.flush()
        self.assertEqual(await count(self.member, "editor"), 0)
        self.assertEqual(await serialize_links(self.db, [self.link], self.member), [])

    async def test_owner_and_active_recipient_keep_note_link_metadata(self):
        await self.share()
        for user in (self.owner, self.member):
            items = await serialize_links(self.db, [self.link], user)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].target_title, self.note.title)
            self.assertEqual(items[0].notes, self.link.notes)

    async def test_map_has_no_private_note_node_or_edge_including_revoke(self):
        async def note_nodes():
            graph = await build_project_map(self.db, self.entity, "editor", self.member)
            nodes = [node for node in graph.nodes if node.id == f"link:{self.link.id}"]
            edges = [edge for edge in graph.edges if edge.id == f"link:{self.link.id}"]
            self.assertEqual(len(nodes), len(edges))
            return nodes

        self.assertEqual(await note_nodes(), [])
        share = await self.share()
        self.assertEqual((await note_nodes())[0].title, self.note.title)
        share.status = "revoked"
        await self.db.flush()
        self.assertEqual(await note_nodes(), [])

    async def test_map_preserves_other_target_restricted_placeholder(self):
        link = WorkEntityLink(
            id=uuid4(), entity_id=self.entity.id, personal_task_id=uuid4(),
            created_by_id=self.owner.id,
        )
        self.db.add(link)
        await self.db.flush()
        graph = await build_project_map(self.db, self.entity, "editor", self.member)
        nodes = [node for node in graph.nodes if node.node_type == "linked_object"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].id, f"link:{link.id}")
        self.assertFalse(nodes[0].accessible)

    async def test_other_recipient_share_does_not_grant_member_access(self):
        await self.share(self.outsider)
        self.seed_history()
        await self.db.flush()
        self.assertEqual(await serialize_links(self.db, [self.link], self.member), [])
        self.assertEqual(await self.history(), [])

    async def test_other_target_restricted_placeholders_and_counts_are_preserved(self):
        links = []
        for field in ("personal_task_id", "task_id", "deadline_tracker_id", "target_entity_id"):
            link = WorkEntityLink(
                id=uuid4(), entity_id=self.entity.id, **{field: uuid4()},
                notes="Existing non-note link metadata", created_by_id=self.owner.id,
            )
            self.db.add(link)
            links.append(link)
        await self.db.flush()
        items = await serialize_links(self.db, [self.link, *links], self.member)
        self.assertEqual(len(items), 4)
        self.assertTrue(all(not item.target_accessible and item.target_id is None for item in items))
        summary = await build_entity_summary(self.db, self.entity.id, [self.link, *links], self.member)
        self.assertEqual(summary.restricted_links, 4)
        detail = await routes._entity_read(self.db, self.entity, "editor", self.member.id)
        self.assertEqual(detail.links_count, 4)

    async def test_live_link_history_hidden_then_visible_then_hidden_on_revoke(self):
        events = self.seed_history()
        await self.db.flush()
        self.assertEqual(await self.history(), [])
        self.assertEqual(len(await self.history(self.owner)), 3)
        share = await self.share()
        self.assertEqual({event.id for event in await self.history()}, {event.id for event in events})
        share.status = "revoked"
        await self.db.flush()
        self.assertEqual(await self.history(), [])

    async def test_deleted_link_history_recovers_note_from_creation_event(self):
        self.seed_history()
        await self.db.delete(self.link)
        await self.db.flush()
        self.assertEqual(await self.history(), [])
        self.assertEqual(len(await self.history(self.owner)), 3)
        await self.share()
        self.assertEqual(len(await self.history()), 3)

    async def test_legacy_payload_link_id_history_after_delete_and_revoke(self):
        self.seed_history(legacy=True)
        await self.db.delete(self.link)
        await self.db.flush()
        self.assertEqual(await self.history(), [])
        share = await self.share()
        self.assertEqual(len(await self.history()), 3)
        share.status = "revoked"
        await self.db.flush()
        self.assertEqual(await self.history(), [])

    async def test_deleted_note_history_is_not_visible_even_to_project_owner(self):
        self.seed_history()
        await self.db.delete(self.link)
        await self.db.delete(self.note)
        await self.db.flush()
        self.assertEqual(await self.history(self.owner), [])
        self.assertEqual(await self.history(), [])

    async def test_project_owner_has_no_bypass_for_another_users_note(self):
        self.note.owner_id = self.outsider.id
        self.seed_history()
        await self.db.flush()
        self.assertEqual(await serialize_links(self.db, [self.link], self.owner), [])
        self.assertEqual(await self.history(self.owner), [])
        detail = await routes._entity_read(self.db, self.entity, "owner", self.owner.id)
        self.assertEqual(detail.links_count, 0)

    async def test_filter_precedes_pagination_and_preserves_non_link_events(self):
        for offset in range(5):
            self.event("link_updated", offset=offset)
        visible = []
        for offset in (-1, -2):
            event = self.event("entity_updated", offset=offset)
            event.object_type = None
            event.object_id = None
            visible.append(event)
        await self.db.flush()
        page = await self.history(limit=1)
        self.assertEqual([event.id for event in page], [visible[0].id])
        page = await self.history(limit=1, before=page[0])
        self.assertEqual([event.id for event in page], [visible[1].id])

    async def test_unresolved_or_malformed_note_history_fails_closed(self):
        self.event("link_removed", {"target_type": "quick_note", "target_id": "invalid"})
        self.event("link_updated", link_id=uuid4())
        await self.db.flush()
        self.assertEqual(await self.history(), [])

    async def test_origin_from_another_project_cannot_resolve_history(self):
        link_id = uuid4()
        origin = self.event("link_added", {
            "target_type": "personal_task", "target_id": str(uuid4()),
        }, link_id=link_id)
        origin.entity_id = uuid4()
        self.event("link_updated", link_id=link_id)
        await self.db.flush()
        self.assertEqual(await self.history(), [])

    async def test_known_other_target_history_is_not_hidden(self):
        other_id = uuid4()
        self.event("link_added", {
            "target_type": "personal_task", "target_id": str(uuid4()),
        }, link_id=other_id)
        self.event("link_updated", link_id=other_id, offset=1)
        self.event("link_removed", {"target_type": "personal_task"}, link_id=other_id, offset=2)
        await self.db.flush()
        self.assertEqual(len(await self.history()), 3)

    async def test_create_link_returns_404_when_note_access_is_revoked_after_commit(self):
        await self.db.delete(self.link)
        await self.db.flush()

        async def serialize_with_revoked_access(db, links, user):
            if commit.await_count:
                return []
            return await serialize_links(db, links, user)

        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            with patch.object(
                routes, "serialize_links", side_effect=serialize_with_revoked_access,
            ) as serializer:
                with self.assertRaises(HTTPException) as raised:
                    await routes.create_work_entity_link(
                        self.entity.id,
                        WorkEntityLinkCreate(
                            target_type="quick_note", target_id=self.note.id,
                            relation_type="related", notes="Private link comment", position=0,
                        ),
                        user=self.owner, db=self.db,
                    )

        commit.assert_awaited_once()
        self.assertEqual(serializer.await_count, 2)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail, "Связанный объект не найден или недоступен",
        )

    async def test_update_link_returns_404_when_note_access_is_revoked_after_commit(self):
        async def serialize_with_revoked_access(db, links, user):
            if commit.await_count:
                return []
            return await serialize_links(db, links, user)

        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            with patch.object(
                routes, "serialize_links", side_effect=serialize_with_revoked_access,
            ) as serializer:
                with self.assertRaises(HTTPException) as raised:
                    await routes.update_work_entity_link(
                        self.entity.id, self.link.id,
                        WorkEntityLinkUpdate(notes="Changed private note comment"),
                        user=self.owner, db=self.db,
                    )

        commit.assert_awaited_once()
        self.assertEqual(serializer.await_count, 2)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail, "Связанный объект не найден или недоступен",
        )

    async def test_update_link_returns_404_when_note_access_is_revoked_before_commit(self):
        for body in (
            WorkEntityLinkUpdate(),
            WorkEntityLinkUpdate(notes="Changed private note comment"),
        ):
            with self.subTest(changes=body.model_dump(exclude_unset=True)):
                with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
                    with patch.object(routes, "serialize_links", return_value=[]) as serializer:
                        with self.assertRaises(HTTPException) as raised:
                            await routes.update_work_entity_link(
                                self.entity.id, self.link.id, body,
                                user=self.owner, db=self.db,
                            )

                commit.assert_not_awaited()
                serializer.assert_awaited_once()
                self.assertEqual(raised.exception.status_code, 404)
                self.assertEqual(
                    raised.exception.detail, "Связанный объект не найден или недоступен",
                )

    async def test_delete_link_returns_404_when_note_access_is_revoked_before_commit(self):
        with patch.object(self.db, "commit", wraps=self.db.commit) as commit:
            with patch.object(routes, "serialize_links", return_value=[]) as serializer:
                with self.assertRaises(HTTPException) as raised:
                    await routes.delete_work_entity_link(
                        self.entity.id, self.link.id, user=self.owner, db=self.db,
                    )

        commit.assert_not_awaited()
        serializer.assert_awaited_once()
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(
            raised.exception.detail, "Связанный объект не найден или недоступен",
        )
        self.assertNotIn(self.link, self.db.deleted)

    async def test_new_update_and_delete_events_keep_target_identity(self):
        await routes.update_work_entity_link(
            self.entity.id, self.link.id, WorkEntityLinkUpdate(notes="Changed private note comment"),
            user=self.owner, db=self.db,
        )
        await routes.delete_work_entity_link(
            self.entity.id, self.link.id, user=self.owner, db=self.db,
        )
        events = (await self.db.execute(select(WorkEntityEvent))).scalars().all()
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event.payload["target_type"], "quick_note")
            self.assertEqual(event.payload["target_id"], str(self.note.id))
        self.assertEqual(await self.history(), [])
        self.assertEqual(len(await self.history(self.owner)), 2)


if __name__ == "__main__":
    unittest.main()
