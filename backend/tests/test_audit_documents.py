"""Unit tests for immutable audit document validation."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.services.audit_documents import (
    finalize_pending_audit_document,
    prepare_audit_document,
    prepare_audit_document_bytes,
    stage_audit_document_file,
)


def office_file(prefix: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{prefix}/document.xml", "<document />")
    return buffer.getvalue()


class AuditDocumentValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_pdf_and_calculates_hash(self):
        upload = UploadFile(filename="technical-spec.pdf", file=BytesIO(b"%PDF-1.7\ncontent"))
        prepared = await prepare_audit_document(upload)
        self.assertEqual(prepared.extension, ".pdf")
        self.assertEqual(prepared.content_type, "application/pdf")
        self.assertEqual(len(prepared.sha256), 64)

    async def test_accepts_real_docx_package(self):
        upload = UploadFile(filename="technical-spec.docx", file=BytesIO(office_file("word")))
        prepared = await prepare_audit_document(upload)
        self.assertEqual(prepared.extension, ".docx")

    async def test_rejects_renamed_office_file(self):
        upload = UploadFile(filename="technical-spec.docx", file=BytesIO(office_file("xl")))
        with self.assertRaises(HTTPException) as context:
            await prepare_audit_document(upload)
        self.assertEqual(context.exception.status_code, 400)

    async def test_rejects_unsupported_extension(self):
        upload = UploadFile(filename="technical-spec.exe", file=BytesIO(b"MZ"))
        with self.assertRaises(HTTPException) as context:
            await prepare_audit_document(upload)
        self.assertEqual(context.exception.status_code, 400)

    def test_staged_file_is_hidden_until_finalized(self):
        prepared = prepare_audit_document_bytes("technical-spec.pdf", b"%PDF-1.7\ncontent")
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            staged = stage_audit_document_file(uuid4(), prepared)

            self.assertTrue(staged.pending_path.exists())
            self.assertFalse(staged.final_path.exists())
            self.assertEqual(staged.pending_path.read_bytes(), prepared.data)
            self.assertTrue(str(staged.pending_path).startswith(str(Path(temp_dir).resolve())))

            self.assertTrue(finalize_pending_audit_document(staged.stored_filename))

            self.assertFalse(staged.pending_path.exists())
            self.assertTrue(staged.final_path.exists())
            self.assertEqual(staged.final_path.read_bytes(), prepared.data)
            self.assertTrue(finalize_pending_audit_document(staged.stored_filename))


if __name__ == "__main__":
    unittest.main()
