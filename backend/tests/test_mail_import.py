"""Offline tests. Load only allowlisted sources, never app settings or .env.

Run: python -m unittest discover -s /absolute/path/backend/tests -p 'test_mail_import*.py'
The HTTP/PostgreSQL suite imports the synthetic module harness from this file.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import ValidationError


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent, _, leaf = name.rpartition(".")
    if parent in sys.modules:
        setattr(sys.modules[parent], leaf, module)
    return module


schema = load_source("_mail_import_offline_schema", BACKEND / "app/schemas/mail_import.py")


def item_payload(**changes):
    return {
        "source_id": "a" * 64, "kind": "mail", "source_modified_at": NOW.isoformat(),
        "received_at": NOW.isoformat(), "subject": "Synthetic subject",
        "sender_name": "Synthetic sender", "sender_address": "sender@example.invalid",
        "source_is_read": False, **changes,
    }


def sync_payload(items=None, **changes):
    return {
        "protocol_version": 1, "mailbox_id": "b" * 64, "mailbox_label": "Synthetic Inbox",
        "source_state": "cached", "items": [item_payload()] if items is None else items,
        **changes,
    }


def attachment_payload(data=b"Synthetic file", **changes):
    return {
        "filename": "example.txt", "content_type": "text/plain",
        "data_base64": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(), **changes,
    }


@contextmanager
def isolated_app():
    """Replace the entire app namespace; only our four source modules are loaded."""
    from sqlalchemy import Boolean, Integer, String
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.orm import DeclarativeBase, mapped_column

    class Base(DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        id = mapped_column(UUID(as_uuid=True), primary_key=True)
        full_name = mapped_column(String(255), nullable=False)
        is_active = mapped_column(Boolean, nullable=False, default=True)
        auth_version = mapped_column(Integer, nullable=False, default=0)

    modules = {}
    for name in ("app", "app.models", "app.schemas", "app.services", "app.api", "app.api.routes"):
        module = ModuleType(name)
        module.__path__ = []
        modules[name] = module
    modules["app.models"].Base = Base
    modules["app.models.user"] = ModuleType("app.models.user")
    modules["app.models.user"].User = User
    deps = modules["app.api.deps"] = ModuleType("app.api.deps")

    async def missing_dependency():
        raise AssertionError("Test dependency override required")

    async def missing_user():
        raise AssertionError("Test actor override required")

    deps.get_db = missing_dependency
    deps.get_current_user = missing_user
    # Remove even preloaded app.config; no search path means imports fail closed.
    previous = {name: value for name, value in sys.modules.copy().items() if name == "app" or name.startswith("app.")}
    for name in previous:
        del sys.modules[name]
    sys.modules.update(modules)
    try:
        models = load_source("app.models.mail_import", BACKEND / "app/models/mail_import.py")
        schemas = load_source("app.schemas.mail_import", BACKEND / "app/schemas/mail_import.py")
        service = load_source("app.services.mail_import", BACKEND / "app/services/mail_import.py")
        routes = load_source("app.api.routes.mail_import", BACKEND / "app/api/routes/mail_import.py")
        yield SimpleNamespace(Base=Base, User=User, models=models, schema=schemas, service=service, routes=routes, deps=deps)
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(previous)


def require_dependencies(case):
    missing = [name for name in ("fastapi", "sqlalchemy", "httpx") if importlib.util.find_spec(name) is None]
    if missing:
        case.skipTest("Offline environment lacks: " + ", ".join(missing))


class SchemaTests(unittest.TestCase):
    def test_defaults_and_explicit_body_grant(self):
        self.assertFalse(schema.DeviceCreate(name="Laptop").include_body)
        self.assertFalse(schema.DeviceCreate(name="Laptop").include_attachments)
        self.assertTrue(schema.DeviceCreate(name="Laptop", include_body=True).include_body)
        request = schema.SyncRequest(**sync_payload(items=[]))
        self.assertTrue(request.scan_complete)
        self.assertEqual(request.skipped_items, 0)
        self.assertTrue(schema.ItemReadRequest().is_read)

    def test_owner_and_other_extra_fields_are_forbidden(self):
        for model, payload in (
            (schema.DeviceCreate, {"name": "Laptop", "owner_id": str(uuid4())}),
            (schema.PairRequest, {"pairing_code": "x" * 43, "owner_id": str(uuid4())}),
            (schema.ImportedItemInput, item_payload(html="forbidden")),
            (schema.SyncRequest, sync_payload(owner_id=str(uuid4()))),
            (schema.EmptyRequest, {"include_body": True}),
            (schema.ItemReadRequest, {"source_is_read": True}),
        ):
            with self.subTest(model=model.__name__), self.assertRaises(ValidationError):
                model(**payload)

    def test_dates_require_timezone_and_normalize(self):
        for field in ("received_at", "source_modified_at", "starts_at", "ends_at"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                schema.ImportedItemInput(**item_payload(**{field: "2026-11-16T12:00:00"}))
        item = schema.ImportedItemInput(**item_payload(source_modified_at="2026-11-16T15:00:00+03:00"))
        self.assertEqual(item.source_modified_at, NOW)

    def test_schedule_is_paired_and_ordered(self):
        for changes in (
            {"starts_at": NOW.isoformat()}, {"ends_at": NOW.isoformat()},
            {"starts_at": NOW.isoformat(), "ends_at": (NOW - timedelta(hours=1)).isoformat()},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                schema.ImportedItemInput(**item_payload(kind="meeting", **changes))
        schema.ImportedItemInput(**item_payload(kind="meeting", starts_at=NOW, ends_at=NOW + timedelta(hours=1)))

    def test_lengths_counts_hashes_and_scan_bounds(self):
        for changes in (
            {"subject": "s" * 1001}, {"body_text": "s" * 2_000_001}, {"body_html": "s" * 2_000_001},
            {"to_recipients": "s" * 20001}, {"cc_recipients": "s" * 20001},
            {"sender_name": "s" * 301}, {"sender_address": "s" * 321},
            {"location": "s" * 1001}, {"source_id": "g" * 64},
            {"meeting_key": "a" * 63}, {"subject": "nul\x00text"}, {"subject": "\ud800"},
        ):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                schema.ImportedItemInput(**item_payload(**changes))
        self.assertEqual(schema.ImportedItemInput(**item_payload(source_id="A" * 64)).source_id, "a" * 64)
        schema.SyncRequest(**sync_payload(items=[item_payload()] * 50, scan_complete=False, skipped_items=5000))
        for changes in (
            {"items": [item_payload()] * 51}, {"skipped_items": -1}, {"skipped_items": 5001},
            {"skipped_items": True}, {"skipped_items": "1"}, {"scan_complete": "false"},
            {"skipped_items": 1, "scan_complete": True},
            {"protocol_version": True}, {"protocol_version": 1.0}, {"protocol_version": 2},
        ):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                schema.SyncRequest(**sync_payload(**changes))

    def test_attachment_checksum_encoding_metadata_and_count(self):
        for changes in (
            {"data_base64": "not-base64"}, {"sha256": "0" * 64},
            {"filename": "x" * 256}, {"content_type": "x" * 201},
            {"content_id": "x" * 501}, {"is_inline": "true"}, {"extra": "forbidden"},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(ValidationError):
                schema.AttachmentInput(**attachment_payload(**changes))
        attachment = schema.AttachmentInput(**attachment_payload())
        self.assertEqual(attachment.decoded_data, b"Synthetic file")
        self.assertNotIn("data_base64", repr(attachment))
        self.assertNotIn("decoded_data", attachment.model_dump())
        schema.ImportedItemInput(**item_payload(attachments=[attachment_payload(b"")] * 100))
        with self.assertRaises(ValidationError):
            schema.ImportedItemInput(**item_payload(attachments=[attachment_payload(b"")] * 101))

    def test_actual_file_and_item_byte_boundaries(self):
        maximum = attachment_payload(b"x" * schema.MAX_ATTACHMENT_BYTES)
        schema.AttachmentInput(**maximum)
        schema.ImportedItemInput(**item_payload(attachments=[maximum, maximum]))
        with self.assertRaises(ValidationError):
            schema.ImportedItemInput(**item_payload(attachments=[maximum, maximum, attachment_payload(b"x")]))
        with self.assertRaises(ValidationError):
            schema.AttachmentInput(**attachment_payload(b"x" * (schema.MAX_ATTACHMENT_BYTES + 1)))

    def test_code_is_redacted_in_schema_repr_and_public_models_exclude_hashes(self):
        code = "x" * 43
        self.assertNotIn(code, repr(schema.PairRequest(pairing_code=code)))
        for model in (schema.DeviceRead, schema.ImportedItemRead):
            for name in model.model_fields:
                self.assertNotIn("hash", name)
                self.assertNotIn("secret", name)
                self.assertNotIn("pairing", name)
                self.assertNotEqual(name, "owner_id")


class DomainTests(unittest.TestCase):
    def setUp(self):
        require_dependencies(self)
        self.context = isolated_app()
        self.app = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.service = self.app.service

    def item(self, **changes):
        return self.app.schema.ImportedItemInput(**item_payload(**changes))

    def row(self):
        item = self.item()
        return self.app.models.MailImportItem(
            **item.model_dump(exclude={"attachments"}), semantic_hash=self.service.semantic_hash(item),
            content_byte_length=self.service.content_size(item),
            body_captured=False, attachments_captured=False,
            is_read=True, updated_at=NOW, created_at=NOW,
        )

    def test_hash_ignores_source_read_and_version_but_not_content(self):
        base = self.service.semantic_hash(self.item())
        self.assertEqual(base, self.service.semantic_hash(self.item(
            source_is_read=True, source_modified_at=NOW + timedelta(seconds=1),
        )))
        self.assertNotEqual(base, self.service.semantic_hash(self.item(subject="Changed")))
        self.assertEqual(base, self.service.semantic_hash(self.item(received_at="2026-11-16T15:00:00+03:00")))

    def test_duplicate_stale_and_read_only_change_preserve_read_state(self):
        for changes, expected in (
            ({}, "unchanged"), ({"source_is_read": True}, "unchanged"),
            ({"source_modified_at": NOW + timedelta(seconds=1)}, "unchanged"),
            ({"source_modified_at": NOW - timedelta(seconds=1), "subject": "Older"}, "stale"),
        ):
            with self.subTest(expected=expected, changes=changes):
                row, item = self.row(), self.item(**changes)
                self.assertEqual(self.service.apply_item(row, item, self.service.semantic_hash(item), NOW), expected)
                self.assertTrue(row.is_read)
                self.assertEqual(row.subject, "Synthetic subject")

    def test_meaningful_new_version_resets_read_and_equal_version_conflicts(self):
        from fastapi import HTTPException
        row = self.row()
        divergent = self.item(subject="Changed")
        with self.assertRaises(HTTPException) as caught:
            self.service.apply_item(row, divergent, self.service.semantic_hash(divergent), NOW)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(row.is_read)
        newer = self.item(subject="Changed", source_modified_at=NOW + timedelta(seconds=1))
        self.assertEqual(self.service.apply_item(row, newer, self.service.semantic_hash(newer), NOW), "updated")
        self.assertFalse(row.is_read)

    def test_public_device_status_and_expiry(self):
        row = self.app.models.MailImportDevice(
            id=uuid4(), name="Laptop", include_body=False, include_attachments=False, owner_auth_version=4,
            pairing_expires_at=NOW + timedelta(minutes=10), created_at=NOW,
            last_skipped_items=0,
        )
        self.assertEqual(self.service.device_read(row, 4, NOW).status, "pending")
        self.assertEqual(self.service.device_read(row, 4, NOW + timedelta(minutes=10)).status, "expired")
        row.paired_at, row.expires_at = NOW, NOW + timedelta(days=365)
        self.assertEqual(self.service.device_read(row, 4, NOW).status, "active")
        self.assertEqual(self.service.device_read(row, 5, NOW).status, "revoked")
        row.revoked_at = NOW
        self.assertEqual(self.service.device_read(row, 4, NOW).status, "revoked")

    def test_hash_domains_and_signed_advisory_ids(self):
        self.assertNotEqual(self.service.digest("x" * 43, "pair"), self.service.digest("x" * 43, "device"))
        owner = uuid4()
        self.assertNotEqual(self.service.advisory_id(owner), self.service.advisory_id(owner, "a" * 64))
        self.assertTrue(-(2 ** 63) <= self.service.advisory_id(owner) < 2 ** 63)

    def test_persistence_is_only_three_new_tables_and_no_side_effect_imports(self):
        self.assertEqual(set(self.app.Base.metadata.tables), {"users", "mail_import_devices", "mail_import_items", "mail_import_attachments"})
        import ast
        tree = ast.parse((BACKEND / "app/services/mail_import.py").read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name and name.startswith("app.services") for name in imports))
        self.assertNotIn("app.config", sys.modules)
        with self.assertRaises(ModuleNotFoundError):
            __import__("app.config")

    def test_semantic_hash_covers_attachment_metadata_but_not_base64_spelling(self):
        payload = attachment_payload(b"x")
        first = self.item(attachments=[payload])
        # Nonzero padding bits decode to the same bytes; semantic identity is SHA + metadata.
        second = self.item(attachments=[{**payload, "data_base64": "eB=="}])
        self.assertEqual(self.service.semantic_hash(first), self.service.semantic_hash(second))
        renamed = self.item(attachments=[{**payload, "filename": "renamed.txt"}])
        self.assertNotEqual(self.service.semantic_hash(first), self.service.semantic_hash(renamed))
        self.assertNotEqual(self.service.semantic_hash(first), self.service.semantic_hash(self.item(attachments=[attachment_payload(b"y")])))

    def test_content_size_counts_utf8_text_html_recipients_and_decoded_files(self):
        item = self.item(
            body_text="\u044f", body_html="<b>\U0001f600</b>", to_recipients="to", cc_recipients="cc",
            attachments=[attachment_payload(b"123")],
        )
        self.assertEqual(self.service.content_size(item), 2 + 11 + 2 + 2 + 3)
        self.assertEqual(self.service.MAX_CONTENT_BYTES_PER_USER, 2 * 1024 * 1024 * 1024)

    def test_equal_version_enrichment_preserves_read_and_captured_groups(self):
        from fastapi import HTTPException
        row = self.row()
        enriched = self.item(body_text="Captured", attachments=[attachment_payload(b"file")])
        result = self.service.apply_item(
            row, enriched, self.service.semantic_hash(enriched), NOW,
            include_body=True, include_attachments=True,
        )
        self.assertEqual(result, "updated")
        self.assertTrue(row.is_read)
        self.assertTrue(row.body_captured)
        self.assertTrue(row.attachments_captured)
        changed = self.item(body_text="Different", attachments=[attachment_payload(b"file")])
        with self.assertRaises(HTTPException) as caught:
            self.service.apply_item(row, changed, self.service.semantic_hash(changed), NOW, include_body=True, include_attachments=True)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(row.body_text, "Captured")

    def test_enrichment_cannot_change_other_metadata(self):
        row = self.row()
        for changes in ({"subject": "Changed"}, {"to_recipients": "new@example.invalid"}, {"kind": "meeting"}):
            with self.subTest(fields=list(changes)):
                candidate = self.item(body_text="Enrichment", **changes)
                self.assertFalse(self.service.can_enrich(row, candidate, include_body=True, include_attachments=True))

    def test_same_hash_upgrade_captures_empty_groups_but_stale_does_not(self):
        row = self.row()
        stale = self.item(source_modified_at=NOW - timedelta(seconds=1), body_text="Old")
        self.assertEqual(self.service.apply_item(
            row, stale, self.service.semantic_hash(stale), NOW, include_body=True, include_attachments=True,
        ), "stale")
        self.assertFalse(row.body_captured)
        self.assertFalse(row.attachments_captured)
        item = self.item()
        self.assertEqual(self.service.apply_item(
            row, item, self.service.semantic_hash(item), NOW, include_body=True, include_attachments=True,
        ), "unchanged")
        self.assertTrue(row.body_captured)
        self.assertTrue(row.attachments_captured)
        self.assertTrue(row.is_read)


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        require_dependencies(self)
        self.context = isolated_app()
        self.app = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    async def test_commit_failure_is_not_success_and_rolls_back(self):
        from fastapi import HTTPException
        from sqlalchemy.exc import SQLAlchemyError
        db = SimpleNamespace(commit=AsyncMock(side_effect=SQLAlchemyError("private diagnostics")), rollback=AsyncMock())
        with self.assertRaises(HTTPException) as caught:
            async with self.app.routes.committed(db):
                pass
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("private", str(caught.exception.detail))
        db.rollback.assert_awaited_once()

    async def test_failed_item_rolls_back_and_never_commits(self):
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with self.assertRaises(ValueError):
            async with self.app.routes.committed(db):
                raise ValueError("synthetic item failure")
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
