"""Isolated SQLite contracts for the host boot journal; no host/production access."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes import server_boot as route
from app.models.server_boot import ServerBootEvent, ServerBootImportStatus
from app.services import server_boot as service
from app.workers import server_boot as worker


NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
EVENT_ID = "a" * 32
SOURCE = "local-development"
API_PATH = "/api/admin/server-boots"


def event_bytes(event_id=EVENT_ID, *, boot_time=None, recorded_at=None, uptime="60.000"):
    boot_time = boot_time or NOW - timedelta(minutes=1)
    recorded_at = recorded_at or NOW
    return (
        "# Host boot event\n[server_boot]\n"
        f"format_version = 1\nevent_id = {event_id}\n"
        f"boot_time_utc = {boot_time.isoformat()}\n"
        f"recorded_at_utc = {recorded_at.isoformat()}\n"
        f"uptime_seconds_at_record = {uptime}\n"
        "reason = unknown\nclock = system_clock_not_independently_verified\n"
    ).encode("utf-8")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BootParserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.filename = f"boot-{EVENT_ID}.txt"
        self.path = self.directory / self.filename

    def tearDown(self):
        self.temporary.cleanup()

    def test_recorder_format_compatibility_and_utc_normalization(self):
        recorder = load_module(
            "server_boot_test_recorder", Path(__file__).parents[2] / "deploy/stability/record_boot.py",
        )
        event = recorder.BootEvent(EVENT_ID, NOW - timedelta(minutes=1), NOW, 60.125)
        parsed = service.parse_event(recorder.encode_event(event).encode("utf-8"), self.filename)
        self.assertEqual(parsed.event_id, EVENT_ID)
        self.assertEqual(parsed.boot_time, event.booted_at)
        self.assertEqual(parsed.uptime_seconds, 60.125)
        local = NOW.astimezone(timezone(timedelta(hours=3)))
        parsed = service.parse_event(event_bytes(recorded_at=local), self.filename)
        self.assertEqual(parsed.recorded_at.isoformat(), NOW.isoformat())

    def test_strict_schema_and_values(self):
        good = event_bytes()
        bad = [
            b"\xff" + good, good.replace(b"[server_boot]", b"[other]"),
            good + b"unexpected = value\n", good + b"reason = unknown\n",
            good + b"[other]\n", b"[DEFAULT]\n" + good,
            good.replace(b"format_version = 1", b"format_version = 2"),
            good.replace(b"reason = unknown", b"reason = crash"),
            good.replace(b"system_clock_not_independently_verified", b"verified"),
            good.replace(b"event_id = " + EVENT_ID.encode(), b"event_id = " + b"b" * 32),
            good.replace(b"reason = unknown\n", b""),
            good.replace(b"reason = unknown", b"Reason = unknown"),
            good.replace(b"reason = unknown", b"reason: unknown"),
            good.replace(b"reason = unknown", b"reason = unknown\n  continuation"),
            good.replace(b"+00:00", b""),
            good.replace(b"2026-09-25", b"2026-02-30"),
            good.replace(b"T12:00:00", b"T25:00:00"),
            good.replace(b"+00:00", b"+24:00"),
        ]
        for uptime in ("nan", "inf", "-1", "1e999", "1_000", "9" * 1000):
            bad.append(event_bytes(uptime=uptime))
        for raw in bad:
            with self.subTest(case=bad.index(raw)):
                with self.assertRaisesRegex(ValueError, "^Invalid boot event$"):
                    service.parse_event(raw, self.filename)

    def test_size_boundary_and_path_traversal(self):
        good = event_bytes()
        padded = good + b"#" + b"x" * (service.MAX_EVENT_BYTES - len(good) - 1)
        self.assertEqual(len(padded), 8192)
        service.parse_event(padded, self.filename)
        with self.assertRaises(ValueError):
            service.parse_event(padded + b"x", self.filename)
        for name in (f"../{self.filename}", f"/tmp/{self.filename}", "boot-nope.txt", self.filename + "\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                service.read_event(-1, name)

    def test_symlink_directory_fifo_nonregular_and_oversize_are_rejected(self):
        valid = self.directory / ("boot-" + "b" * 32 + ".txt")
        valid.write_bytes(event_bytes("b" * 32))
        self.path.symlink_to(valid)
        (self.directory / ("boot-" + "c" * 32 + ".txt")).mkdir()
        os.mkfifo(self.directory / ("boot-" + "d" * 32 + ".txt"))
        (self.directory / ("boot-" + "e" * 32 + ".txt")).write_bytes(b"x" * 8193)
        result = service.scan_directory(self.directory)
        self.assertEqual(result.checked_files, 5)
        self.assertEqual(result.invalid_files, 4)
        self.assertEqual([e.event_id for e in result.events], ["b" * 32])
        self.assertIsNone(result.error_code)
        self.assertTrue(self.path.is_symlink())

    def test_symlink_swap_after_directory_scan_does_not_follow(self):
        self.path.write_bytes(event_bytes())
        real_open = os.open

        def swapped_open(path, flags, *args, **kwargs):
            if path == self.filename:
                self.path.unlink()
                self.path.symlink_to(self.directory / "absent")
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertTrue(flags & os.O_NONBLOCK)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(service.os, "open", side_effect=swapped_open):
            result = service.scan_directory(self.directory)
        self.assertEqual(result.invalid_files, 1)
        self.assertEqual(result.events, [])

    def test_fifo_swap_after_directory_scan_does_not_block(self):
        self.path.write_bytes(event_bytes())
        real_open = os.open

        def swapped_open(path, flags, *args, **kwargs):
            if path == self.filename:
                self.path.unlink()
                os.mkfifo(self.path)
                self.assertTrue(flags & os.O_NONBLOCK)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(service.os, "open", side_effect=swapped_open):
            result = service.scan_directory(self.directory)
        self.assertEqual(result.invalid_files, 1)
        self.assertEqual(result.events, [])

    def test_in_place_mutation_is_rejected_and_reads_are_bounded(self):
        self.path.write_bytes(event_bytes())
        real_read = os.read
        mutated = False

        def changing_read(fd, length):
            nonlocal mutated
            self.assertLessEqual(length, service.MAX_EVENT_BYTES + 1)
            chunk = real_read(fd, length)
            if not mutated:
                self.path.write_bytes(event_bytes() + b"# changed\n")
                mutated = True
            return chunk

        with patch.object(service.os, "read", side_effect=changing_read):
            result = service.scan_directory(self.directory)
        self.assertEqual(result.invalid_files, 1)

    def test_directory_errors_and_scan_cap_are_explicit(self):
        self.assertEqual(service.scan_directory(self.directory / "missing").error_code, "directory_missing")
        self.path.symlink_to(self.directory, target_is_directory=True)
        self.assertEqual(service.scan_directory(self.path).error_code, "directory_unreadable")
        self.assertEqual(service.scan_directory(self.directory / ".." / "elsewhere").error_code, "directory_unreadable")
        with patch.object(service.os, "open", side_effect=PermissionError(errno.EACCES, "not logged")):
            self.assertEqual(service.scan_directory(self.directory).error_code, "directory_unreadable")
        with patch.object(service.os, "scandir", side_effect=OSError("not logged")):
            self.assertEqual(service.scan_directory(self.directory).error_code, "scan_failed")
        for letter in "bc":
            (self.directory / f"boot-{letter * 32}.txt").write_bytes(event_bytes(letter * 32))
        with patch.object(service, "MAX_SCAN_FILES", 2):
            result = service.scan_directory(self.directory)
        self.assertEqual(result.checked_files, 2)
        self.assertEqual(result.error_code, "too_many_files")

    def test_pending_files_are_never_opened_or_counted_but_scan_is_bounded(self):
        self.path.write_bytes(event_bytes())
        for i in range(3):
            os.mkfifo(self.directory / f".boot-pending-{i}")
        real_read = service.read_event
        with patch.object(service, "read_event", wraps=real_read) as read:
            result = service.scan_directory(self.directory)
        self.assertEqual((result.checked_files, result.invalid_files), (1, 0))
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[1], self.filename)
        with patch.object(service, "MAX_SCAN_FILES", 3):
            result = service.scan_directory(self.directory)
        self.assertEqual(result.error_code, "too_many_files")


class ServerBootStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        for model in (ServerBootEvent, ServerBootImportStatus):
            model.__table__.to_metadata(metadata)
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.role = "admin"
        self.app = FastAPI()
        self.app.include_router(route.router, prefix=API_PATH)

        async def current_user():
            return SimpleNamespace(role=SimpleNamespace(value=self.role))

        async def database():
            async with self.sessions() as db:
                yield db

        self.app.dependency_overrides[get_current_user] = current_user
        self.app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")
        self.env = patch.dict(os.environ, {"SERVER_BOOT_SOURCE_ID": SOURCE})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.client.aclose()
        await self.engine.dispose()
        self.temporary.cleanup()

    def write_event(self, event_id=EVENT_ID, **kwargs):
        path = self.directory / f"boot-{event_id}.txt"
        path.write_bytes(event_bytes(event_id, **kwargs))
        return path

    async def tick(self, *, now=NOW, source_id=SOURCE, directory=None):
        return await worker.run_once(
            self.sessions, directory=directory or self.directory, source_id=source_id, now=now,
        )

    async def report(self, **kwargs):
        async with self.sessions() as db:
            return await service.list_server_boots(db, source_id=SOURCE, now=NOW, **kwargs)

    async def healthy(self, now=NOW):
        return await worker.healthcheck(self.sessions, source_id=SOURCE, now=now)

    async def test_waiting_empty_contract_and_no_write_routes(self):
        response = await self.client.get(API_PATH)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "period_days": 0, "total": 0, "all_time_count": 0, "last_7_days_count": 0,
            "first_imported_at": None, "items": [],
            "import_status": {
                "state": "waiting", "last_attempt_at": None, "last_success_at": None,
                "invalid_files": 0, "conflicting_files": 0, "checked_files": 0, "error_code": None,
            },
        })
        self.assertFalse(await self.healthy())
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual((await self.client.request(method, API_PATH)).status_code, 405)

    async def test_role_403_and_unauthenticated_401(self):
        for role in ("executor", "teamlead", "auditor"):
            self.role = role
            response = await self.client.get(API_PATH)
            self.assertEqual(response.status_code, 403, response.text)
        del self.app.dependency_overrides[get_current_user]
        response = await self.client.get(API_PATH)
        self.assertEqual(response.status_code, 401, response.text)

    async def test_pagination_validation_and_default_limit(self):
        for query in (
            "days=-1", "days=367", "days=bad", "days=1.5", "limit=0", "limit=101",
            "offset=-1", f"offset={service.MAX_OFFSET + 1}", "offset=1.5",
        ):
            with self.subTest(query=query):
                self.assertEqual((await self.client.get(f"{API_PATH}?{query}")).status_code, 422)
        for i in range(28):
            self.write_event(f"{i:032x}")
        await self.tick()
        with patch.object(service, "utc_now", return_value=NOW):
            default = await self.client.get(API_PATH)
            page = await self.client.get(f"{API_PATH}?days=366&limit=2&offset=25")
            end = await self.client.get(f"{API_PATH}?offset={service.MAX_OFFSET}")
        self.assertEqual(len(default.json()["items"]), 25)
        self.assertEqual(default.json()["total"], 28)
        self.assertEqual([i["event_id"] for i in page.json()["items"]], [f"{i:032x}" for i in (25, 26)])
        self.assertEqual(page.json()["period_days"], 366)
        self.assertEqual(end.json()["items"], [])
        self.assertEqual(end.json()["total"], 28)

    async def test_counts_boundaries_sorting_and_utc_contract(self):
        for i, boot in enumerate((
            NOW - timedelta(days=400), NOW - timedelta(days=7, microseconds=1),
            NOW - timedelta(days=7), NOW - timedelta(days=1), NOW - timedelta(days=1),
            NOW, NOW + timedelta(microseconds=1),
        )):
            self.write_event(f"{i:032x}", boot_time=boot)
        await self.tick(now=NOW - timedelta(seconds=30))
        report = await self.report(days=7, limit=2, offset=1)
        self.assertEqual((report.total, report.all_time_count, report.last_7_days_count), (4, 7, 4))
        self.assertEqual([i.event_id for i in report.items], [f"{i:032x}" for i in (3, 4)])
        all_time = await self.report()
        self.assertEqual(all_time.total, 7)
        self.assertEqual([i.event_id for i in all_time.items], [f"{i:032x}" for i in (6, 5, 3, 4, 2, 1, 0)])
        self.assertGreater(all_time.items[0].boot_time, NOW)
        self.assertEqual((await self.report(days=1)).total, 3)
        self.assertEqual(report.first_imported_at, NOW - timedelta(seconds=30))
        with patch.object(service, "utc_now", return_value=NOW):
            body = (await self.client.get(API_PATH)).json()
        item = body["items"][0]
        self.assertEqual(set(item), {
            "source_id", "event_id", "boot_time", "recorded_at", "imported_at", "uptime_seconds", "reason", "clock",
        })
        self.assertEqual(item["reason"], "unknown")
        self.assertEqual(item["clock"], "system_clock_not_independently_verified")
        for name in ("boot_time", "recorded_at", "imported_at"):
            self.assertTrue(item[name].endswith("Z"), item)

    async def test_dedup_conflict_preserves_first_event_and_multiple_sources(self):
        self.write_event()
        first = await self.tick()
        self.assertEqual(first.state, "ok")
        await self.tick(now=NOW + timedelta(seconds=10))
        self.assertEqual((await self.report()).total, 1)
        self.write_event(uptime="99.000")
        status = await self.tick(now=NOW + timedelta(seconds=20))
        self.assertEqual((status.state, status.conflicting_files, status.error_code), ("degraded", 1, "conflicting_files"))
        self.assertEqual(status.last_success_at, NOW + timedelta(seconds=10))
        self.assertFalse(await self.healthy(NOW + timedelta(seconds=20)))
        item = (await self.report()).items[0]
        self.assertEqual(item.uptime_seconds, 60)
        self.assertEqual(item.imported_at, NOW)
        await self.tick(source_id="primary-vps")
        self.assertEqual((await self.report()).total, 2)
        self.write_event()
        self.assertEqual((await self.tick(now=NOW + timedelta(seconds=30))).state, "ok")

    async def test_bad_files_allow_good_import_and_degraded_health(self):
        valid = self.write_event()
        invalid = self.directory / ("boot-" + "b" * 32 + ".txt")
        invalid.write_bytes(b"not INI")
        status = await self.tick()
        self.assertEqual(status.state, "degraded")
        self.assertEqual(status.error_code, "invalid_files")
        self.assertEqual((status.checked_files, status.invalid_files), (2, 1))
        self.assertIsNone(status.last_success_at)
        self.assertEqual((await self.report()).total, 1)
        self.assertTrue(await self.healthy())
        self.assertEqual(valid.read_bytes(), event_bytes())
        self.assertTrue(invalid.exists())

    async def test_missing_directory_persists_failure_and_recovers(self):
        await self.tick(now=NOW - timedelta(seconds=30))
        missing = self.directory / "not-created"
        status = await self.tick(directory=missing)
        self.assertEqual(status.state, "degraded")
        self.assertEqual(status.error_code, "directory_missing")
        self.assertEqual(status.last_success_at, NOW - timedelta(seconds=30))
        self.assertEqual((await self.report()).import_status, status)
        self.assertFalse(await self.healthy())
        self.assertFalse(missing.exists())
        missing.mkdir()
        status = await self.tick(directory=missing, now=NOW + timedelta(seconds=60))
        self.assertEqual(status.state, "ok")
        self.assertEqual(status.last_success_at, NOW + timedelta(seconds=60))
        self.assertTrue(await self.healthy(NOW + timedelta(seconds=60)))

    async def test_unreadable_scan_failure_and_cap_are_persisted(self):
        await self.tick(now=NOW - timedelta(seconds=30))
        for error_code in ("directory_unreadable", "scan_failed", "too_many_files"):
            with self.subTest(error_code=error_code):
                with patch.object(service, "scan_directory", return_value=service.BootScan(error_code=error_code)):
                    status = await self.tick()
                self.assertEqual(status.error_code, error_code)
                self.assertEqual(status.state, "degraded")
                self.assertEqual(status.last_success_at, NOW - timedelta(seconds=30))
                self.assertEqual((await self.report()).import_status.error_code, error_code)
                self.assertFalse(await self.healthy())

    async def test_cap_import_is_explicitly_partial_never_successful(self):
        for i in range(3):
            self.write_event(f"{i:032x}")
        with patch.object(service, "MAX_SCAN_FILES", 2):
            status = await self.tick()
        self.assertEqual(status.checked_files, 2)
        self.assertEqual(status.error_code, "too_many_files")
        self.assertIsNone(status.last_success_at)
        self.assertEqual((await self.report()).total, 2)
        self.assertFalse(await self.healthy())
        await self.tick(now=NOW + timedelta(seconds=60))
        self.assertEqual((await self.report()).total, 3)

    async def test_staleness_boundary_preserves_failure_details(self):
        await self.tick(now=NOW - timedelta(seconds=180))
        self.assertEqual((await self.report()).import_status.state, "ok")
        self.assertTrue(await self.healthy())
        self.assertFalse(await self.healthy(NOW + timedelta(microseconds=1)))
        await self.tick(directory=self.directory / "missing", now=NOW - timedelta(seconds=181))
        status = (await self.report()).import_status
        self.assertEqual(status.state, "stale")
        self.assertEqual(status.error_code, "directory_missing")

    async def test_future_heartbeat_after_clock_rollback_is_not_healthy(self):
        await self.tick(now=NOW + timedelta(days=1))
        self.assertEqual((await self.report()).import_status.state, "stale")
        self.assertFalse(await self.healthy())
        await self.tick(now=NOW + timedelta(seconds=5))
        self.assertEqual((await self.report()).import_status.state, "ok")
        await self.tick(now=NOW + timedelta(seconds=5, microseconds=1))
        self.assertEqual((await self.report()).import_status.state, "stale")
        await self.tick(now=NOW)
        self.assertTrue(await self.healthy())

    async def test_commit_failure_rolls_back_events_and_heartbeat_then_retries(self):
        self.write_event()

        def fail_commit(connection):
            raise RuntimeError("simulated database outage")

        sa.event.listen(self.engine.sync_engine, "commit", fail_commit)
        try:
            with self.assertRaises(RuntimeError):
                await self.tick()
        finally:
            sa.event.remove(self.engine.sync_engine, "commit", fail_commit)
        report = await self.report()
        self.assertEqual(report.total, 0)
        self.assertEqual(report.import_status.state, "waiting")
        self.assertFalse(await self.healthy())
        await self.tick(now=NOW + timedelta(seconds=60))
        self.assertEqual((await self.report()).total, 1)

    async def test_late_transaction_failure_does_not_leave_partial_import(self):
        self.write_event()
        self.write_event("b" * 32)
        with patch.object(AsyncSession, "flush", side_effect=RuntimeError("simulated write failure")):
            with self.assertRaises(RuntimeError):
                await self.tick()
        self.assertEqual((await self.report()).total, 0)
        self.assertEqual((await self.report()).import_status.state, "waiting")
        await self.tick()
        self.assertEqual((await self.report()).total, 2)

    async def test_failed_existing_import_preserves_last_committed_heartbeat(self):
        self.write_event()
        await self.tick(now=NOW - timedelta(seconds=181))
        self.write_event("b" * 32)
        with patch.object(AsyncSession, "flush", side_effect=RuntimeError("simulated write failure")):
            with self.assertRaises(RuntimeError):
                await self.tick()
        report = await self.report()
        self.assertEqual(report.total, 1)
        self.assertEqual(report.import_status.state, "stale")
        self.assertEqual(report.import_status.last_attempt_at, NOW - timedelta(seconds=181))

    async def test_worker_uses_environment_source_and_read_only_directory(self):
        self.write_event()
        with patch.dict(os.environ, {"SERVER_BOOT_EVENTS_DIR": str(self.directory), "SERVER_BOOT_SOURCE_ID": "primary-vps"}):
            await worker.run_once(self.sessions, now=NOW)
        item = (await self.report()).items[0]
        self.assertEqual(item.source_id, "primary-vps")
        self.assertEqual((await self.report()).import_status.state, "waiting")
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [f"boot-{EVENT_ID}.txt"])

    async def test_existing_hash_lookup_is_batched_and_unchanged_events_are_not_written(self):
        for i in range(501):
            self.write_event(f"{i:032x}")
        statements = []

        def record_statement(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(self.engine.sync_engine, "before_cursor_execute", record_statement)
        try:
            await self.tick()
            inserts = [s for s in statements if s.startswith("INSERT INTO server_boot_events")]
            self.assertEqual(len(inserts), 2)
            hashes = [s for s in statements if s.startswith("SELECT server_boot_events.event_id")]
            self.assertEqual(len(hashes), 1)
            statements.clear()
            await self.tick(now=NOW + timedelta(seconds=60))
            self.assertFalse(any(s.startswith("INSERT INTO server_boot_events") for s in statements))
            self.assertEqual(sum(s.startswith("SELECT server_boot_events.event_id") for s in statements), 1)
        finally:
            sa.event.remove(self.engine.sync_engine, "before_cursor_execute", record_statement)
        self.assertEqual((await self.report()).total, 501)


class WorkerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_retry_next_loop_without_raw_error_logs(self):
        good = service.ServerBootImportRead(state="ok")
        tick = AsyncMock(side_effect=[RuntimeError("sensitive fixture, do not log"), good])
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
        with patch.dict(os.environ, {"SERVER_BOOT_POLL_SECONDS": "60"}), \
                patch.object(worker, "run_once", tick), patch.object(worker.asyncio, "sleep", sleep), \
                self.assertLogs("server_boot", level="INFO") as logs:
            with self.assertRaises(asyncio.CancelledError):
                await worker.run(object())
        self.assertEqual(tick.await_count, 2)
        self.assertEqual(sleep.await_args_list[0].args, (60,))
        self.assertNotIn("sensitive fixture", " ".join(logs.output))

    async def test_once_returns_after_commit_without_sleep(self):
        for status, expected in (("ok", 0), ("degraded", 1)):
            with patch.object(worker, "run_once", AsyncMock(return_value=service.ServerBootImportRead(state=status))), \
                    patch.object(worker.asyncio, "sleep", AsyncMock()) as sleep:
                self.assertEqual(await worker.run(object(), once=True), expected)
                sleep.assert_not_awaited()
        with patch.object(worker, "run_once", AsyncMock(side_effect=RuntimeError("private"))), \
                self.assertLogs("server_boot"):
            self.assertEqual(await worker.run(object(), once=True), 1)

    def test_interval_default_minimum_and_nonfinite(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(worker.poll_seconds(), 60)
            self.assertEqual(service.source_id_from_env(), "primary-vps")
        for value, expected in (("1", 10), ("-2", 10), ("60", 60), ("120", 120)):
            with patch.dict(os.environ, {"SERVER_BOOT_POLL_SECONDS": value}):
                self.assertEqual(worker.poll_seconds(), expected)
        for value in ("inf", "nan", "bad"):
            with patch.dict(os.environ, {"SERVER_BOOT_POLL_SECONDS": value}), self.assertRaises(ValueError):
                worker.poll_seconds()
        for value in ("", "../other", "x\n", "a" * 101):
            with self.assertRaises(ValueError):
                service.validate_source_id(value)


class ServerBootMigrationTests(unittest.TestCase):
    def test_revision_upgrade_constraints_indexes_and_downgrade(self):
        migration = load_module(
            "server_boot_test_migration", Path(__file__).parents[1] / "alembic/versions/097_server_boot_events.py",
        )
        self.assertEqual(migration.revision, "097_server_boot_events")
        self.assertEqual(migration.down_revision, "096_graph_documents")
        self.assertLessEqual(len(migration.revision), 32)
        engine = sa.create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE unrelated_graph_work (id INTEGER PRIMARY KEY)")
                with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                    migration.upgrade()
                    inspector = sa.inspect(connection)
                    unique = inspector.get_unique_constraints("server_boot_events")
                    self.assertIn(["source_id", "event_id"], [c["column_names"] for c in unique])
                    indexes = inspector.get_indexes("server_boot_events")
                    self.assertIn("ix_server_boot_events_boot_time", [i["name"] for i in indexes])
                    for model in (ServerBootEvent, ServerBootImportStatus):
                        columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
                        self.assertEqual(columns, set(model.__table__.columns.keys()))
                    table = sa.Table("server_boot_import_status", sa.MetaData(), autoload_with=connection)
                    connection.execute(table.insert().values(source_id=SOURCE, last_attempt_at=NOW))
                    with self.assertRaises(sa.exc.IntegrityError):
                        connection.execute(table.insert().values(source_id="bad-code", last_attempt_at=NOW, error_code="raw error"))
                    with self.assertRaises(sa.exc.IntegrityError):
                        connection.execute(table.insert().values(source_id="negative", last_attempt_at=NOW, invalid_files=-1))
                    migration.downgrade()
                    self.assertEqual(sa.inspect(connection).get_table_names(), ["unrelated_graph_work"])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
