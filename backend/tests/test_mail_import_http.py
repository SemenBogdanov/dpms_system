"""Isolated HTTP tests and opt-in tests against disposable PostgreSQL only.

No app settings, .env, real User model, auth implementation or Alembic env is
imported. PostgreSQL requires BOTH OUTLOOK_TEST_POSTGRES=1 and an explicit
OUTLOOK_TEST_DATABASE_URL with driver postgresql+asyncpg and database name
dpms_outlook_test. Only loopback TCP or an owned private 0700 Unix socket
directory /tmp/dpms-outlook-pg.* is accepted. DATABASE_URL is ignored.
Each test creates/drops only its own randomly named schema. Run with unittest
discover -s /absolute/path/backend/tests -p 'test_mail_import*.py' from any cwd.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import importlib.util
import os
from pathlib import Path
import re
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from test_mail_import import BACKEND, NOW, attachment_payload, isolated_app, item_payload, load_source, require_dependencies, sync_payload


PREFIX = "/api/mail-import"


class OfflineHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        require_dependencies(self)
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        context = isolated_app()
        self.bundle = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.events = []
        self.db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: self.events.append("commit")), rollback=AsyncMock())
        self.actor = SimpleNamespace(id=uuid4(), auth_version=0)
        app = FastAPI()
        app.include_router(self.bundle.routes.router, prefix=PREFIX)

        async def database():
            yield self.db

        async def owner():
            return self.actor

        app.dependency_overrides[self.bundle.deps.get_db] = database
        app.dependency_overrides[self.bundle.deps.get_current_user] = owner

        async def recorded(scope, receive, send):
            async def recorded_send(message):
                if message["type"] == "http.response.start":
                    self.events.append("response")
                await send(message)
            await app(scope, receive, recorded_send)

        self.client = AsyncClient(transport=ASGITransport(app=recorded), base_url="https://test.invalid")
        self.addAsyncCleanup(self.client.aclose)

    def pair_result(self):
        return self.bundle.schema.PairRead(device_id=uuid4(), device_secret="s" * 43, owner_name="Synthetic owner", include_body=False)

    async def test_commit_precedes_response_and_no_store_on_pair(self):
        with patch.object(self.bundle.service, "pair_device", AsyncMock(return_value=self.pair_result())):
            response = await self.client.post(PREFIX + "/pair", json={"pairing_code": "c" * 43})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.events, ["commit", "response"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_commit_failure_never_returns_one_time_material(self):
        from sqlalchemy.exc import SQLAlchemyError
        self.db.commit.side_effect = SQLAlchemyError("synthetic private diagnostic")
        with patch.object(self.bundle.service, "pair_device", AsyncMock(return_value=self.pair_result())):
            response = await self.client.post(PREFIX + "/pair", json={"pairing_code": "c" * 43})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("s" * 43, response.text)
        self.assertNotIn("private", response.text)
        self.db.rollback.assert_awaited_once()

    async def test_service_conflict_rolls_back_without_success(self):
        with patch.object(self.bundle.service, "sync_items", AsyncMock(side_effect=self.bundle.service.error(409, "item_version_conflict"))):
            response = await self.client.post(PREFIX + "/sync", json=sync_payload(), headers={"Authorization": "Bearer " + "s" * 43})
        self.assertEqual(response.status_code, 409)
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_awaited_once()

    async def test_declared_and_streamed_byte_limits_precede_json_parsing(self):
        from starlette.requests import Request
        maximum = self.bundle.schema.MAX_BATCH_BYTES
        with patch.object(Request, "json", AsyncMock(side_effect=AssertionError("must not parse oversized JSON"))):
            response = await self.client.post(PREFIX + "/sync", content=b"x", headers={
                "Content-Type": "application/json", "Content-Length": str(maximum + 1),
                "Authorization": "Bearer " + "s" * 43,
            })
            self.assertEqual(response.status_code, 413)

            async def chunks():
                yield b"x" * maximum
                yield b"y"

            for declared in ({}, {"Content-Length": "1"}):
                response = await self.client.post(PREFIX + "/sync", content=chunks(), headers={
                    "Content-Type": "application/json", **declared,
                    "Authorization": "Bearer " + "s" * 43,
                })
                self.assertEqual(response.status_code, 413)
        self.db.commit.assert_not_awaited()

    async def test_malformed_http_and_schema_errors_do_not_echo_values(self):
        marker = "synthetic-private-marker"
        requests = [
            ("/pair", {"json": {"pairing_code": marker}}, 422),
            ("/pair", {"content": ('{"pairing_code":"' + marker).encode(), "headers": {"Content-Type": "application/json"}}, 422),
            ("/devices", {"json": {"name": "Laptop", "owner_id": marker}}, 422),
            ("/sync", {"json": sync_payload(items=[item_payload(subject=marker)] * 51)}, 422),
            ("/sync", {"json": sync_payload(items=[item_payload(sender_address=marker, received_at="bad")])}, 422),
            ("/sync", {"content": b"{}", "headers": {"Content-Type": "application/json", "Content-Length": "no"}}, 400),
            ("/sync", {"content": b"{}", "headers": {"Content-Type": "application/json", "Content-Encoding": "gzip"}}, 415),
            ("/sync", {"content": marker, "headers": {"Content-Type": "text/plain"}}, 415),
        ]
        for path, kwargs, expected in requests:
            with self.subTest(path=path, expected=expected):
                if path == "/sync":
                    kwargs = {**kwargs, "headers": {"Authorization": "Bearer " + "s" * 43, **kwargs.get("headers", {})}}
                response = await self.client.post(PREFIX + path, **kwargs)
                self.assertEqual(response.status_code, expected)
                self.assertNotIn(marker, response.text)
                self.assertNotIn("input", response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
        self.db.commit.assert_not_awaited()

    async def test_missing_and_wrong_bearer_are_401_and_query_bounds_422(self):
        for headers in ({}, {"Authorization": "Basic synthetic"}, {"Authorization": "Bearer"}):
            response = await self.client.post(PREFIX + "/sync", json=sync_payload(), headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
        for query in ("limit=0", "limit=101", "offset=-1", "kind=calendar"):
            self.assertEqual((await self.client.get(PREFIX + "/items?" + query)).status_code, 422)

    async def test_sync_rejects_bad_bearer_before_any_body_read_or_json_parse(self):
        from starlette.requests import Request
        invalid_headers = (
            {}, {"Authorization": "Basic synthetic"}, {"Authorization": "Bearer"},
            {"Authorization": "Bearer " + "s" * 42}, {"Authorization": "Bearer " + "s" * 44},
            {"Authorization": "Bearer " + "!" * 43},
            [("Authorization", "Bearer " + "s" * 43), ("Authorization", "Bearer " + "x" * 43)],
        )
        with patch.object(Request, "stream", side_effect=AssertionError("body must not be read")) as stream:
            with patch.object(Request, "json", AsyncMock(side_effect=AssertionError("JSON must not be parsed"))) as parser:
                for headers in invalid_headers:
                    response = await self.client.post(PREFIX + "/sync", content=b"synthetic-private-body", headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertNotIn("synthetic-private-body", response.text)
                stream.assert_not_called()
                parser.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_attachment_validation_errors_never_echo_bytes_or_metadata(self):
        marker = "synthetic-private-marker"
        attachment = attachment_payload(marker.encode(), filename=marker, sha256="0" * 64)
        response = await self.client.post(PREFIX + "/sync", json=sync_payload([item_payload(attachments=[attachment])]), headers={"Authorization": "Bearer " + "s" * 43})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertNotIn(attachment["data_base64"], response.text)

    async def test_download_forces_attachment_nosniff_no_store_after_commit(self):
        filename = "\u043e\u0442\u0447\u0451\u0442\r\n.html"
        with patch.object(self.bundle.service, "download_attachment", AsyncMock(return_value=(filename, b"<script>synthetic</script>"))):
            response = await self.client.get(PREFIX + f"/items/{uuid4()}/attachments/{uuid4()}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])
        self.assertNotIn("\r", response.headers["content-disposition"])
        self.assertEqual(self.events, ["commit", "response"])

    async def test_gateway_has_only_pair_and_sync_and_no_startup_handlers(self):
        from httpx import ASGITransport, AsyncClient
        gateway = load_source("_outlook_gateway_test", BACKEND / "app/mail_import_gateway.py")
        self.assertEqual({(path, tuple(method.upper() for method in methods)) for path, methods in gateway.app.openapi()["paths"].items()}, {
            (PREFIX + "/pair", ("POST",)), (PREFIX + "/sync", ("POST",)),
        })
        self.assertEqual(gateway.app.router.on_startup, [])
        self.assertEqual(gateway.app.router.on_shutdown, [])
        async with AsyncClient(transport=ASGITransport(app=gateway.app), base_url="https://test.invalid") as client:
            for path in ("/devices", "/items", "/docs", "/openapi.json"):
                self.assertEqual((await client.get(PREFIX + path)).status_code, 404)


def disposable_url():
    from sqlalchemy.engine import make_url
    raw = os.environ.get("OUTLOOK_TEST_DATABASE_URL")
    if os.environ.get("OUTLOOK_TEST_POSTGRES") != "1" or not raw:
        raise RuntimeError("Explicit disposable PostgreSQL opt-in and OUTLOOK_TEST_DATABASE_URL required")
    try:
        url = make_url(raw)
    except Exception:
        raise RuntimeError("Invalid disposable PostgreSQL test URL") from None
    if url.drivername != "postgresql+asyncpg" or url.database != "dpms_outlook_test":
        raise RuntimeError("Only dpms_outlook_test via asyncpg is allowed")
    if url.host in {"localhost", "127.0.0.1", "::1"} and not url.query:
        return url
    if url.host is not None or url.port is not None or set(url.query) != {"host", "port"}:
        raise RuntimeError("Only loopback TCP or an explicit private disposable Unix socket is allowed")
    host, port = url.query["host"], url.query["port"]
    if not isinstance(host, str) or not re.fullmatch(r"/(?:private/)?tmp/dpms-outlook-pg\.[A-Za-z0-9_-]+", host):
        raise RuntimeError("Unexpected disposable Unix socket directory")
    if not isinstance(port, str) or not port.isascii() or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise RuntimeError("Explicit nonprivileged disposable PostgreSQL port required")
    try:
        info = Path(host).lstat()
    except OSError:
        raise RuntimeError("Disposable Unix socket directory does not exist") from None
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
        raise RuntimeError("Disposable Unix socket directory must be owned, private 0700 and not a symlink")
    return url


class HarnessGuardTests(unittest.TestCase):
    def test_production_or_implicit_database_is_rejected_without_connecting(self):
        if importlib.util.find_spec("sqlalchemy") is None:
            self.skipTest("Offline environment lacks sqlalchemy")
        cases = (
            {}, {"DATABASE_URL": "postgresql+asyncpg://localhost/dpms_outlook_test"},
            {"OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg://localhost/dpms_outlook_test"},
            {"OUTLOOK_TEST_POSTGRES": "1", "OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg://localhost/production"},
            {"OUTLOOK_TEST_POSTGRES": "1", "OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg://remote.invalid/dpms_outlook_test"},
            {"OUTLOOK_TEST_POSTGRES": "1", "OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg://localhost/dpms_outlook_test?host=remote.invalid"},
            {"OUTLOOK_TEST_POSTGRES": "1", "OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg:///dpms_outlook_test?host=/tmp&port=55439"},
        )
        for environment in cases:
            with self.subTest(environment=list(environment)), patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(RuntimeError):
                    disposable_url()
        with patch.dict(os.environ, {
            "OUTLOOK_TEST_POSTGRES": "1",
            "OUTLOOK_TEST_DATABASE_URL": "postgresql+asyncpg://127.0.0.1/dpms_outlook_test",
        }, clear=True):
            self.assertEqual(disposable_url().database, "dpms_outlook_test")

    def test_private_socket_guard_without_connecting(self):
        if importlib.util.find_spec("sqlalchemy") is None:
            self.skipTest("Offline environment lacks sqlalchemy")
        with tempfile.TemporaryDirectory(prefix="dpms-outlook-pg.", dir="/tmp") as directory:
            with patch.dict(os.environ, {
                "OUTLOOK_TEST_POSTGRES": "1",
                "OUTLOOK_TEST_DATABASE_URL": f"postgresql+asyncpg://synthetic@/dpms_outlook_test?host={directory}&port=55439",
            }, clear=True):
                self.assertEqual(disposable_url().query["host"], directory)
                os.chmod(directory, 0o755)
                with self.assertRaises(RuntimeError):
                    disposable_url()


@unittest.skipUnless(os.getenv("OUTLOOK_TEST_POSTGRES") == "1", "disposable PostgreSQL opt-in required")
class PostgresHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        require_dependencies(self)
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.schema import CreateSchema

        context = isolated_app()
        self.bundle = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.schema_name = "outlook_test_" + uuid4().hex
        self.engine = create_async_engine(disposable_url(), echo=False, hide_parameters=True, connect_args={
            "server_settings": {"search_path": self.schema_name, "statement_timeout": "10000", "lock_timeout": "5000"},
        })
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            if await connection.scalar(text("SELECT current_database()")) != "dpms_outlook_test":
                raise RuntimeError("Disposable database identity check failed")
            await connection.execute(CreateSchema(self.schema_name))
        self.addAsyncCleanup(self.drop_schema)
        self.migration = load_source("_outlook_migration_" + self.schema_name, BACKEND / "alembic/versions/100_mail_import.py")
        async with self.engine.begin() as connection:
            await connection.run_sync(self.bundle.User.__table__.create)
            await connection.run_sync(lambda conn: self.run_migration(conn, "upgrade"))
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.owner = SimpleNamespace(id=uuid4(), auth_version=0)
        self.other = SimpleNamespace(id=uuid4(), auth_version=0)
        self.actor = self.owner
        async with self.factory.begin() as db:
            db.add_all([
                self.bundle.User(id=self.owner.id, full_name="Synthetic owner", is_active=True, auth_version=0),
                self.bundle.User(id=self.other.id, full_name="Synthetic other", is_active=True, auth_version=0),
            ])
        app = FastAPI()
        app.include_router(self.bundle.routes.router, prefix=PREFIX)

        async def current_user():
            return self.actor

        async def database():
            async with self.factory() as db:
                try:
                    yield db
                finally:
                    # Deliberately no dependency commit: only explicit route commits persist.
                    await db.rollback()

        app.dependency_overrides[self.bundle.deps.get_current_user] = current_user
        app.dependency_overrides[self.bundle.deps.get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="https://test.invalid")
        self.addAsyncCleanup(self.client.aclose)

    async def drop_schema(self):
        from sqlalchemy.schema import DropSchema
        async with self.engine.begin() as connection:
            await connection.execute(DropSchema(self.schema_name, cascade=True))

    def run_migration(self, connection, direction):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(connection)):
            getattr(self.migration, direction)()

    async def create(self, *, include_body=False, include_attachments=False):
        response = await self.client.post(PREFIX + "/devices", json={"name": "Synthetic laptop", "include_body": include_body, "include_attachments": include_attachments})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def paired(self, *, include_body=False, include_attachments=False):
        created = await self.create(include_body=include_body, include_attachments=include_attachments)
        response = await self.client.post(PREFIX + "/pair", json={"pairing_code": created["pairing_code"]})
        self.assertEqual(response.status_code, 200, response.text)
        return created, response.json()

    async def sync(self, paired, items=None, **changes):
        return await self.client.post(PREFIX + "/sync", json=sync_payload(items, **changes), headers={
            "Authorization": "Bearer " + paired["device_secret"],
        })

    async def listing(self, **params):
        response = await self.client.get(PREFIX + "/items", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def set_device(self, device_id, **changes):
        from sqlalchemy import update
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.models.MailImportDevice).where(
                self.bundle.models.MailImportDevice.id == UUID(str(device_id)),
            ).values(**changes))

    async def set_owner(self, **changes):
        from sqlalchemy import update
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(**changes))

    async def capture_flags(self, item_id):
        async with self.factory() as db:
            row = await db.get(self.bundle.models.MailImportItem, UUID(item_id))
            return row.body_captured, row.attachments_captured

    async def test_pair_single_use_hash_at_rest_and_normal_response_redaction(self):
        created = await self.create()
        code = created["pairing_code"]
        self.assertEqual(len(code), 43)
        async with self.factory() as db:
            row = await db.get(self.bundle.models.MailImportDevice, UUID(created["device"]["id"]))
            self.assertEqual(row.pairing_code_hash, self.bundle.service.digest(code, "pair"))
            self.assertNotEqual(row.pairing_code_hash, code)
            self.assertIsNone(row.device_secret_hash)
        response = await self.client.post(PREFIX + "/pair", json={"pairing_code": code})
        self.assertEqual(response.status_code, 200)
        paired = response.json()
        replay = await self.client.post(PREFIX + "/pair", json={"pairing_code": code})
        self.assertEqual(replay.status_code, 401)
        async with self.factory() as db:
            row = await db.get(self.bundle.models.MailImportDevice, UUID(paired["device_id"]))
            self.assertIsNone(row.pairing_code_hash)
            self.assertEqual(row.device_secret_hash, self.bundle.service.digest(paired["device_secret"], "device"))
        public = await self.client.get(PREFIX + "/devices")
        self.assertNotIn(code, public.text)
        self.assertNotIn(paired["device_secret"], public.text)
        self.assertNotIn("hash", public.text)
        self.assertEqual(public.json()[0]["status"], "active")

    async def test_concurrent_pair_has_exactly_one_winner(self):
        created = await self.create()
        responses = await asyncio.gather(*[
            self.client.post(PREFIX + "/pair", json={"pairing_code": created["pairing_code"]}) for _ in range(3)
        ])
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401, 401])
        winner = next(response.json() for response in responses if response.status_code == 200)
        self.assertEqual((await self.sync(winner, [])).status_code, 200)

    async def test_owner_isolation_including_revoke_detail_read_and_payload(self):
        created, paired = await self.paired()
        self.assertEqual((await self.sync(paired)).status_code, 200)
        item = (await self.listing())["items"][0]
        self.actor = self.other
        self.assertEqual((await self.client.get(PREFIX + "/devices")).json(), [])
        self.assertEqual((await self.listing())["total"], 0)
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item["id"])).status_code, 404)
        self.assertEqual((await self.client.post(PREFIX + "/items/" + item["id"] + "/read", json={})).status_code, 404)
        self.assertEqual((await self.client.post(PREFIX + "/devices/" + created["device"]["id"] + "/revoke", json={})).status_code, 404)
        self.assertEqual((await self.client.post(PREFIX + "/devices", json={"name": "Spoof", "owner_id": str(self.owner.id)})).status_code, 422)

    async def test_versions_counts_read_state_and_no_implicit_read(self):
        _, paired = await self.paired()
        created = await self.sync(paired, [item_payload(), item_payload()])
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual({k: created.json()[k] for k in ("accepted", "created", "unchanged")}, {"accepted": 2, "created": 1, "unchanged": 1})
        listed = await self.listing()
        self.assertEqual((listed["total"], listed["unread_count"]), (1, 1))
        item_id = listed["items"][0]["id"]
        self.assertFalse((await self.client.get(PREFIX + "/items/" + item_id)).json()["is_read"])
        self.assertEqual((await self.listing())["unread_count"], 1)
        self.assertTrue((await self.client.post(PREFIX + "/items/" + item_id + "/read", json={})).json()["is_read"])
        duplicate = await self.sync(paired)
        self.assertEqual(duplicate.json()["unchanged"], 1)
        source_read = await self.sync(paired, [item_payload(source_is_read=True, source_modified_at=(NOW + timedelta(seconds=1)).isoformat())])
        self.assertEqual(source_read.json()["unchanged"], 1)
        stale = await self.sync(paired, [item_payload(subject="Old", source_modified_at=(NOW - timedelta(seconds=1)).isoformat())])
        self.assertEqual(stale.json()["stale"], 1)
        self.assertEqual((await self.listing())["unread_count"], 0)
        changed = await self.sync(paired, [item_payload(subject="New", source_modified_at=(NOW + timedelta(seconds=2)).isoformat())])
        self.assertEqual(changed.json()["updated"], 1)
        self.assertEqual((await self.listing())["unread_count"], 1)
        replay = await self.sync(paired, [])
        self.assertEqual(replay.json()["accepted"], 0)
        self.assertEqual((await self.listing())["total"], 1)

    async def test_equal_version_conflict_rolls_back_every_item_and_heartbeat(self):
        created, paired = await self.paired()
        self.assertEqual((await self.sync(paired)).status_code, 200)
        before = (await self.client.get(PREFIX + "/devices")).json()[0]
        response = await self.sync(paired, [item_payload(source_id="c" * 64), item_payload(subject="Conflict")], scan_complete=False, skipped_items=3)
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.listing())["total"], 1)
        after = (await self.client.get(PREFIX + "/devices")).json()[0]
        self.assertEqual(after["last_sync_at"], before["last_sync_at"])
        self.assertEqual(after["last_scan_complete"], before["last_scan_complete"])
        self.assertEqual(after["last_skipped_items"], before["last_skipped_items"])
        fresh, fresh_pair = await self.paired()
        response = await self.sync(fresh_pair, [item_payload(source_id="d" * 64), item_payload(source_id="d" * 64, subject="Conflict")])
        self.assertEqual(response.status_code, 409)
        async with self.factory() as db:
            row = await db.get(self.bundle.models.MailImportDevice, UUID(fresh["device"]["id"]))
            self.assertIsNone(row.mailbox_id)
            self.assertIsNone(row.last_sync_at)

    async def test_body_grant_list_redaction_and_mailbox_binding(self):
        _, metadata_pair = await self.paired()
        for body in ({"body_text": ""}, {"body_text": "Synthetic body"}, {"body_html": "<script>synthetic</script>"}):
            response = await self.sync(metadata_pair, [item_payload(**body)])
            self.assertEqual(response.status_code, 403)
        self.assertEqual((await self.listing())["total"], 0)
        _, paired = await self.paired(include_body=True)
        response = await self.sync(paired, [item_payload(body_text="Synthetic body", body_html="<p>Stored only</p>", to_recipients="to@example.invalid", cc_recipients="cc@example.invalid")])
        self.assertEqual(response.status_code, 200, response.text)
        item = (await self.listing())["items"][0]
        self.assertIsNone(item["body_text"])
        self.assertIsNone(item["body_html"])
        detail = await self.client.get(PREFIX + "/items/" + item["id"])
        self.assertEqual(detail.json()["body_text"], "Synthetic body")
        self.assertEqual(detail.json()["body_html"], "<p>Stored only</p>")
        self.assertEqual(detail.json()["to_recipients"], "to@example.invalid")
        self.assertEqual((await self.sync(paired, [], mailbox_id="c" * 64)).status_code, 409)

    async def test_full_import_blocks_metadata_newer_batch_without_data_loss(self):
        metadata_created, metadata = await self.paired()
        self.assertEqual((await self.sync(metadata, [])).status_code, 200)
        _, full = await self.paired(include_body=True, include_attachments=True)
        payload = item_payload(body_text="Keep text", body_html="<p>Keep HTML</p>", attachments=[attachment_payload(b"keep file")])
        self.assertEqual((await self.sync(full, [payload])).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        await self.client.post(PREFIX + "/items/" + item_id + "/read", json={})
        before = (await self.client.get(PREFIX + "/items/" + item_id)).json()
        devices = {row["id"]: row for row in (await self.client.get(PREFIX + "/devices")).json()}
        response = await self.sync(metadata, [
            item_payload(source_modified_at=(NOW + timedelta(seconds=1)).isoformat()),
            item_payload(source_id="c" * 64),
        ], scan_complete=False, skipped_items=1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "mailbox_scope_mismatch")
        self.assertEqual((await self.listing())["total"], 1)
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item_id)).json(), before)
        self.assertEqual(await self.capture_flags(item_id), (True, True))
        after_devices = {row["id"]: row for row in (await self.client.get(PREFIX + "/devices")).json()}
        self.assertEqual(after_devices[metadata_created["device"]["id"]], devices[metadata_created["device"]["id"]])
        download = await self.client.get(PREFIX + "/items/" + item_id + "/attachments/" + before["attachments"][0]["id"])
        self.assertEqual(download.content, b"keep file")

    async def test_metadata_to_full_same_version_enriches_without_resetting_read(self):
        _, metadata = await self.paired()
        self.assertEqual((await self.sync(metadata)).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        self.assertEqual(await self.capture_flags(item_id), (False, False))
        await self.client.post(PREFIX + "/items/" + item_id + "/read", json={})
        _, full = await self.paired(include_body=True, include_attachments=True)
        enriched = item_payload(body_text="Enriched", body_html="<p>Enriched</p>", attachments=[attachment_payload(b"file")], source_is_read=True)
        response = await self.sync(full, [enriched])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 1)
        detail = (await self.client.get(PREFIX + "/items/" + item_id)).json()
        self.assertTrue(detail["is_read"])
        self.assertEqual(detail["body_text"], "Enriched")
        self.assertEqual(await self.capture_flags(item_id), (True, True))
        self.assertEqual((await self.sync(full, [enriched])).json()["unchanged"], 1)
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item_id)).json(), detail)
        self.assertEqual((await self.sync(metadata)).status_code, 409)

    async def test_enrichment_rejects_metadata_and_captured_body_changes(self):
        _, body_only = await self.paired(include_body=True)
        self.assertEqual((await self.sync(body_only, [item_payload(body_text="Keep")])).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        await self.client.post(PREFIX + "/items/" + item_id + "/read", json={})
        full_created, full = await self.paired(include_body=True, include_attachments=True)
        file = attachment_payload(b"new file")
        for changes in ({"body_text": "Changed"}, {"subject": "Changed"}, {"to_recipients": "changed@example.invalid"}):
            response = await self.sync(full, [{**item_payload(body_text="Keep", attachments=[file]), **changes}])
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "item_version_conflict")
            self.assertEqual(await self.capture_flags(item_id), (True, False))
        async with self.factory() as db:
            device = await db.get(self.bundle.models.MailImportDevice, UUID(full_created["device"]["id"]))
            self.assertIsNone(device.mailbox_id)
        valid = item_payload(body_text="Keep", attachments=[file])
        self.assertEqual((await self.sync(full, [valid])).status_code, 200)
        detail = (await self.client.get(PREFIX + "/items/" + item_id)).json()
        self.assertEqual(detail["body_text"], "Keep")
        self.assertTrue(detail["is_read"])
        for changed in (item_payload(body_text="Different", attachments=[file]), item_payload(body_text="Keep", attachments=[attachment_payload(b"different")])):
            response = await self.sync(full, [changed])
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "item_version_conflict")
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item_id)).json(), detail)

    async def test_body_enrichment_preserves_captured_attachment_ids_and_quota(self):
        _, attachments_only = await self.paired(include_attachments=True)
        file = attachment_payload(b"keep")
        self.assertEqual((await self.sync(attachments_only, [item_payload(attachments=[file])])).status_code, 200)
        item = (await self.listing())["items"][0]
        await self.client.post(PREFIX + "/items/" + item["id"] + "/read", json={})
        created, full = await self.paired(include_body=True, include_attachments=True)
        enriched = item_payload(body_text="enrich", attachments=[file])
        with patch.object(self.bundle.service, "MAX_CONTENT_BYTES_PER_USER", 4):
            response = await self.sync(full, [enriched])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(await self.capture_flags(item["id"]), (False, True))
        async with self.factory() as db:
            device = await db.get(self.bundle.models.MailImportDevice, UUID(created["device"]["id"]))
            self.assertIsNone(device.mailbox_id)
            self.assertIsNone(device.last_sync_at)
        self.assertEqual((await self.sync(attachments_only, [item_payload(attachments=[file])])).status_code, 200)
        self.assertEqual((await self.sync(full, [enriched])).status_code, 200)
        detail = (await self.client.get(PREFIX + "/items/" + item["id"])).json()
        self.assertEqual(detail["attachments"], item["attachments"])
        self.assertTrue(detail["is_read"])
        self.assertEqual(detail["body_text"], "enrich")
        self.assertEqual(await self.capture_flags(item["id"]), (True, True))

    async def test_revoked_full_scope_history_blocks_metadata_writes_and_heartbeat(self):
        created, full = await self.paired(include_body=True, include_attachments=True)
        self.assertEqual((await self.sync(full, [item_payload(body_text="Keep", attachments=[attachment_payload()])])).status_code, 200)
        item = (await self.listing())["items"][0]
        self.assertEqual((await self.client.post(PREFIX + "/devices/" + created["device"]["id"] + "/revoke", json={})).status_code, 200)
        metadata_created, metadata = await self.paired()
        for items in ([], [item_payload(source_modified_at=(NOW + timedelta(seconds=1)).isoformat())]):
            response = await self.sync(metadata, items)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "mailbox_scope_mismatch")
        detail = (await self.client.get(PREFIX + "/items/" + item["id"])).json()
        self.assertEqual(detail["body_text"], "Keep")
        self.assertEqual(detail["attachments"], item["attachments"])
        async with self.factory() as db:
            device = await db.get(self.bundle.models.MailImportDevice, UUID(metadata_created["device"]["id"]))
            self.assertIsNone(device.mailbox_id)

    async def test_same_hash_scope_upgrade_persists_authoritative_empty_groups(self):
        _, metadata = await self.paired()
        self.assertEqual((await self.sync(metadata)).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        await self.client.post(PREFIX + "/items/" + item_id + "/read", json={})
        _, full = await self.paired(include_body=True, include_attachments=True)
        response = await self.sync(full)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unchanged"], 1)
        self.assertEqual(await self.capture_flags(item_id), (True, True))
        self.assertTrue((await self.client.get(PREFIX + "/items/" + item_id)).json()["is_read"])
        for changes in ({"body_text": "Late"}, {"attachments": [attachment_payload(b"late")]}):
            self.assertEqual((await self.sync(full, [item_payload(**changes)])).status_code, 409)

    async def test_scope_enrichment_commit_failure_rolls_back_capture_flags_and_binding(self):
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.ext.asyncio import AsyncSession
        _, metadata = await self.paired()
        self.assertEqual((await self.sync(metadata)).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        before = (await self.client.get(PREFIX + "/items/" + item_id)).json()
        created, full = await self.paired(include_body=True, include_attachments=True)
        with patch.object(AsyncSession, "commit", AsyncMock(side_effect=SQLAlchemyError("synthetic commit failure"))):
            response = await self.sync(full, [item_payload(body_text="Enriched", attachments=[attachment_payload()])])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(await self.capture_flags(item_id), (False, False))
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item_id)).json(), before)
        async with self.factory() as db:
            device = await db.get(self.bundle.models.MailImportDevice, UUID(created["device"]["id"]))
            self.assertIsNone(device.mailbox_id)
            self.assertIsNone(device.last_sync_at)
            item = await db.get(self.bundle.models.MailImportItem, UUID(item_id))
            self.assertEqual(item.content_byte_length, 0)
        self.assertEqual((await self.sync(metadata)).status_code, 200)

    async def test_stale_full_snapshot_does_not_capture_or_change_item(self):
        _, metadata = await self.paired()
        current = item_payload(source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
        self.assertEqual((await self.sync(metadata, [current])).status_code, 200)
        item_id = (await self.listing())["items"][0]["id"]
        before = (await self.client.get(PREFIX + "/items/" + item_id)).json()
        _, full = await self.paired(include_body=True, include_attachments=True)
        stale = item_payload(body_text="Stale", attachments=[attachment_payload()])
        response = await self.sync(full, [stale])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stale"], 1)
        self.assertEqual(await self.capture_flags(item_id), (False, False))
        self.assertEqual((await self.client.get(PREFIX + "/items/" + item_id)).json(), before)
        self.assertEqual((await self.sync(full, [{**current, "body_text": "Current", "attachments": [attachment_payload()]}])).status_code, 200)
        self.assertEqual(await self.capture_flags(item_id), (True, True))

    async def test_concurrent_scope_upgrade_and_metadata_retry_serialize_both_orders(self):
        for full_first, mailbox in ((True, "b" * 64), (False, "c" * 64)):
            with self.subTest(full_first=full_first):
                _, metadata = await self.paired()
                self.assertEqual((await self.sync(metadata, mailbox_id=mailbox)).status_code, 200)
                _, full = await self.paired(include_body=True, include_attachments=True)
                payload = item_payload(body_text="Full", attachments=[attachment_payload(b"full")])
                entered, release = asyncio.Event(), asyncio.Event()
                original = self.bundle.service.lock_import
                held = False

                async def paused_lock(db, owner_id, mailbox_id=None):
                    nonlocal held
                    await original(db, owner_id, mailbox_id)
                    if mailbox_id is not None and not held:
                        held = True
                        entered.set()
                        await release.wait()

                with patch.object(self.bundle.service, "lock_import", paused_lock):
                    first = asyncio.create_task(self.sync(full if full_first else metadata, [payload] if full_first else None, mailbox_id=mailbox))
                    second = None
                    try:
                        await asyncio.wait_for(entered.wait(), timeout=3)
                        second = asyncio.create_task(self.sync(metadata if full_first else full, None if full_first else [payload], mailbox_id=mailbox))
                        await asyncio.sleep(0.05)
                        self.assertFalse(second.done())
                        release.set()
                        responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=3)
                        self.assertEqual([response.status_code for response in responses], [200, 409 if full_first else 200])
                        if full_first:
                            self.assertEqual(responses[1].json()["detail"]["code"], "mailbox_scope_mismatch")
                    finally:
                        release.set()
                        await asyncio.gather(*[task for task in (first, second) if task is not None], return_exceptions=True)
                async with self.factory() as db:
                    from sqlalchemy import select
                    row = (await db.scalars(select(self.bundle.models.MailImportItem).where(
                        self.bundle.models.MailImportItem.owner_id == self.owner.id,
                        self.bundle.models.MailImportItem.mailbox_id == mailbox,
                    ))).one()
                    self.assertEqual(row.body_text, "Full")
                    self.assertTrue(row.body_captured)
                    self.assertTrue(row.attachments_captured)

    async def test_heartbeat_binds_mailbox_and_persists_incomplete_scan(self):
        created, paired = await self.paired()
        response = await self.sync(paired, [], scan_complete=False, skipped_items=5000, source_state="offline")
        self.assertEqual(response.status_code, 200)
        row = (await self.client.get(PREFIX + "/devices")).json()[0]
        self.assertFalse(row["last_scan_complete"])
        self.assertEqual(row["last_skipped_items"], 5000)
        self.assertEqual(row["source_state"], "offline")
        self.assertEqual(row["last_sync_at"], response.json()["synced_at"])
        self.assertEqual((await self.sync(paired, [], mailbox_id="c" * 64)).status_code, 409)
        self.assertEqual((await self.sync(paired, [])).status_code, 200)
        row = (await self.client.get(PREFIX + "/devices")).json()[0]
        self.assertTrue(row["last_scan_complete"])
        self.assertEqual(row["last_skipped_items"], 0)

    async def test_attachment_grants_manifests_and_download_owner_isolation(self):
        _, metadata = await self.paired(include_body=True)
        file = attachment_payload(b"<script>synthetic</script>", filename="\u043e\u0442\u0447\u0451\u0442.html", content_type="text/html", is_inline=True, content_id="synthetic-cid")
        self.assertEqual((await self.sync(metadata, [item_payload(attachments=[file])])).status_code, 403)
        _, paired = await self.paired(include_attachments=True)
        self.assertTrue(paired["include_attachments"])
        self.assertFalse(paired["include_body"])
        self.assertEqual((await self.sync(paired, [item_payload(body_html="<b>Ungrant</b>", attachments=[file])])).status_code, 403)
        response = await self.sync(paired, [item_payload(attachments=[file])])
        self.assertEqual(response.status_code, 200, response.text)
        item = (await self.listing())["items"][0]
        manifest = item["attachments"][0]
        self.assertEqual(manifest["size"], len(b"<script>synthetic</script>"))
        self.assertEqual(manifest["ordinal"], 0)
        self.assertNotIn("data_base64", manifest)
        self.assertNotIn("data", manifest)
        detail = (await self.client.get(PREFIX + "/items/" + item["id"])).json()
        self.assertEqual(detail["attachments"], item["attachments"])
        path = PREFIX + "/items/" + item["id"] + "/attachments/" + manifest["id"]
        download = await self.client.get(path)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"<script>synthetic</script>")
        self.assertEqual(download.headers["content-type"], "application/octet-stream")
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        self.assertEqual(download.headers["cache-control"], "no-store")
        self.assertIn("filename*=UTF-8''", download.headers["content-disposition"])
        wrong_parent = PREFIX + f"/items/{uuid4()}/attachments/" + manifest["id"]
        self.assertEqual((await self.client.get(wrong_parent)).status_code, 404)
        self.actor = self.other
        self.assertEqual((await self.client.get(path)).status_code, 404)

    async def test_attachment_replacement_duplicates_stale_and_removal(self):
        _, paired = await self.paired(include_attachments=True)
        initial = item_payload(attachments=[attachment_payload(b"old")])
        self.assertEqual((await self.sync(paired, [initial])).status_code, 200)
        item = (await self.listing())["items"][0]
        old_id = item["attachments"][0]["id"]
        old_path = PREFIX + "/items/" + item["id"] + "/attachments/" + old_id
        await self.client.post(PREFIX + "/items/" + item["id"] + "/read", json={})
        self.assertEqual((await self.sync(paired, [initial])).json()["unchanged"], 1)
        stale = item_payload(attachments=[attachment_payload(b"stale")], source_modified_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual((await self.sync(paired, [stale])).json()["stale"], 1)
        item = (await self.listing())["items"][0]
        self.assertTrue(item["is_read"])
        self.assertEqual(item["attachments"][0]["id"], old_id)
        equal = item_payload(attachments=[attachment_payload(b"new")])
        self.assertEqual((await self.sync(paired, [equal])).status_code, 409)
        newer = item_payload(attachments=[attachment_payload(b"new")], source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
        self.assertEqual((await self.sync(paired, [newer])).json()["updated"], 1)
        item = (await self.listing())["items"][0]
        self.assertFalse(item["is_read"])
        self.assertNotEqual(item["attachments"][0]["id"], old_id)
        self.assertEqual((await self.client.get(old_path)).status_code, 404)
        cleared = item_payload(source_modified_at=(NOW + timedelta(seconds=2)).isoformat())
        self.assertEqual((await self.sync(paired, [cleared])).json()["updated"], 1)
        self.assertEqual((await self.listing())["items"][0]["attachments"], [])

    async def test_attachment_write_failure_rolls_back_bytes_items_and_status(self):
        from sqlalchemy.exc import SQLAlchemyError
        from sqlalchemy.ext.asyncio import AsyncSession
        _, paired = await self.paired(include_attachments=True)
        self.assertEqual((await self.sync(paired, [item_payload(attachments=[attachment_payload(b"old")])])).status_code, 200)
        before = (await self.listing())["items"][0]
        status_before = (await self.client.get(PREFIX + "/devices")).json()[0]
        original_flush = AsyncSession.flush

        async def failing_flush(db, *args, **kwargs):
            inserted_files = any(isinstance(row, self.bundle.models.MailImportAttachment) for row in db.new)
            await original_flush(db, *args, **kwargs)
            if inserted_files:
                raise SQLAlchemyError("synthetic failure after writing bytes")

        with patch.object(AsyncSession, "flush", failing_flush):
            response = await self.sync(paired, [
                item_payload(attachments=[attachment_payload(b"new")], subject="New", source_modified_at=(NOW + timedelta(seconds=1)).isoformat()),
                item_payload(source_id="e" * 64, attachments=[attachment_payload(b"other")]),
            ], scan_complete=False, skipped_items=1)
        self.assertEqual(response.status_code, 503)
        listing = await self.listing()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0], before)
        self.assertEqual((await self.client.get(PREFIX + "/devices")).json()[0], status_before)
        path = PREFIX + "/items/" + before["id"] + "/attachments/" + before["attachments"][0]["id"]
        self.assertEqual((await self.client.get(path)).content, b"old")

    async def test_attachment_quota_serializes_mailboxes_and_counts_replacements(self):
        _, first = await self.paired(include_attachments=True)
        _, second = await self.paired(include_attachments=True)
        payload = item_payload(attachments=[attachment_payload(b"1234")])
        with patch.object(self.bundle.service, "MAX_CONTENT_BYTES_PER_USER", 5):
            responses = await asyncio.gather(self.sync(first, [payload]), self.sync(second, [payload], mailbox_id="d" * 64))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 413])
            winner = first if responses[0].status_code == 200 else second
            mailbox = "b" * 64 if responses[0].status_code == 200 else "d" * 64
            self.assertEqual((await self.sync(winner, [payload], mailbox_id=mailbox)).status_code, 200)
            too_large = item_payload(attachments=[attachment_payload(b"123456")], source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
            self.assertEqual((await self.sync(winner, [too_large], mailbox_id=mailbox)).status_code, 413)
            replacement = item_payload(attachments=[attachment_payload(b"12345")], source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
            self.assertEqual((await self.sync(winner, [replacement], mailbox_id=mailbox)).status_code, 200)
        self.assertEqual((await self.listing())["total"], 1)
        self.assertEqual((await self.listing())["items"][0]["attachments"][0]["size"], 5)

    async def test_combined_content_quota_utf8_boundary_and_replacement(self):
        _, paired = await self.paired(include_body=True, include_attachments=True)
        payload = item_payload(body_text="\u044f", body_html="h", to_recipients="to", cc_recipients="cc", attachments=[attachment_payload(b"x")])
        with patch.object(self.bundle.service, "MAX_CONTENT_BYTES_PER_USER", 8):
            response = await self.sync(paired, [payload])
            self.assertEqual(response.status_code, 200, response.text)
            listing = await self.listing()
            item_id = listing["items"][0]["id"]
            self.assertNotIn("content_byte_length", listing["items"][0])
            async with self.factory() as db:
                row = await db.get(self.bundle.models.MailImportItem, UUID(item_id))
                self.assertEqual(row.content_byte_length, 8)
            self.assertEqual((await self.sync(paired, [payload])).json()["unchanged"], 1)
            too_large = {**payload, "body_text": "\u044f\u044f", "source_modified_at": (NOW + timedelta(seconds=1)).isoformat()}
            response = await self.sync(paired, [too_large])
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json()["detail"]["code"], "content_storage_limit")
            smaller = {**payload, "body_text": "", "source_modified_at": (NOW + timedelta(seconds=1)).isoformat()}
            self.assertEqual((await self.sync(paired, [smaller])).status_code, 200)
            async with self.factory() as db:
                row = await db.get(self.bundle.models.MailImportItem, UUID(item_id))
                self.assertEqual(row.content_byte_length, 6)
            self.assertEqual((await self.sync(paired, [item_payload(source_id="c" * 64, body_text="\u044f")])).status_code, 200)
            self.assertEqual((await self.sync(paired, [item_payload(source_id="d" * 64, attachments=[attachment_payload(b"x")])])).status_code, 413)
            self.assertEqual((await self.listing())["total"], 2)

    async def test_text_only_content_quota_serializes_different_mailboxes(self):
        from sqlalchemy import func, select
        _, first = await self.paired(include_body=True)
        _, second = await self.paired(include_body=True)
        payload = item_payload(body_text="\u044f")
        with patch.object(self.bundle.service, "MAX_CONTENT_BYTES_PER_USER", 3):
            responses = await asyncio.gather(self.sync(first, [payload]), self.sync(second, [payload], mailbox_id="d" * 64))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 413])
        self.assertEqual((await self.listing())["total"], 1)
        async with self.factory() as db:
            stored = await db.scalar(select(func.sum(self.bundle.models.MailImportItem.content_byte_length)))
            self.assertEqual(stored, 2)

    async def test_batch_version_order_does_not_change_read_state_or_hide_conflict(self):
        _, paired = await self.paired()
        self.assertEqual((await self.sync(paired)).status_code, 200)
        row = (await self.listing())["items"][0]
        await self.client.post(PREFIX + "/items/" + row["id"] + "/read", json={})
        middle = item_payload(subject="Intermediate", source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
        newest = item_payload(source_modified_at=(NOW + timedelta(seconds=2)).isoformat())
        self.assertEqual((await self.sync(paired, [middle, newest])).status_code, 200)
        self.assertTrue((await self.listing())["items"][0]["is_read"])
        even_newer = item_payload(source_modified_at=(NOW + timedelta(seconds=3)).isoformat())
        divergent = item_payload(subject="Conflict", source_modified_at=(NOW + timedelta(seconds=2)).isoformat())
        self.assertEqual((await self.sync(paired, [even_newer, divergent])).status_code, 409)

    async def test_expired_pending_active_and_revoked_devices_are_rejected(self):
        expired = await self.create()
        await self.set_device(expired["device"]["id"], pairing_expires_at=NOW - timedelta(days=365))
        self.assertEqual((await self.client.post(PREFIX + "/pair", json={"pairing_code": expired["pairing_code"]})).status_code, 401)
        created, paired = await self.paired()
        self.assertEqual((await self.sync(paired)).status_code, 200)
        response = await self.client.post(PREFIX + "/devices/" + created["device"]["id"] + "/revoke", json={})
        self.assertEqual(response.json()["status"], "revoked")
        self.assertEqual((await self.sync(paired)).status_code, 401)
        self.assertEqual((await self.listing())["total"], 1)
        pending = await self.create()
        self.assertEqual((await self.client.post(PREFIX + "/devices/" + pending["device"]["id"] + "/revoke", json={})).status_code, 200)
        self.assertEqual((await self.client.post(PREFIX + "/pair", json={"pairing_code": pending["pairing_code"]})).status_code, 401)
        active, active_pair = await self.paired()
        await self.set_device(active["device"]["id"], expires_at=NOW - timedelta(days=365))
        self.assertEqual((await self.sync(active_pair, [])).status_code, 401)
        states = {row["id"]: row["status"] for row in (await self.client.get(PREFIX + "/devices")).json()}
        self.assertEqual(states[expired["device"]["id"]], "expired")
        self.assertEqual(states[active["device"]["id"]], "expired")

    async def test_password_version_and_inactive_owner_gate(self):
        pending = await self.create()
        _, paired = await self.paired()
        await self.set_owner(auth_version=1)
        self.assertEqual((await self.sync(paired)).status_code, 401)
        self.assertEqual((await self.client.post(PREFIX + "/pair", json={"pairing_code": pending["pairing_code"]})).status_code, 401)
        self.assertEqual((await self.client.get(PREFIX + "/devices")).status_code, 403)
        self.actor = SimpleNamespace(id=self.owner.id, auth_version=1)
        _, fresh = await self.paired()
        await self.set_owner(is_active=False)
        self.assertEqual((await self.sync(fresh)).status_code, 401)
        self.assertEqual((await self.client.get(PREFIX + "/items")).status_code, 403)

    async def test_competing_devices_do_not_duplicate_or_lose_newest_version(self):
        _, first = await self.paired()
        _, second = await self.paired()
        responses = await asyncio.gather(self.sync(first), self.sync(second))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(sum(r.json()["created"] for r in responses), 1)
        self.assertEqual((await self.listing())["total"], 1)
        newer = item_payload(subject="Newer", source_modified_at=(NOW + timedelta(seconds=2)).isoformat())
        middle = item_payload(subject="Middle", source_modified_at=(NOW + timedelta(seconds=1)).isoformat())
        responses = await asyncio.gather(self.sync(first, [newer]), self.sync(second, [middle]))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual((await self.listing())["items"][0]["subject"], "Newer")

    async def test_owner_quota_serializes_different_mailboxes(self):
        _, first = await self.paired()
        _, second = await self.paired()
        with patch.object(self.bundle.service, "MAX_ITEMS_PER_USER", 1):
            responses = await asyncio.gather(self.sync(first), self.sync(second, mailbox_id="d" * 64))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
            winner = first if responses[0].status_code == 200 else second
            mailbox = "b" * 64 if responses[0].status_code == 200 else "d" * 64
            self.assertEqual((await self.sync(winner, mailbox_id=mailbox)).status_code, 200)
        self.assertEqual((await self.listing())["total"], 1)

    async def test_revoke_waits_for_inflight_sync_then_rejects_future_batches(self):
        created, paired = await self.paired()
        locked, release = asyncio.Event(), asyncio.Event()
        original = self.bundle.service.lock_import

        async def paused_lock(db, owner_id, mailbox_id=None):
            await original(db, owner_id, mailbox_id)
            if mailbox_id is not None:
                locked.set()
                await release.wait()

        with patch.object(self.bundle.service, "lock_import", paused_lock):
            sync_task = asyncio.create_task(self.sync(paired))
            revoke_task = None
            try:
                await asyncio.wait_for(locked.wait(), timeout=3)
                revoke_task = asyncio.create_task(self.client.post(PREFIX + "/devices/" + created["device"]["id"] + "/revoke", json={}))
                await asyncio.sleep(0.1)
                self.assertFalse(revoke_task.done())
                release.set()
                self.assertEqual((await asyncio.wait_for(sync_task, timeout=3)).status_code, 200)
                self.assertEqual((await asyncio.wait_for(revoke_task, timeout=3)).status_code, 200)
            finally:
                release.set()
                await asyncio.gather(*[task for task in (sync_task, revoke_task) if task is not None], return_exceptions=True)
        self.assertEqual((await self.sync(paired)).status_code, 401)

    async def test_filter_pagination_order_and_unread_counts(self):
        _, paired = await self.paired()
        items = [
            item_payload(source_id="1" * 64), item_payload(source_id="2" * 64),
            item_payload(source_id="3" * 64, kind="meeting", meeting_status="cancelled", meeting_key="4" * 64),
        ]
        self.assertEqual((await self.sync(paired, items)).status_code, 200)
        listing = await self.listing()
        ids = [row["id"] for row in listing["items"]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual([row["id"] for row in (await self.listing(limit=1, offset=1))["items"]], ids[1:2])
        meeting = (await self.listing(kind="meeting"))["items"][0]
        await self.client.post(PREFIX + "/items/" + meeting["id"] + "/read", json={})
        self.assertEqual((await self.listing(kind="mail"))["total"], 2)
        self.assertEqual((await self.listing(kind="meeting"))["unread_count"], 0)
        self.assertEqual((await self.listing(unread_only=True))["total"], 2)

    async def test_invalid_item_rejects_entire_batch_and_no_other_tables_exist(self):
        from sqlalchemy import text
        _, paired = await self.paired()
        response = await self.sync(paired, [item_payload(), item_payload(source_id="c" * 64, starts_at=NOW.isoformat())])
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.listing())["total"], 0)
        async with self.engine.connect() as connection:
            tables = (await connection.scalars(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
            ), {"schema": self.schema_name})).all()
        self.assertEqual(set(tables), {"users", "mail_import_devices", "mail_import_items", "mail_import_attachments"})

    async def test_migration_downgrade_empty_only_and_model_columns_match(self):
        from sqlalchemy import delete, inspect
        from sqlalchemy.exc import DBAPIError
        async with self.engine.begin() as connection:
            for model in (self.bundle.models.MailImportDevice, self.bundle.models.MailImportItem, self.bundle.models.MailImportAttachment):
                columns = await connection.run_sync(lambda conn: inspect(conn).get_columns(model.__tablename__))
                self.assertEqual({col["name"] for col in columns}, set(model.__table__.columns.keys()))
            await connection.run_sync(lambda conn: self.run_migration(conn, "downgrade"))
            await connection.run_sync(lambda conn: self.run_migration(conn, "upgrade"))
        await self.create()
        with self.assertRaises(DBAPIError):
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda conn: self.run_migration(conn, "downgrade"))
        self.assertEqual(len((await self.client.get(PREFIX + "/devices")).json()), 1)
        _, paired = await self.paired(include_attachments=True)
        self.assertEqual((await self.sync(paired, [item_payload(attachments=[attachment_payload()])])).status_code, 200)
        async with self.factory.begin() as db:
            await db.execute(delete(self.bundle.models.MailImportDevice))
        with self.assertRaises(DBAPIError):
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda conn: self.run_migration(conn, "downgrade"))
        self.assertEqual((await self.listing())["total"], 1)


if __name__ == "__main__":
    unittest.main()
