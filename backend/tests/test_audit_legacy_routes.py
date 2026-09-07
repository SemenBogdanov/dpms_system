"""Isolated staging API tests with synthetic XLSX and a disposable SQLite DB.

SQLite substitutes transaction-scoped locks in concurrency tests; the PostgreSQL
lock SQL is asserted separately. Real multi-process PG races remain an integration
gate. This module never connects to configured application storage.
"""

import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, get_ident
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from anyio import CapacityLimiter
from fastapi import FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Column, JSON, MetaData, String, Table, event, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import StatementError
from sqlalchemy.schema import CreateTable

from app.api.deps import get_current_user, get_db
from app.api.routes import audit_legacy as routes
from app.models.activity import ActivityEvent
from app.models.audit_legacy import AuditLegacyImport
from app.models.user import UserRole


BASE = "/api/audit/legacy-imports"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def workbook_bytes(rows=None, *, sheet_name="Source") -> bytes:
    if rows is None:
        rows = [["case_key", "digital_product"], ["case-001", "Synthetic product"]]
    sheet = ET.Element("worksheet", xmlns=NS)
    sheet_data = ET.SubElement(sheet, "sheetData")
    for row_number, values in enumerate(rows, 1):
        row = ET.SubElement(sheet_data, "row", r=str(row_number))
        for index, value in enumerate(values):
            cell = ET.SubElement(row, "c", r=f"{chr(65 + index)}{row_number}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = str(value)
    book = ET.Element("workbook", xmlns=NS)
    ET.SubElement(
        ET.SubElement(book, "sheets"), "sheet", name=sheet_name, sheetId="1",
        attrib={"{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId1"},
    )
    relationships = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    ET.SubElement(
        relationships, "Relationship", Id="rId1", Target="worksheets/sheet1.xml",
        Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", ET.tostring(book))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return output.getvalue()


def mapping_for(batch, *, kind="cases", fields=None):
    return {
        "sheet_id": batch["inspection"]["sheets"][0]["id"],
        "header_row": 1,
        "kind": kind,
        "fields": {"case_key": "A", "digital_product": "B"} if fields is None else fields,
    }


class AuditLegacyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="dpms-legacy-staging-test-")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/isolated.sqlite")
        @event.listens_for(self.engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.admin_id, self.second_admin_id = uuid4(), uuid4()
        metadata = MetaData()
        users = Table("users", metadata, Column("id", postgresql.UUID(as_uuid=True), primary_key=True))
        Table("tasks", metadata, Column("id", postgresql.UUID(as_uuid=True), primary_key=True))
        AuditLegacyImport.__table__.to_metadata(metadata)
        activity_table = ActivityEvent.__table__.to_metadata(metadata)
        activity_table.c.metadata.type = JSON()
        self.targets = [
            Table(name, metadata, Column("id", String, primary_key=True), Column("value", String))
            for name in ("audit_cases", "audit_atoms", "audit_assignments", "audit_events", "audit_import_batches")
        ]
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(users.insert(), [{"id": self.admin_id}, {"id": self.second_admin_id}])
            for target in self.targets:
                await connection.execute(target.insert().values(id="existing", value="unchanged"))
        self.sql = []

        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
            self.sql.append(statement)

        self.user = SimpleNamespace(id=self.admin_id, role=UserRole.admin, audit_enabled=True)
        self.staging_lock = asyncio.Lock()
        self.row_locks = {}
        original_batch = routes._batch_or_404

        async def acquire(db, lock):
            if lock not in db.info.get("test_locks", []):
                await lock.acquire()
                db.info.setdefault("test_locks", []).append(lock)

        async def staging_lock(db):
            await acquire(db, self.staging_lock)

        async def batch_or_404(db, batch_id, *, for_update=False):
            if for_update:
                await acquire(db, self.row_locks.setdefault(batch_id, asyncio.Lock()))
            return await original_batch(db, batch_id, for_update=for_update)

        self.patchers = [
            patch.object(routes, "_lock_staging", side_effect=staging_lock),
            patch.object(routes, "_batch_or_404", side_effect=batch_or_404),
            patch.object(routes, "PARSER_LIMITER", CapacityLimiter(1)),
        ]
        for patcher in self.patchers:
            patcher.start()

        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
                finally:
                    for lock in reversed(db.info.get("test_locks", [])):
                        lock.release()

        async def current_user():
            if self.user is None:
                raise HTTPException(status_code=401, detail="Not signed in")
            return self.user

        app = FastAPI()
        app.include_router(routes.router, prefix=BASE)
        app.dependency_overrides[get_current_user] = current_user
        app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.data = workbook_bytes()

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.directory.cleanup()

    async def upload(self, data=None, *, filename="synthetic.xlsx"):
        return await self.client.post(BASE, files={"file": (filename, self.data if data is None else data, "application/octet-stream")})

    async def create_batch(self, data=None):
        response = await self.upload(data)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def update_mapping(self, batch, mapping=None, *, revision=None):
        return await self.client.put(f"{BASE}/{batch['id']}/mapping", json={
            "revision": batch["revision"] if revision is None else revision,
            "mapping": mapping_for(batch) if mapping is None else mapping,
        })

    async def count_batches(self):
        async with self.sessions() as db:
            return await db.scalar(select(func.count()).select_from(AuditLegacyImport))

    async def test_upload_detail_list_and_source_contract(self):
        response = await self.upload(filename="private-source-person-name.XLSX")
        self.assertEqual(response.status_code, 200, response.text)
        batch = response.json()
        self.assertEqual(set(batch), {
            "id", "sha256", "size_bytes", "status", "created_at", "updated_at", "revision",
            "inspection", "mapping", "report",
        })
        self.assertEqual(batch["sha256"], sha256(self.data).hexdigest())
        self.assertEqual(batch["size_bytes"], len(self.data))
        self.assertEqual(batch["status"], "uploaded")
        self.assertEqual(batch["revision"], 1)
        self.assertIsNone(batch["mapping"])
        self.assertIsNone(batch["report"])
        self.assertTrue(batch["created_at"].endswith("Z"))
        self.assertNotIn("private-source-person-name", response.text)
        self.sql.clear()
        detail = await self.client.get(f"{BASE}/{batch['id']}")
        listing = await self.client.get(BASE)
        self.assertEqual(detail.json(), batch)
        self.assertEqual(listing.json(), [batch])
        self.assertTrue(all("source_bytes" not in statement for statement in self.sql))
        for result in (response, detail, listing):
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual(result.headers["x-content-type-options"], "nosniff")
        source = await self.client.get(f"{BASE}/{batch['id']}/source")
        self.assertEqual(source.content, self.data)
        self.assertEqual(source.headers["content-disposition"], 'attachment; filename="audit-legacy-source.xlsx"')
        self.assertEqual(source.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(source.headers["cache-control"], "no-store")
        self.assertEqual(source.headers["x-content-type-options"], "nosniff")

    async def test_every_endpoint_requires_audit_and_admin(self):
        batch = await self.create_batch()
        requests = [
            ("GET", BASE, {}),
            ("POST", BASE, {"files": {"file": ("source.xlsx", self.data)}}),
            ("GET", f"{BASE}/{batch['id']}", {}),
            ("PUT", f"{BASE}/{batch['id']}/mapping", {"json": {"revision": 1, "mapping": mapping_for(batch)}}),
            ("GET", f"{BASE}/{batch['id']}/source", {}),
            ("DELETE", f"{BASE}/{batch['id']}?revision=1", {}),
        ]
        for role, enabled in [("executor", False), ("executor", True), ("teamlead", True)]:
            self.user = SimpleNamespace(role=UserRole(role), audit_enabled=enabled)
            self.sql.clear()
            for method, path, kwargs in requests:
                with self.subTest(role=role, enabled=enabled, path=path, method=method):
                    result = await self.client.request(method, path, **kwargs)
                    self.assertEqual(result.status_code, 403, result.text)
            self.assertEqual(self.sql, [])
        self.user = None
        for method, path, kwargs in requests:
            self.assertEqual((await self.client.request(method, path, **kwargs)).status_code, 401)

    async def test_admin_uses_existing_audit_access_policy(self):
        self.user = SimpleNamespace(id=self.admin_id, role=UserRole.admin, audit_enabled=False)
        self.assertEqual((await self.upload()).status_code, 200)

    async def test_extension_empty_and_size_rejected_before_parser(self):
        with patch.object(routes, "inspect_legacy_workbook") as parser:
            for filename in ("data.xls", "data.xlsm", "data.csv", "data", "data.xlsx.exe"):
                self.assertEqual((await self.upload(filename=filename)).status_code, 415)
            self.assertEqual((await self.upload(b"")).status_code, 422)
            self.assertEqual((await self.upload(b"a" * (routes.MAX_UPLOAD_BYTES + 1))).status_code, 413)
            parser.assert_not_called()
        self.assertEqual(await self.count_batches(), 0)

    async def test_upload_read_is_bounded_even_without_size_metadata(self):
        file = UploadFile(filename="source.xlsx", file=BytesIO(b"a" * (routes.MAX_UPLOAD_BYTES + 1)))
        with patch.object(file, "read", wraps=file.read) as read:
            with self.assertRaises(HTTPException) as failure:
                await routes._upload_bytes(file)
            self.assertEqual(failure.exception.status_code, 413)
            read.assert_awaited_once_with(routes.MAX_UPLOAD_BYTES + 1)
        self.assertTrue(file.file.closed)

    async def test_invalid_workbook_does_not_persist_or_echo_content(self):
        marker = "private-invalid-workbook-content"
        result = await self.upload(marker.encode())
        self.assertEqual(result.status_code, 400, result.text)
        self.assertNotIn(marker, result.text)
        self.assertEqual(await self.count_batches(), 0)

    async def test_duplicate_returns_checked_batch_without_reparse(self):
        batch = await self.create_batch()
        checked = await self.update_mapping(batch)
        self.assertEqual(checked.status_code, 200, checked.text)
        with patch.object(routes, "inspect_legacy_workbook") as parser:
            duplicate = await self.upload(filename="different-name.xlsx")
            parser.assert_not_called()
        self.assertEqual(duplicate.json(), checked.json())
        self.assertEqual(await self.count_batches(), 1)

    async def test_concurrent_duplicate_has_one_durable_source(self):
        with patch.object(routes, "inspect_legacy_workbook", wraps=routes.inspect_legacy_workbook) as parser:
            first, second = await asyncio.gather(self.upload(), self.upload())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(await self.count_batches(), 1)
        async with self.sessions() as restarted:
            self.assertEqual(await restarted.scalar(select(AuditLegacyImport.source_bytes)), self.data)

    async def test_global_cap_allows_duplicate_and_delete_frees_slot(self):
        first = await self.create_batch()
        for index in range(1, routes.MAX_STAGING_BATCHES):
            await self.create_batch(workbook_bytes(sheet_name=f"Source{index}"))
        self.assertEqual(await self.count_batches(), 20)
        with patch.object(routes, "inspect_legacy_workbook") as parser:
            self.assertEqual((await self.upload()).json(), first)
            rejected = await self.upload(workbook_bytes(sheet_name="OverCapacity"))
            self.assertEqual(rejected.status_code, 409, rejected.text)
            parser.assert_not_called()
        self.assertEqual((await self.client.delete(f"{BASE}/{first['id']}?revision=1")).status_code, 204)
        await self.create_batch(workbook_bytes(sheet_name="Replacement"))
        self.assertEqual(await self.count_batches(), 20)

    async def test_concurrent_last_slot_cannot_exceed_cap(self):
        with patch.object(routes, "MAX_STAGING_BATCHES", 2):
            await self.create_batch()
            responses = await asyncio.gather(
                self.upload(workbook_bytes(sheet_name="A")),
                self.upload(workbook_bytes(sheet_name="B")),
            )
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(await self.count_batches(), 2)

    async def test_mapping_revision_conflict_and_required_delete_revision(self):
        batch = await self.create_batch()
        checked_response = await self.update_mapping(batch)
        self.assertEqual(checked_response.status_code, 200, checked_response.text)
        checked = checked_response.json()
        self.assertEqual(checked["revision"], 2)
        self.assertEqual(checked["status"], "checked")
        self.assertEqual(checked["created_at"], batch["created_at"])
        self.assertGreater(checked["updated_at"], batch["updated_at"])
        self.assertEqual(checked["report"]["valid_rows"], 1)
        self.assertFalse(checked["report"]["ready_for_import"])
        with patch.object(routes, "preview_legacy_mapping") as parser:
            self.assertEqual((await self.update_mapping(batch)).status_code, 409)
            parser.assert_not_called()
        self.assertEqual((await self.client.delete(f"{BASE}/{batch['id']}")).status_code, 422)
        self.assertEqual((await self.client.delete(f"{BASE}/{batch['id']}?revision=1")).status_code, 409)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), checked)
        result = await self.client.delete(f"{BASE}/{batch['id']}?revision=2")
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result.content, b"")
        self.assertEqual(await self.count_batches(), 0)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}/source")).status_code, 404)

    async def test_concurrent_mapping_and_mapping_delete_have_single_winner(self):
        batch = await self.create_batch()
        results = await asyncio.gather(self.update_mapping(batch), self.update_mapping(batch))
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        batch = next(result.json() for result in results if result.status_code == 200)
        results = await asyncio.gather(
            self.update_mapping(batch),
            self.client.delete(f"{BASE}/{batch['id']}?revision={batch['revision']}"),
        )
        statuses = sorted(result.status_code for result in results)
        self.assertIn(statuses, ([200, 409], [204, 404]))

    async def test_missing_mapping_is_checked_report_not_http_failure(self):
        batch = await self.create_batch()
        result = await self.update_mapping(batch, mapping_for(batch, fields={}))
        self.assertEqual(result.status_code, 200, result.text)
        checked = result.json()
        self.assertEqual(checked["status"], "checked")
        self.assertEqual(checked["report"]["valid_rows"], 0)
        self.assertEqual(checked["report"]["error_rows"], 1)
        self.assertTrue(any(issue["code"] == "missing_mapping" for issue in checked["report"]["issues"]))
        self.assertIs(checked["report"]["ready_for_import"], False)

    async def test_strict_mapping_schema_rejects_invalid_input_without_mutation(self):
        batch = await self.create_batch()
        for value in (True, 1.0, "1", 0, 1048577):
            mapping = mapping_for(batch)
            mapping["header_row"] = value
            self.assertEqual((await self.update_mapping(batch, mapping)).status_code, 422)
        for fields in ({"unsupported": "A"}, {"case_key": "a"}, {"case_key": "XFE"}, {"case_key": "A1"}):
            self.assertEqual((await self.update_mapping(batch, mapping_for(batch, fields=fields))).status_code, 422)
        for value in (True, "1", 1.1, 0):
            self.assertEqual((await self.update_mapping(batch, revision=value)).status_code, 422)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)

    async def test_invalid_mapping_preserves_previous_report_and_revision(self):
        batch = await self.create_batch()
        batch = (await self.update_mapping(batch)).json()
        for changes in ({"sheet_id": "absent"}, {"header_row": 99}, {"fields": {"case_key": "A", "digital_product": "A"}}):
            mapping = mapping_for(batch)
            mapping.update(changes)
            result = await self.update_mapping(batch, mapping)
            self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)

    async def test_duplicate_rows_remain_only_in_report(self):
        batch = await self.create_batch(workbook_bytes([
            ["case_key", "digital_product"], ["case-1", "First"], ["case-1", "Second"],
        ]))
        result = (await self.update_mapping(batch)).json()
        self.assertEqual(result["report"]["duplicate_rows"], 2)
        self.assertEqual(result["report"]["error_rows"], 2)
        self.assertFalse(result["report"]["ready_for_import"])

    async def test_no_lifecycle_action_mutates_registry_targets(self):
        batch = await self.create_batch()
        checked = (await self.update_mapping(batch)).json()
        await self.upload()
        await self.client.get(BASE)
        await self.client.get(f"{BASE}/{batch['id']}/source")
        await self.client.delete(f"{BASE}/{batch['id']}?revision={checked['revision']}")
        writes = [sql.lower() for sql in self.sql if sql.lstrip().lower().startswith(("insert", "update", "delete"))]
        self.assertTrue(writes)
        self.assertTrue(all("audit_legacy_imports" in sql or "activity_events" in sql for sql in writes), writes)
        async with self.sessions() as db:
            for target in self.targets:
                self.assertEqual((await db.execute(select(target))).all(), [("existing", "unchanged")])

    async def test_missing_batch_routes_return_404(self):
        batch = {"id": str(uuid4()), "revision": 1, "inspection": {"sheets": [{"id": "sheet-1"}]}}
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).status_code, 404)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}/source")).status_code, 404)
        self.assertEqual((await self.update_mapping(batch)).status_code, 404)
        self.assertEqual((await self.client.delete(f"{BASE}/{batch['id']}?revision=1")).status_code, 404)

    async def test_parser_runs_off_loop_with_one_shared_capacity_slot(self):
        batch = await self.create_batch()
        loop_thread = get_ident()
        entered = Event()
        release = Event()
        mutex = Lock()
        active = 0
        peak = 0
        threads = []
        inspect_parser = routes.inspect_legacy_workbook
        preview_parser = routes.preview_legacy_mapping

        def bounded_call(function, *args):
            nonlocal active, peak
            with mutex:
                active += 1
                peak = max(peak, active)
                threads.append(get_ident())
            entered.set()
            try:
                if not release.wait(timeout=5):
                    raise AssertionError("Parser test release timed out")
                return function(*args)
            finally:
                with mutex:
                    active -= 1

        with (
            patch.object(routes, "inspect_legacy_workbook", side_effect=lambda *args: bounded_call(inspect_parser, *args)),
            patch.object(routes, "preview_legacy_mapping", side_effect=lambda *args: bounded_call(preview_parser, *args)),
        ):
            tasks = [
                asyncio.create_task(self.update_mapping(batch)),
                asyncio.create_task(self.upload(workbook_bytes(sheet_name="Other"))),
            ]
            try:
                for _ in range(200):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(entered.is_set())
                await asyncio.sleep(0.03)
                self.assertEqual((await self.client.get(BASE)).status_code, 200)
                self.assertEqual(len(threads), 1)
            finally:
                release.set()
                results = await asyncio.gather(*tasks)
        self.assertEqual([result.status_code for result in results], [200, 200])
        self.assertEqual(peak, 1)
        self.assertEqual(len(threads), 2)
        self.assertNotIn(loop_thread, threads)

    async def test_parser_exception_is_sanitized_and_rolls_back(self):
        with patch.object(routes, "inspect_legacy_workbook", side_effect=ValueError("private source value")):
            result = await self.upload()
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("private source value", result.text)
        self.assertEqual(await self.count_batches(), 0)
        batch = await self.create_batch()
        with patch.object(routes, "preview_legacy_mapping", side_effect=ValueError("private source value")):
            result = await self.update_mapping(batch)
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("private source value", result.text)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)


    async def test_provenance_and_metadata_activity_survive_source_deletion(self):
        batch = await self.create_batch()
        async with self.sessions() as db:
            stored = await db.get(AuditLegacyImport, UUID(batch["id"]))
            self.assertEqual((stored.created_by_id, stored.updated_by_id), (self.admin_id, self.admin_id))
        self.user = SimpleNamespace(id=self.second_admin_id, role=UserRole.admin, audit_enabled=True)
        duplicate = await self.upload(filename="private-uploader-name.xlsx")
        self.assertEqual(duplicate.json(), batch)
        checked = (await self.update_mapping(batch)).json()
        async with self.sessions() as db:
            stored = await db.get(AuditLegacyImport, UUID(batch["id"]))
            self.assertEqual((stored.created_by_id, stored.updated_by_id), (self.admin_id, self.second_admin_id))
            self.assertEqual(await db.scalar(select(func.count()).select_from(ActivityEvent)), 2)
        await self.client.delete(f"{BASE}/{batch['id']}?revision={checked['revision']}")
        async with self.sessions() as db:
            events = (await db.execute(select(ActivityEvent).order_by(ActivityEvent.occurred_at))).scalars().all()
            self.assertEqual([item.event_type for item in events], [
                "audit_legacy_uploaded", "audit_legacy_mapping_checked", "audit_legacy_deleted",
            ])
            self.assertEqual([item.actor_id for item in events], [self.admin_id, self.second_admin_id, self.second_admin_id])
            allowed = {
                "batch_id", "sha256", "size_bytes", "revision", "sheet_count", "total_rows",
                "valid_rows", "error_rows", "warning_rows", "duplicate_rows", "issue_count",
            }
            for item in events:
                self.assertLessEqual(set(item.event_data), allowed)
                self.assertIsNone(item.task_id)
                self.assertEqual(item.event_data["batch_id"], batch["id"])
                self.assertEqual(item.event_data["sha256"], batch["sha256"])
                self.assertNotIn("private-uploader-name", str(item.event_data))
                self.assertNotIn("Synthetic product", str(item.event_data))
            self.assertIsNone(await db.get(AuditLegacyImport, UUID(batch["id"])))

    async def test_failed_activity_write_cannot_commit_source_mutations(self):
        with patch.object(routes, "record_activity_event", side_effect=RuntimeError("Synthetic journal failure")):
            with self.assertRaises(RuntimeError):
                await self.upload()
        self.assertEqual(await self.count_batches(), 0)
        batch = await self.create_batch()
        with patch.object(routes, "record_activity_event", side_effect=RuntimeError("Synthetic journal failure")):
            with self.assertRaises(RuntimeError):
                await self.update_mapping(batch)
            with self.assertRaises(RuntimeError):
                await self.client.delete(f"{BASE}/{batch['id']}?revision=1")
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(ActivityEvent)), 1)


    async def test_database_write_errors_do_not_expose_source_parameters(self):
        error = StatementError("Synthetic failure", "INSERT INTO staging", {"source": "private-cell-content"}, None)
        with patch.object(AsyncSession, "flush", side_effect=error):
            result = await self.upload()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private-cell-content", result.text)
        self.assertEqual(await self.count_batches(), 0)
        batch = await self.create_batch()
        with patch.object(AsyncSession, "commit", side_effect=error):
            result = await self.update_mapping(batch)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private-cell-content", result.text)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)
        with patch.object(AsyncSession, "commit", side_effect=error):
            result = await self.client.delete(f"{BASE}/{batch['id']}?revision=1")
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private-cell-content", result.text)
        self.assertEqual((await self.client.get(f"{BASE}/{batch['id']}")).json(), batch)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(ActivityEvent)), 1)


