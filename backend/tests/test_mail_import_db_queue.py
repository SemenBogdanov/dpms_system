"""Synthetic queue tests; PostgreSQL uses the existing explicit disposable guard.

Never import real settings, users, Alembic env or database configuration. Run:
python -B -m unittest discover -s backend/tests -p 'test_mail_import_db_queue.py' -v
PostgreSQL additionally needs OUTLOOK_TEST_POSTGRES=1 and OUTLOOK_TEST_DATABASE_URL.
"""
from contextlib import contextmanager
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from test_mail_import import BACKEND, attachment_payload, isolated_app, item_payload, load_source, sync_payload
from test_mail_import_http import disposable_url


@contextmanager
def queue_app():
    with isolated_app() as bundle:
        bundle.queue_models = load_source("app.models.mail_import_queue", BACKEND / "app/models/mail_import_queue.py")
        bundle.queue_service = load_source("app.services.mail_import_queue", BACKEND / "app/services/mail_import_queue.py")
        package = ModuleType("app.workers")
        package.__path__ = []
        sys.modules["app.workers"] = package
        bundle.worker = load_source("app.workers.mail_import_queue", BACKEND / "app/workers/mail_import_queue.py")
        bundle.migration = load_source("_outlook_queue_migration", BACKEND / "alembic/versions/101_mail_import_db_queue.py")
        yield bundle


class OfflineQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        context = queue_app()
        self.bundle = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def test_model_has_no_implicit_parent_locks_and_no_raw_device_material(self):
        table = self.bundle.queue_models.MailImportQueue.__table__
        self.assertEqual(list(table.foreign_keys), [])
        self.assertNotIn("device_secret", table.columns)
        self.assertNotIn("pairing_code", table.columns)
        self.assertTrue(table.c.result.type.none_as_null)
        self.assertEqual({column.name for column in table.primary_key}, {"device_id", "request_id"})

    def test_sql_security_and_pg12_native_hash_contract(self):
        statements = self.bundle.migration.function_statements('synthetic"schema')
        self.assertEqual(len(statements), 10)
        for create, revoke in zip(statements[::2], statements[1::2]):
            self.assertIn("SECURITY DEFINER SET search_path = pg_catalog, pg_temp", create)
            self.assertIn('"synthetic""schema".', create)
            self.assertIn("REVOKE ALL ON FUNCTION", revoke)
            self.assertTrue(revoke.endswith("FROM PUBLIC"))
            for forbidden in ("CREATE ROLE", "CREATE SCHEMA", "CREATE EXTENSION", "MERGE ", "digest("):
                self.assertNotIn(forbidden, create)
        pair, enqueue, status, protocol, connect = statements[::2]
        self.assertIn("dpms-mail-import:pair:", pair)
        self.assertIn("dpms-mail-import:device:", pair)
        self.assertIn("pg_catalog.sha256", pair)
        self.assertIn("''protocol_version'', 1", pair)
        self.assertIn("''maximum_batch_bytes'', 33554432", protocol)
        self.assertIn("''login_mode'', ''role_bound''", protocol)
        self.assertIn("dpms-mail-import:db-device:", connect)
        self.assertIn("SESSION_USER", connect)
        self.assertNotIn("owner_id uuid", connect.split("RETURNS", 1)[0])
        self.assertNotIn("FOR UPDATE", enqueue)
        self.assertNotIn("FOR SHARE", enqueue)
        self.assertNotIn("::json", enqueue)
        self.assertNotIn("$1, $2", enqueue.split("INSERT INTO", 1)[1])
        self.assertIn("transaction_isolation", enqueue)
        self.assertNotIn("device_secret'',", status)

    async def test_shared_service_entry_points_delegate_without_second_implementation(self):
        service = self.bundle.service
        db, device, owner, body = object(), object(), object(), object()
        result = object()
        with patch.object(service, "locked_device_by_digest", AsyncMock(return_value=(device, owner))) as lock:
            self.assertEqual(await service.locked_device(db, "s" * 43), (device, owner))
            lock.assert_awaited_once_with(db, service.digest("s" * 43, "device"), pairing=False)
        with patch.object(service, "locked_device", AsyncMock(return_value=(device, owner))):
            with patch.object(service, "sync_locked", AsyncMock(return_value=result)) as sync:
                self.assertIs(await service.sync_items(db, "s" * 43, body), result)
                sync.assert_awaited_once_with(db, device, owner, body)

    async def test_digest_entry_rejects_raw_material_before_database_access(self):
        from fastapi import HTTPException
        for value in ("s" * 43, "Z" * 64, "", "1" * 65):
            with self.assertRaises(HTTPException) as error:
                await self.bundle.service.locked_device_by_digest(None, value)
            self.assertEqual(error.exception.status_code, 401)

    def test_healthcheck_is_settings_free_and_fails_closed(self):
        worker = self.bundle.worker
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heartbeat"
            with patch.dict(os.environ, {"MAIL_IMPORT_QUEUE_HEARTBEAT": str(path)}, clear=True):
                self.assertEqual(worker.main(["--healthcheck"]), 1)
                path.touch()
                stamp = path.stat().st_mtime
                self.assertTrue(worker.healthy(now=stamp + 1))
                self.assertFalse(worker.healthy(now=stamp + 121))
                self.assertFalse(worker.healthy(now=stamp - 1))
                path.unlink()
                path.symlink_to(Path(directory))
                self.assertFalse(worker.healthy())
                for interval in ("nan", "inf", "0", "bad", "61"):
                    with patch.dict(os.environ, {"MAIL_IMPORT_QUEUE_POLL_SECONDS": interval}):
                        self.assertFalse(worker.healthy())
        self.assertNotIn("app.config", sys.modules)
        self.assertNotIn("app.database", sys.modules)

    async def test_worker_does_not_refresh_heartbeat_on_failed_commit_or_echo_diagnostics(self):
        worker = self.bundle.worker
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heartbeat"
            path.touch()
            with patch.dict(os.environ, {"MAIL_IMPORT_QUEUE_HEARTBEAT": str(path)}, clear=True):
                with patch.object(worker, "run_once", AsyncMock(side_effect=RuntimeError("private-input-marker"))):
                    with self.assertLogs("mail_import_queue", level="ERROR") as logs:
                        self.assertEqual(await worker.run(None, once=True), 1)
                self.assertFalse(path.exists())
                self.assertNotIn("private-input-marker", "".join(logs.output))
                with patch.object(worker, "run_once", AsyncMock(return_value=False)):
                    self.assertEqual(await worker.run(None, once=True), 0)
                self.assertTrue(worker.healthy())


