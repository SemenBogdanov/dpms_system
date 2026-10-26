"""Isolated contract tests for private graph storage."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes import graphs
from app.models.graph_document import GraphDocument
from app.models.user import User
from app.schemas.graph import GraphEdge, GraphPayload
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

    async def test_version_3_interaction_fields_round_trip(self):
        payload = graph_payload(client_id="graph-v3", title="Интерактивный граф")
        payload["version"] = 3
        payload["nodes"] = [
            {
                **payload["nodes"][0],
                "type": "list",
                "autoSize": False,
                "width": 320,
                "height": 180,
                "items": ["Первый атом", "Второй атом"],
            },
            {
                **payload["nodes"][0],
                "id": "node-2",
                "type": "atom",
                "title": "Первый атом",
                "x": 420,
                "autoSize": True,
                "width": 190,
                "height": 96,
                "items": [],
            },
        ]
        payload["edges"] = [
            {
                "id": "edge-1",
                "source": "node-1",
                "target": "node-2",
                "label": "атом",
                "routing": "orthogonal",
                "points": [{"x": 300, "y": 80}, {"x": 360, "y": 80}],
            }
        ]
        payload["views"][0]["positions"]["node-2"] = {"x": 420, "y": 20}
        payload["views"][0]["connectionLensEnabled"] = True

        created = await self.put(payload)

        self.assertEqual(created.status_code, 200, created.text)
        saved = created.json()["payload"]
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["nodes"][0]["items"], ["Первый атом", "Второй атом"])
        self.assertEqual(saved["nodes"][0]["width"], 320)
        self.assertEqual(saved["edges"][0]["routing"], "orthogonal")
        self.assertEqual(saved["edges"][0]["points"][1], {"x": 360.0, "y": 80.0})
        self.assertTrue(saved["views"][0]["connectionLensEnabled"])

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

    async def test_edge_ports_round_trip_and_clear_without_migration(self):
        for version in (2, 3):
            with self.subTest(version=version):
                payload = graph_payload(client_id=f"graph-ports-v{version}")
                payload["version"] = version
                payload["nodes"].append({**payload["nodes"][0], "id": "node-2", "x": 420})
                payload["edges"] = [{
                    "id": "edge-1", "source": "node-1", "target": "node-2", "label": "ports",
                    "sourcePort": "e:4", "targetPort": "n:0",
                }]
                created = await self.put(payload)
                self.assertEqual(created.status_code, 200, created.text)
                read = await self.client.get(f"/api/graphs/{payload['id']}")
                self.assertEqual(read.status_code, 200, read.text)
                edge = read.json()["payload"]["edges"][0]
                self.assertEqual(edge["sourcePort"], "e:4")
                self.assertEqual(edge["targetPort"], "n:0")

                payload["edges"][0].update(sourcePort=None, targetPort=None)
                updated = await self.put(payload, created.json()["revision"])
                self.assertEqual(updated.status_code, 200, updated.text)
                read = await self.client.get(f"/api/graphs/{payload['id']}")
                edge = read.json()["payload"]["edges"][0]
                self.assertIsNone(edge["sourcePort"])
                self.assertIsNone(edge["targetPort"])

    async def test_invalid_edge_ports_are_rejected_without_saving(self):
        payload = graph_payload(client_id="graph-invalid-ports")
        payload["nodes"].append({**payload["nodes"][0], "id": "node-2", "x": 420})
        edge = {"id": "edge-1", "source": "node-1", "target": "node-2", "label": "ports"}
        for field in ("sourcePort", "targetPort"):
            with self.subTest(field=field):
                payload["edges"] = [{**edge, field: "n:5"}]
                response = await self.put(payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual((await self.client.get(f"/api/graphs/{payload['id']}")).status_code, 404)

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


class GraphEdgePortTests(unittest.TestCase):
    def edge(self, **ports):
        return GraphEdge(id="edge-1", source="node-1", target="node-2", label="ports", **ports)

    def test_missing_and_null_ports_default_to_none(self):
        for ports in ({}, {"sourcePort": None}, {"targetPort": None}, {"sourcePort": None, "targetPort": None}):
            with self.subTest(ports=ports):
                edge = self.edge(**ports)
                self.assertIsNone(edge.sourcePort)
                self.assertIsNone(edge.targetPort)

    def test_all_twenty_ports_are_valid_on_either_end(self):
        for side in "nesw":
            for index in range(5):
                port = f"{side}:{index}"
                for ports in ({"sourcePort": port}, {"targetPort": port}, {"sourcePort": port, "targetPort": port}):
                    with self.subTest(ports=ports):
                        edge = self.edge(**ports)
                        restored = GraphEdge.model_validate_json(edge.model_dump_json())
                        self.assertEqual(restored.sourcePort, ports.get("sourcePort"))
                        self.assertEqual(restored.targetPort, ports.get("targetPort"))

    def test_payload_json_round_trip_preserves_ports_and_connection_lens(self):
        for version in (2, 3):
            with self.subTest(version=version):
                payload = graph_payload()
                payload["version"] = version
                payload["nodes"].append({**payload["nodes"][0], "id": "node-2", "x": 420})
                payload["views"][0]["connectionLensEnabled"] = True
                payload["edges"] = [{
                    "id": "edge-1", "source": "node-1", "target": "node-2", "label": "ports",
                    "sourcePort": "s:3", "targetPort": "w:1",
                }]
                model = GraphPayload.model_validate(payload)
                restored = GraphPayload.model_validate_json(model.model_dump_json())
                self.assertEqual(restored, model)
                self.assertEqual(restored.edges[0].sourcePort, "s:3")
                self.assertEqual(restored.edges[0].targetPort, "w:1")
                self.assertTrue(restored.views[0].connectionLensEnabled)

    def test_invalid_port_values_are_rejected(self):
        invalid = ("", "N:0", "x:0", "north:0", "n", "n:-1", "n:5", "e:10", "w:00", "s:1.0", "n:0\n", " n:0", "n:0 ", 0, True, [], {})
        for field in ("sourcePort", "targetPort"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        self.edge(**{field: value})


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