class AuditLegacySQLTests(unittest.IsolatedAsyncioTestCase):
    async def test_transaction_advisory_lock_and_row_lock_sql(self):
        db = AsyncMock(spec=AsyncSession)
        await routes._lock_staging(db)
        query = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("pg_advisory_xact_lock", str(query))
        self.assertEqual(list(query.params.values()), [routes.STAGING_LOCK_ID])
        db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: object())
        await routes._batch_or_404(db, uuid4(), for_update=True)
        query = db.execute.await_args.args[0]
        self.assertIn("FOR UPDATE", str(query.compile(dialect=postgresql.dialect())))
        self.assertTrue(query.get_execution_options()["populate_existing"])

    async def test_model_deferred_bytes_unique_sha_and_staging_only_constraints(self):
        mapper = inspect(AuditLegacyImport)
        self.assertTrue(mapper.attrs.source_bytes.deferred)
        self.assertTrue(mapper.attrs.source_bytes.raiseload)
        self.assertNotIn("source_bytes", str(select(AuditLegacyImport).compile(dialect=postgresql.dialect())))
        ddl = str(CreateTable(AuditLegacyImport.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("source_bytes BYTEA NOT NULL", ddl)
        self.assertIn("UNIQUE (sha256)", ddl)
        self.assertIn("status IN ('uploaded', 'checked')", ddl)
        self.assertEqual({foreign.target_fullname for foreign in AuditLegacyImport.__table__.foreign_keys}, {"users.id"})
        self.assertTrue(all(foreign.ondelete == "SET NULL" for foreign in AuditLegacyImport.__table__.foreign_keys))

    async def test_migration_chain_and_no_registry_table_operations(self):
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "alembic/versions/082_audit_legacy_upload.py"
        spec = importlib.util.spec_from_file_location("audit_legacy_migration_test", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertLessEqual(len(migration.revision), 32)
        self.assertEqual(migration.down_revision, "081_personal_task_form_guide")
        self.assertIn("Рабочий реестр не изменён", migration.ARTICLE["body"])
        with patch.object(migration, "op") as operations:
            operations.get_bind.return_value.execute.return_value.scalar_one.return_value = 0
            migration.upgrade()
            self.assertEqual(operations.create_table.call_args.args[0], "audit_legacy_imports")
            query, parameters = operations.get_bind.return_value.execute.call_args.args
            self.assertIn("INSERT INTO knowledge_articles", str(query))
            self.assertEqual(set(query.compile().params), set(parameters))
            migration.downgrade()
            operations.drop_table.assert_called_once_with("audit_legacy_imports")
        with patch.object(migration, "op") as operations:
            operations.get_bind.return_value.execute.return_value.scalar_one.return_value = 1
            with self.assertRaisesRegex(RuntimeError, "Export and delete uploaded files first"):
                migration.downgrade()
            operations.drop_table.assert_not_called()
            self.assertEqual([
                str(call.args[0]) for call in operations.get_bind.return_value.execute.call_args_list
            ], [
                "LOCK TABLE audit_legacy_imports IN ACCESS EXCLUSIVE MODE",
                "SELECT count(*) FROM audit_legacy_imports",
            ])


if __name__ == "__main__":
    unittest.main()