@unittest.skipUnless(os.getenv("OUTLOOK_TEST_POSTGRES") == "1", "disposable PostgreSQL opt-in required")
class PostgresQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.schema import CreateSchema
        context = queue_app()
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
        previous = load_source("_outlook_queue_previous", BACKEND / "alembic/versions/100_mail_import.py")
        async with self.engine.begin() as connection:
            await connection.run_sync(self.bundle.User.__table__.create)
            await connection.run_sync(lambda conn: self.run_migration(conn, previous, "upgrade"))
            await connection.run_sync(lambda conn: self.run_migration(conn, self.bundle.migration, "upgrade"))
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.owner = SimpleNamespace(id=uuid4(), auth_version=0)
        self.other = SimpleNamespace(id=uuid4(), auth_version=0)
        async with self.factory.begin() as db:
            db.add_all([self.bundle.User(id=owner.id, full_name="Synthetic owner", is_active=True, auth_version=0)
                        for owner in (self.owner, self.other)])

    async def drop_schema(self):
        from sqlalchemy.schema import DropSchema
        async with self.engine.begin() as connection:
            await connection.execute(DropSchema(self.schema_name, cascade=True))

    @staticmethod
    def run_migration(connection, migration, direction):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()

    def statement(self, name, args):
        from sqlalchemy import text
        self.assertIn(name, self.bundle.migration.SIGNATURES)
        types = self.bundle.migration.SIGNATURES[name].split(", ") if args else []
        self.assertEqual(len(types), len(args))
        params = {f"p{i}": arg for i, arg in enumerate(args)}
        arguments = ", ".join(f"CAST(:p{i} AS {kind})" for i, kind in enumerate(types))
        function = self.bundle.migration.qualified(self.schema_name, name)
        return text(f"SELECT {function}({arguments})"), params

    async def sql(self, name, *args):
        statement, params = self.statement(name, args)
        async with self.factory.begin() as db:
            return await db.scalar(statement, params)

    async def create(self, owner=None, **grants):
        async with self.factory.begin() as db:
            return await self.bundle.service.create_device(db, owner or self.owner,
                self.bundle.schema.DeviceCreate(name="Synthetic direct DB", **grants))

    async def paired(self, owner=None, **grants):
        created = await self.create(owner, **grants)
        result = await self.sql("mail_import_db_pair", created.pairing_code, secrets.token_urlsafe(32))
        self.bundle.schema.PairRead.model_validate(result)
        return result

    async def enqueue(self, pair, payload=None, request_id=None):
        if payload is None:
            payload = sync_payload()
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=True)
        return await self.sql("mail_import_db_enqueue", pair["device_secret"], request_id or uuid4(), payload)

    async def status(self, pair, request_id):
        return await self.sql("mail_import_db_status", pair["device_secret"], UUID(str(request_id)))

    async def process(self):
        return await self.bundle.worker.run_once(self.factory)

    async def rows(self, model):
        from sqlalchemy import select
        async with self.factory() as db:
            return list((await db.scalars(select(model))).all())

    async def update_device(self, pair, **changes):
        from sqlalchemy import update
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.models.MailImportDevice).where(
                self.bundle.models.MailImportDevice.id == UUID(pair["device_id"])).values(**changes))

    async def provision(self, owner=None, *, include_body=False, include_attachments=False, enabled=True):
        """Explicit DBA fixture in this test's schema; never create/change PG roles."""
        from sqlalchemy import text
        async with self.factory.begin() as db:
            role = (await db.execute(text("SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname = SESSION_USER"))).one()
            await db.merge(self.bundle.queue_models.MailImportDBLogin(
                role_oid=role.oid, role_name=role.rolname, owner_id=(owner or self.owner).id,
                include_body=include_body, include_attachments=include_attachments, enabled=enabled,
            ))
        return role

    async def connected(self, owner=None, *, raw=None, name="Synthetic direct DB", **grants):
        await self.provision(owner, **grants)
        result = await self.sql("mail_import_db_connect", name, raw or secrets.token_urlsafe(32))
        self.bundle.schema.PairRead.model_validate(result)
        return result

    async def test_protocol_and_pair_one_use_concurrent_hash_at_rest(self):
        self.assertEqual(await self.sql("mail_import_db_protocol"), {"protocol_version": 1, "maximum_batch_bytes": 33554432, "login_mode": "role_bound"})
        created = await self.create(include_body=True, include_attachments=True)
        raw = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        results = await asyncio.gather(*(self.sql("mail_import_db_pair", created.pairing_code, value) for value in raw))
        success = [result for result in results if "device_id" in result]
        self.assertEqual(len(success), 1)
        self.assertEqual(success[0]["protocol_version"], 1)
        self.assertTrue(success[0]["include_body"])
        self.assertTrue(success[0]["include_attachments"])
        self.assertEqual([r["error_status"] for r in results if "error_status" in r], [401])
        device = (await self.rows(self.bundle.models.MailImportDevice))[0]
        self.assertEqual(device.device_secret_hash, self.bundle.service.digest(success[0]["device_secret"], "device"))
        self.assertIsNone(device.pairing_code_hash)
        self.assertEqual((await self.sql("mail_import_db_pair", created.pairing_code, raw[0]))["error_status"], 401)

    async def test_pair_rejects_bad_format_expiry_owner_version_and_inactive(self):
        from sqlalchemy import update
        created = await self.create()
        for code, raw, status in (("bad", "s" * 43, 401), (created.pairing_code, "bad", 422),
                                  (created.pairing_code, created.pairing_code, 422)):
            result = await self.sql("mail_import_db_pair", code, raw)
            self.assertEqual(result["error_status"], status)
            self.assertNotIn(code, json.dumps(result))
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(auth_version=1))
        self.assertEqual((await self.sql("mail_import_db_pair", created.pairing_code, "s" * 43))["error_status"], 401)
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(auth_version=0, is_active=False))
        self.assertEqual((await self.sql("mail_import_db_pair", created.pairing_code, "s" * 43))["error_status"], 401)
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(is_active=True))
            await db.execute(update(self.bundle.models.MailImportDevice).values(pairing_expires_at=self.bundle.models.utc_now() - timedelta(seconds=1)))
        self.assertEqual((await self.sql("mail_import_db_pair", created.pairing_code, "s" * 43))["error_status"], 401)

    async def test_receipt_atomic_visibility_and_full_import_reuses_domain(self):
        pair = await self.paired(include_body=True, include_attachments=True)
        payload = sync_payload([item_payload(body_text="Synthetic body", body_html="<b>inert</b>",
                                            attachments=[attachment_payload()])], scan_complete=False, skipped_items=2)
        receipt = await self.enqueue(pair, payload)
        self.assertEqual(receipt["state"], "pending")
        async with self.factory() as db:
            async with db.begin():
                self.assertTrue(await self.bundle.queue_service.process_next(db))
                self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "pending")
                self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])
        final = await self.status(pair, receipt["request_id"])
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["result"]["created"], 1)
        self.bundle.schema.SyncRead.model_validate(final["result"])
        self.assertIsNone((await self.rows(self.bundle.queue_models.MailImportQueue))[0].payload)
        self.assertEqual((await self.rows(self.bundle.models.MailImportAttachment))[0].data, b"Synthetic file")
        device = (await self.rows(self.bundle.models.MailImportDevice))[0]
        self.assertFalse(device.last_scan_complete)
        self.assertEqual(device.last_skipped_items, 2)
        repeated = await self.enqueue(pair, payload, UUID(receipt["request_id"]))
        self.assertEqual(repeated["state"], "done")
        duplicate = await self.enqueue(pair, payload)
        await self.process()
        self.assertEqual((await self.status(pair, duplicate["request_id"]))["result"]["unchanged"], 1)
        self.assertEqual(len(await self.rows(self.bundle.models.MailImportAttachment)), 1)

    async def test_uuid_replay_conflict_pending_limit_and_concurrent_admission(self):
        pair = await self.paired()
        request_id = uuid4()
        results = await asyncio.gather(*(self.enqueue(pair, request_id=request_id) for _ in range(3)))
        self.assertTrue(all(result["state"] == "pending" for result in results))
        self.assertEqual(len(await self.rows(self.bundle.queue_models.MailImportQueue)), 1)
        conflict = await self.enqueue(pair, sync_payload(subject="synthetic-private-marker"), request_id)
        self.assertEqual(conflict, {"error_code": "request_conflict", "error_status": 409})
        self.assertEqual((await self.enqueue(pair))["error_status"], 429)
        await self.process()
        results = await asyncio.gather(*(self.enqueue(pair) for _ in range(3)))
        self.assertEqual(sum(result.get("state") == "pending" for result in results), 1)
        self.assertEqual(sum(result.get("error_status") == 429 for result in results), 2)

    async def test_owner_count_and_global_byte_admission_limits(self):
        pairs = [await self.paired() for _ in range(5)]
        results = await asyncio.gather(*(self.enqueue(pair, sync_payload([])) for pair in pairs))
        self.assertEqual(sum(result.get("state") == "pending" for result in results), 4)
        self.assertEqual(sum(result.get("error_status") == 429 for result in results), 1)
        from sqlalchemy import delete
        queue = self.bundle.queue_models.MailImportQueue
        async with self.factory.begin() as db:
            await db.execute(delete(queue))
            # Privileged synthetic fixtures exercise accounting without allocating 1GiB.
            stamp = self.bundle.models.utc_now()
            for _ in range(32):
                db.add(queue(device_id=uuid4(), request_id=uuid4(), owner_id=uuid4(), device_digest="a" * 64,
                    payload="synthetic", payload_hash="b" * 64, payload_bytes=33554432, state="pending",
                    created_at=stamp, expires_at=stamp + timedelta(days=1)))
        self.assertEqual((await self.enqueue(pairs[0], sync_payload([])))["error_status"], 429)

    async def test_size_bound_before_parse_and_malformed_payload_sanitized(self):
        pair = await self.paired()
        self.assertEqual((await self.enqueue(pair, "x" * 33554433))["error_status"], 413)
        self.assertEqual((await self.enqueue(pair, "\u0430" * 16777217))["error_status"], 413)
        self.assertEqual(await self.rows(self.bundle.queue_models.MailImportQueue), [])
        receipt = await self.enqueue(pair, "synthetic-private-marker {")
        await self.process()
        final = await self.status(pair, receipt["request_id"])
        self.assertEqual(final["error_status"], 422)
        self.assertEqual(final["error_code"], "invalid_payload")
        self.assertNotIn("synthetic-private-marker", json.dumps(final))
        self.assertIsNone((await self.rows(self.bundle.queue_models.MailImportQueue))[0].payload)

    async def test_owner_device_isolation_and_current_access_gates(self):
        from sqlalchemy import update
        pair = await self.paired()
        other = await self.paired(self.other)
        same_owner = await self.paired()
        receipt = await self.enqueue(pair)
        for foreign in (other, same_owner):
            self.assertEqual((await self.status(foreign, receipt["request_id"]))["error_status"], 404)
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(auth_version=1))
        self.assertEqual((await self.status(pair, receipt["request_id"]))["error_status"], 401)
        self.assertEqual((await self.enqueue(pair))["error_status"], 401)
        await self.process()
        row = (await self.rows(self.bundle.queue_models.MailImportQueue))[0]
        self.assertEqual((row.state, row.error_code), ("error", "invalid_device"))
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])

    async def test_revoke_expiry_and_deleted_owner_before_processing_reject(self):
        from sqlalchemy import delete
        for mode in ("revoke", "expire", "inactive", "delete"):
            with self.subTest(mode=mode):
                pair = await self.paired(self.other if mode == "delete" else self.owner)
                receipt = await self.enqueue(pair)
                if mode == "revoke":
                    async with self.factory.begin() as db:
                        await self.bundle.service.revoke_device(db, self.owner, UUID(pair["device_id"]))
                elif mode == "expire":
                    await self.update_device(pair, expires_at=self.bundle.models.utc_now() - timedelta(seconds=1))
                elif mode == "inactive":
                    from sqlalchemy import update
                    async with self.factory.begin() as db:
                        await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(is_active=False))
                else:
                    async with self.factory.begin() as db:
                        await db.execute(delete(self.bundle.User).where(self.bundle.User.id == self.other.id))
                self.assertEqual((await self.status(pair, receipt["request_id"]))["error_status"], 401)
                await self.process()
                rows = await self.rows(self.bundle.queue_models.MailImportQueue)
                row = next(row for row in rows if str(row.request_id) == receipt["request_id"])
                self.assertEqual(row.error_code, "invalid_device")
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])

    async def test_grants_and_domain_conflicts_are_terminal_atomic_errors(self):
        pair = await self.paired()
        for changes, code in (({"body_text": "synthetic"}, "body_not_granted"),
                              ({"attachments": [attachment_payload()]}, "attachments_not_granted")):
            receipt = await self.enqueue(pair, sync_payload([item_payload(**changes)]))
            await self.process()
            self.assertEqual((await self.status(pair, receipt["request_id"]))["error_code"], code)
        receipt = await self.enqueue(pair)
        await self.process()
        conflict = await self.enqueue(pair, sync_payload([item_payload(subject="different"), item_payload(source_id="c" * 64)]))
        await self.process()
        self.assertEqual((await self.status(pair, conflict["request_id"]))["error_code"], "item_version_conflict")
        self.assertEqual(len(await self.rows(self.bundle.models.MailImportItem)), 1)

    async def test_savepoint_rolls_back_completed_domain_mutations_and_sanitizes_unknown_errors(self):
        pair = await self.paired(include_body=True, include_attachments=True)
        receipt = await self.enqueue(pair, sync_payload([item_payload(body_html="inert", attachments=[attachment_payload()])]))
        original = self.bundle.service.sync_locked

        async def fail_after_import(*args):
            await original(*args)
            raise self.bundle.service.error(409, "synthetic-private-marker")

        with patch.object(self.bundle.service, "sync_locked", fail_after_import):
            await self.process()
        final = await self.status(pair, receipt["request_id"])
        self.assertEqual(final["error_code"], "request_rejected")
        self.assertNotIn("synthetic-private-marker", json.dumps(final))
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])
        self.assertEqual(await self.rows(self.bundle.models.MailImportAttachment), [])
        device = (await self.rows(self.bundle.models.MailImportDevice))[0]
        self.assertIsNone(device.mailbox_id)
        self.assertIsNone(device.last_sync_at)

    async def test_crash_and_failed_outer_commit_leave_pending_for_retry(self):
        pair = await self.paired()
        receipt = await self.enqueue(pair)
        original = self.bundle.service.sync_locked

        async def crash_after_import(*args):
            await original(*args)
            raise RuntimeError("synthetic crash")

        with patch.object(self.bundle.service, "sync_locked", crash_after_import):
            with self.assertRaises(RuntimeError):
                await self.process()
        self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "pending")
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])
        with self.assertRaises(RuntimeError):
            async with self.factory() as db, db.begin():
                self.assertTrue(await self.bundle.queue_service.process_next(db))
                raise RuntimeError("synthetic precommit failure")
        self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "pending")
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])
        await self.process()
        self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "done")

    async def test_concurrent_consumers_and_admission_have_no_inverse_lock_order(self):
        pair = await self.paired()
        receipt = await self.enqueue(pair)
        async with self.factory() as db, db.begin():
            self.assertTrue(await self.bundle.queue_service.process_next(db))
            self.assertFalse(await asyncio.wait_for(self.process(), timeout=3))
            self.assertEqual((await asyncio.wait_for(self.enqueue(pair), timeout=3))["error_status"], 429)
            self.assertEqual((await asyncio.wait_for(self.enqueue(pair, request_id=UUID(receipt["request_id"])), timeout=3))["state"], "pending")
        self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "done")

    async def test_import_quota_and_monotonic_mailbox_scope_remain_shared(self):
        full = await self.paired(include_body=True, include_attachments=True)
        receipt = await self.enqueue(full, sync_payload([item_payload(body_text="synthetic")]))
        with patch.object(self.bundle.service, "MAX_CONTENT_BYTES_PER_USER", 1):
            await self.process()
        self.assertEqual((await self.status(full, receipt["request_id"]))["error_code"], "content_storage_limit")
        receipt = await self.enqueue(full, sync_payload([item_payload(body_text="synthetic")]))
        await self.process()
        meta = await self.paired()
        receipt = await self.enqueue(meta, sync_payload([item_payload(source_modified_at="2026-11-18T12:00:00Z")]))
        await self.process()
        self.assertEqual((await self.status(meta, receipt["request_id"]))["error_code"], "mailbox_scope_mismatch")
        self.assertEqual((await self.rows(self.bundle.models.MailImportItem))[0].body_text, "synthetic")

    async def test_ttl_and_retention_cleanup_are_bounded(self):
        from sqlalchemy import update
        pair = await self.paired()
        receipt = await self.enqueue(pair)
        queue = self.bundle.queue_models.MailImportQueue
        now = self.bundle.models.utc_now()
        async with self.factory.begin() as db:
            await db.execute(update(queue).values(expires_at=now - timedelta(seconds=1)))
        self.assertEqual((await self.status(pair, receipt["request_id"]))["error_code"], "request_expired")
        await self.process()
        self.assertIsNone((await self.rows(queue))[0].payload)
        async with self.factory.begin() as db:
            await db.execute(update(queue).values(finished_at=now - timedelta(days=8)))
            for _ in range(101):
                db.add(queue(device_id=uuid4(), request_id=uuid4(), owner_id=self.owner.id, device_digest="a" * 64,
                    payload=None, payload_hash="b" * 64, payload_bytes=1, state="error", error_code="invalid_payload",
                    error_status=422, created_at=now - timedelta(days=9), expires_at=now - timedelta(days=8),
                    finished_at=now - timedelta(days=8)))
        async with self.factory.begin() as db:
            self.assertEqual(await self.bundle.queue_service.cleanup(db, limit=10000), 100)
        self.assertEqual(len(await self.rows(queue)), 2)

    async def test_security_catalog_search_path_and_nondefault_schema(self):
        from sqlalchemy import text
        async with self.factory.begin() as db:
            rows = (await db.execute(text("""
                SELECT p.proname, p.prosecdef, p.proconfig,
                    EXISTS (SELECT 1 FROM pg_catalog.aclexplode(COALESCE(p.proacl,
                        pg_catalog.acldefault('f', p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
                FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname=:schema
            """), {"schema": self.schema_name})).all()
            self.assertEqual(len(rows), 5)
            for row in rows:
                self.assertTrue(row.prosecdef)
                self.assertEqual(row.proconfig, ["search_path=pg_catalog, pg_temp"])
                self.assertFalse(row.public_execute)
            self.assertFalse(await db.scalar(text("""
                SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace,
                    LATERAL pg_catalog.aclexplode(COALESCE(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
                    WHERE n.nspname=:schema AND c.relname='mail_import_queue' AND a.grantee=0)
            """), {"schema": self.schema_name}))
        created = await self.create()
        statement, params = self.statement("mail_import_db_pair", (created.pairing_code, "s" * 43))
        async with self.factory.begin() as db:
            await db.execute(text("CREATE TEMP TABLE users (id integer)"))
            await db.execute(text("CREATE TEMP TABLE mail_import_devices (id integer)"))
            await db.execute(text("SET LOCAL search_path = pg_temp"))
            result = await db.scalar(statement, params)
            self.assertEqual(result["device_id"], str(created.device.id))

    async def test_repeatable_read_admission_is_rejected_not_silently_racy(self):
        from sqlalchemy import text
        pair = await self.paired()
        statement, params = self.statement("mail_import_db_enqueue", (pair["device_secret"], uuid4(), json.dumps(sync_payload())))
        async with self.factory.begin() as db:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            self.assertEqual(await db.scalar(statement, params), {"error_code": "unsupported_transaction", "error_status": 400})

    async def test_downgrade_preserves_receipts_and_empty_round_trip(self):
        from sqlalchemy import delete, text
        pair = await self.paired()
        await self.enqueue(pair)
        with self.assertRaisesRegex(RuntimeError, "downgrade blocked"):
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda conn: self.run_migration(conn, self.bundle.migration, "downgrade"))
        self.assertEqual(len(await self.rows(self.bundle.queue_models.MailImportQueue)), 1)
        async with self.factory.begin() as db:
            await db.execute(delete(self.bundle.queue_models.MailImportQueue))
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda conn: self.run_migration(conn, self.bundle.migration, "downgrade"))
            self.assertIsNone(await connection.scalar(text("SELECT pg_catalog.to_regclass('mail_import_queue')")))
            await connection.run_sync(lambda conn: self.run_migration(conn, self.bundle.migration, "upgrade"))
        self.assertEqual((await self.sql("mail_import_db_protocol"))["protocol_version"], 1)

    async def test_connect_needs_explicit_mapping_even_for_database_owner_and_validates_input(self):
        raw = secrets.token_urlsafe(32)
        self.assertEqual(await self.sql("mail_import_db_connect", "Laptop", raw), {
            "error_code": "db_login_not_provisioned", "error_status": 403,
        })
        self.assertEqual(await self.rows(self.bundle.models.MailImportDevice), [])
        await self.provision()
        for name, value in (("", raw), ("\t \n", raw), ("x" * 121, raw), ("Laptop", "bad")):
            result = await self.sql("mail_import_db_connect", name, value)
            self.assertEqual(result, {"error_code": "invalid_connect_request", "error_status": 422})
        result = await self.sql("mail_import_db_connect", " Laptop ", raw)
        self.assertEqual(result["protocol_version"], 1)
        self.assertEqual(result["device_secret"], raw)
        self.assertFalse(result["include_body"])
        self.assertFalse(result["include_attachments"])
        device = (await self.rows(self.bundle.models.MailImportDevice))[0]
        self.assertEqual(device.owner_id, self.owner.id)
        self.assertEqual(device.name, "Laptop")
        self.assertEqual(device.device_secret_hash, self.bundle.service.digest(raw, "db-device"))
        self.assertIsNone(device.pairing_code_hash)

    async def test_connect_retries_concurrently_return_same_device_and_preserve_bindings(self):
        await self.provision(include_body=True, include_attachments=True)
        raw = secrets.token_urlsafe(32)
        results = await asyncio.gather(*(self.sql("mail_import_db_connect", "Laptop", raw) for _ in range(3)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertTrue(results[0]["include_body"])
        self.assertTrue(results[0]["include_attachments"])
        self.assertEqual(len(await self.rows(self.bundle.models.MailImportDevice)), 1)
        self.assertEqual(len(await self.rows(self.bundle.queue_models.MailImportDBDevice)), 1)
        receipt = await self.enqueue(results[0], sync_payload([item_payload(body_html="<b>inert</b>", attachments=[attachment_payload()])]))
        queue = (await self.rows(self.bundle.queue_models.MailImportQueue))[0]
        binding = (await self.rows(self.bundle.queue_models.MailImportDBDevice))[0]
        self.assertEqual((queue.login_role_oid, queue.login_role_name), (binding.role_oid, binding.role_name))
        self.assertEqual(queue.device_digest, self.bundle.service.digest(raw, "db-device"))
        await self.process()
        self.assertEqual((await self.status(results[0], receipt["request_id"]))["state"], "done")

    async def test_connect_conflicts_on_identity_grant_version_and_revocation_changes(self):
        from sqlalchemy import update
        pair = await self.connected(include_body=True)
        raw = pair["device_secret"]
        self.assertEqual((await self.sql("mail_import_db_connect", "Different laptop", raw))["error_status"], 409)
        await self.provision(self.other, include_body=True)
        self.assertEqual((await self.sql("mail_import_db_connect", "Synthetic direct DB", raw))["error_status"], 409)
        await self.provision()
        self.assertEqual((await self.sql("mail_import_db_connect", "Synthetic direct DB", raw))["error_status"], 409)
        await self.provision(include_body=True, enabled=False)
        self.assertEqual((await self.sql("mail_import_db_connect", "Synthetic direct DB", raw))["error_code"], "db_login_not_provisioned")
        await self.provision(include_body=True)
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(auth_version=1))
        self.assertEqual((await self.sql("mail_import_db_connect", "Synthetic direct DB", raw))["error_status"], 409)
        async with self.factory.begin() as db:
            await db.execute(update(self.bundle.User).where(self.bundle.User.id == self.owner.id).values(auth_version=0))
            await self.bundle.service.revoke_device(db, self.owner, UUID(pair["device_id"]))
        self.assertEqual((await self.sql("mail_import_db_connect", "Synthetic direct DB", raw))["error_status"], 409)
        self.assertEqual(len(await self.rows(self.bundle.models.MailImportDevice)), 1)

    async def test_connect_uses_shared_owner_quota_lock_and_idempotence_at_capacity(self):
        pair = await self.connected()
        blocked = None
        try:
            async with self.factory.begin() as db:
                await self.bundle.service.lock_import(db, self.owner.id)
                blocked = asyncio.create_task(self.sql("mail_import_db_connect", "Other laptop", secrets.token_urlsafe(32)))
                await asyncio.sleep(0.05)
                self.assertFalse(blocked.done())
            result = await asyncio.wait_for(blocked, timeout=3)
            self.assertIn("device_id", result)
        finally:
            if blocked and not blocked.done():
                blocked.cancel()
                await asyncio.gather(blocked, return_exceptions=True)
        for _ in range(98):
            await self.create()
        self.assertEqual(await self.sql("mail_import_db_connect", "Laptop 101", secrets.token_urlsafe(32)), {
            "error_code": "device_count_limit", "error_status": 409,
        })
        self.assertEqual(await self.sql("mail_import_db_connect", "Synthetic direct DB", pair["device_secret"]), pair)
        self.assertEqual(len(await self.rows(self.bundle.models.MailImportDevice)), 100)

    async def test_role_bound_secret_cannot_use_https_sync_or_legacy_pair_hash(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        pair = await self.connected()
        app = FastAPI()
        app.include_router(self.bundle.routes.router, prefix="/api/mail-import")

        async def database():
            async with self.factory() as db:
                yield db

        app.dependency_overrides[self.bundle.deps.get_db] = database
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test.invalid") as client:
            response = await client.post("/api/mail-import/sync", json=sync_payload(), headers={
                "Authorization": "Bearer " + pair["device_secret"],
            })
        self.assertEqual(response.status_code, 401)
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])
        receipt = await self.enqueue(pair)
        self.assertEqual(receipt["state"], "pending")
        await self.process()
        self.assertEqual((await self.status(pair, receipt["request_id"]))["state"], "done")
        legacy = await self.paired()
        self.assertEqual((await self.enqueue(legacy))["error_status"], 401)

    async def test_mapping_changes_reject_status_admission_and_queued_work_without_legacy_fallback(self):
        from sqlalchemy import delete, update
        login = self.bundle.queue_models.MailImportDBLogin
        binding = self.bundle.queue_models.MailImportDBDevice
        for change in ("disabled", "owner", "body", "attachments", "name", "oid", "deleted", "binding_deleted"):
            with self.subTest(change=change):
                pair = await self.connected(include_body=True, include_attachments=True)
                receipt = await self.enqueue(pair)
                async with self.factory.begin() as db:
                    if change == "deleted":
                        await db.execute(delete(login))
                    elif change == "binding_deleted":
                        await db.execute(delete(binding).where(binding.device_id == UUID(pair["device_id"])))
                    else:
                        changes = {
                            "disabled": {"enabled": False}, "owner": {"owner_id": self.other.id},
                            "body": {"include_body": False}, "attachments": {"include_attachments": False},
                            "name": {"role_name": "synthetic_missing_role"}, "oid": {"role_oid": 0},
                        }
                        await db.execute(update(login).values(**changes[change]))
                self.assertEqual((await self.status(pair, receipt["request_id"]))["error_status"], 401)
                self.assertEqual((await self.enqueue(pair))["error_status"], 401)
                await self.process()
                rows = await self.rows(self.bundle.queue_models.MailImportQueue)
                row = next(row for row in rows if str(row.request_id) == receipt["request_id"])
                self.assertEqual((row.state, row.error_code, row.payload), ("error", "invalid_device", None))
                async with self.factory.begin() as db:
                    await db.execute(delete(login))
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])

    async def test_worker_requires_current_role_login_capability_not_just_mapping(self):
        from sqlalchemy import delete, text, update
        pair = await self.connected()
        receipt = await self.enqueue(pair)
        async with self.factory.begin() as db:
            # A pre-existing NOLOGIN system role is only referenced, never modified.
            role = (await db.execute(text("SELECT oid, rolname FROM pg_catalog.pg_roles WHERE NOT rolcanlogin ORDER BY oid LIMIT 1"))).one()
            await db.execute(delete(self.bundle.queue_models.MailImportDBLogin))
            db.add(self.bundle.queue_models.MailImportDBLogin(role_oid=role.oid, role_name=role.rolname, owner_id=self.owner.id))
            await db.execute(update(self.bundle.queue_models.MailImportDBDevice).values(role_oid=role.oid, role_name=role.rolname))
            await db.execute(update(self.bundle.queue_models.MailImportQueue).values(login_role_oid=role.oid, login_role_name=role.rolname))
        await self.process()
        self.assertEqual((await self.rows(self.bundle.queue_models.MailImportQueue))[0].error_code, "invalid_device")
        self.assertEqual(await self.rows(self.bundle.models.MailImportItem), [])

    async def test_mapping_disable_serializes_with_inflight_import_through_commit(self):
        from sqlalchemy import update
        pair = await self.connected()
        await self.enqueue(pair)

        async def disable():
            async with self.factory.begin() as db:
                await db.execute(update(self.bundle.queue_models.MailImportDBLogin).values(enabled=False))

        pending = None
        try:
            async with self.factory.begin() as db:
                self.assertTrue(await self.bundle.queue_service.process_next(db))
                pending = asyncio.create_task(disable())
                await asyncio.sleep(0.05)
                self.assertFalse(pending.done())
            await asyncio.wait_for(pending, timeout=3)
        finally:
            if pending and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        self.assertEqual((await self.rows(self.bundle.queue_models.MailImportQueue))[0].state, "done")
        self.assertEqual((await self.enqueue(pair))["error_status"], 401)

    async def test_login_mapping_blocks_downgrade_and_all_private_table_acls_deny_public(self):
        from sqlalchemy import text
        await self.provision()
        with self.assertRaisesRegex(RuntimeError, "downgrade blocked"):
            async with self.engine.begin() as connection:
                await connection.run_sync(lambda conn: self.run_migration(conn, self.bundle.migration, "downgrade"))
        async with self.factory() as db:
            self.assertEqual(await db.scalar(text("""
                SELECT count(*) FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace,
                LATERAL pg_catalog.aclexplode(COALESCE(c.relacl, pg_catalog.acldefault('r', c.relowner))) a
                WHERE n.nspname=:schema AND c.relname IN ('mail_import_queue', 'mail_import_db_logins', 'mail_import_db_devices')
                    AND a.grantee=0
            """), {"schema": self.schema_name}), 0)


if __name__ == "__main__":
    unittest.main()
