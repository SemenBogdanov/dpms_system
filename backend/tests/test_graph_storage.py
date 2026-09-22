"""Isolated contract tests for private graph storage."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, MetaData, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes import graphs
from app.models.graph_document import GraphDocument
from app.models.user import User
from app.services import graph_documents as service


def graph_payload(client_id: str = "graph-test", title: str = "Рабочий граф") -> dict:
    return {
        "version": 2,
        "id": client_id,
        "title": title,
        "createdAt": "2026-09-22T10:00:00Z",
        "updatedAt": "2026-09-22T10:00:00Z",
        "viewport": {"x": 0, "y": 0, "scale": 1},
        "nodes": [
            {
                "id": "node-1",
                "type": "note",
                "title": "Основание",
                "customTypeLabel": "",
                "sourceRef": "NOTE-1",
                "description": "Тестовый элемент",
                "shape": "rounded",
                "radius": 8,
                "scale": 1,
                "pinned": False,
                "color": "#7C55C7",
                "x": 10,
                "y": 20,
            }
        ],
        "edges": [],
        "groups": [],
        "views": [
            {
                "id": "view-1",
                "name": "Основной вид",
                "layout": "radial",
                "positions": {"node-1": {"x": 10, "y": 20}},
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "focusNodeId": None,
                "focusDepth": 0,
            }
        ],
        "activeViewId": "view-1",
        "audit": [
            {"id": "audit-1", "at": "2026-09-22T10:00:00Z", "action": "Создан граф"}
        ],
    }


class GraphStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(self.engine.sync_engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.restores = []
        schema = MetaData()
        for model in [User, GraphDocument]:
            for column in model.__table__.columns:
                if isinstance(column.type, JSONB):
                    self.restores.append((column, column.type))
                    column.type = JSON()
            model.__table__.to_metadata(schema)
        async with self.engine.begin() as connection:
            await connection.run_sync(schema.create_all)

        self.db = AsyncSession(self.engine, expire_on_commit=False)
        self.owner = User(
            id=uuid4(), full_name="Owner", email="owner.graphs@example.invalid", league="A", role="executor"
        )
        self.admin = User(
            id=uuid4(), full_name="Admin", email="admin.graphs@example.invalid", league="A", role="admin"
        )
        self.db.add_all([self.owner, self.admin])
        await self.db.commit()
        self.user = self.owner

        app = FastAPI()
        app.include_router(graphs.router, prefix="/api/graphs")

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
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()
        for column, column_type in reversed(self.restores):
            column.type = column_type

    async def put(self, payload: dict, base_revision: int | None = None):
        return await self.client.put(
            f"/api/graphs/{payload['id']}",
            json={"base_revision": base_revision, "payload": payload},
        )

    async def test_create_list_read_update_and_delete(self):
        payload = graph_payload()
        created = await self.put(payload)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["revision"], 1)
        self.assertEqual((await self.client.get("/api/graphs")).json()[0]["client_id"], payload["id"])
        self.assertEqual((await self.client.get(f"/api/graphs/{payload['id']}")).json()["payload"]["title"], "Рабочий граф")

        payload["title"] = "Обновлённый граф"
        payload["updatedAt"] = "2026-09-22T10:05:00Z"
        updated = await self.put(payload, 1)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["revision"], 2)
        deleted = await self.client.delete(f"/api/graphs/{payload['id']}?base_revision=2")
        self.assertEqual(deleted.json(), {"deleted": True, "client_id": payload["id"]})
        self.assertEqual((await self.client.get("/api/graphs")).json(), [])

    async def test_identical_retry_is_idempotent_but_stale_change_conflicts(self):
        payload = graph_payload()
        first = await self.put(payload)
        repeated = await self.put(payload)
        self.assertEqual(first.json()["revision"], 1)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["revision"], 1)

        changed = graph_payload(title="Изменение")
        response = await self.put(changed)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "graph_already_exists")

        response = await self.put(changed, 9)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "graph_revision_conflict")
        self.assertEqual(response.json()["detail"]["server_revision"], 1)

    async def test_admin_has_no_access_to_another_users_graphs(self):
        payload = graph_payload()
        self.assertEqual((await self.put(payload)).status_code, 200)
        self.user = self.admin
        self.assertEqual((await self.client.get("/api/graphs")).json(), [])
        self.assertEqual((await self.client.get(f"/api/graphs/{payload['id']}")).status_code, 404)
        self.assertEqual((await self.client.delete(f"/api/graphs/{payload['id']}?base_revision=1")).status_code, 404)

    async def test_graph_and_total_storage_limits_are_enforced(self):
        payload = graph_payload()
        with patch.object(service, "MAX_GRAPH_BYTES", 10):
            response = await self.put(payload)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"]["code"], "graph_too_large")

        with patch.object(service, "MAX_TOTAL_BYTES_PER_USER", 10):
            response = await self.put(payload)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"]["code"], "graph_storage_limit")

        with patch.object(service, "MAX_GRAPHS_PER_USER", 0):
            response = await self.put(payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "graph_count_limit")

    async def test_invalid_references_and_path_payload_mismatch_are_rejected(self):
        payload = graph_payload()
        payload["edges"] = [{"id": "edge-1", "source": "node-1", "target": "missing", "label": "связано"}]
        self.assertEqual((await self.put(payload)).status_code, 422)

        payload = graph_payload()
        response = await self.client.put(
            "/api/graphs/different-id",
            json={"base_revision": None, "payload": payload},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "graph_id_mismatch")


class GraphMigrationContractTests(unittest.TestCase):
    def test_migration_chain(self):
        path = Path(__file__).parents[1] / "alembic/versions/096_graph_documents.py"
        spec = importlib.util.spec_from_file_location("graph_documents_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.revision, "096_graph_documents")
        self.assertEqual(migration.down_revision, "095_web_push")
        self.assertLessEqual(len(migration.revision), 32)


if __name__ == "__main__":
    unittest.main()
