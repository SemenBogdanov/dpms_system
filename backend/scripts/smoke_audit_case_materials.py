"""Local-only API smoke for audit materials and archive-first deletion."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.audit import AuditCase, AuditDocument
from app.models.user import League, User, UserRole
from app.services.audit_documents import audit_document_path, remove_audit_case_files


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Audit material smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Audit material smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = raw_body
    request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        request_headers["Content-Type"] = "application/json"
    api_request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(api_request, timeout=20) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, json.loads(payload) if payload else None


def multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"dpms-audit-material-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/pdf\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def expect(status: int, expected: int, payload: Any, label: str) -> Any:
    if status != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {status}: {payload}")
    return payload


async def run() -> None:
    ensure_safe_target()
    marker = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    user_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    stored_path: Path | None = None
    try:
        async with AsyncSessionLocal() as db:
            admin = User(
                full_name="Audit material smoke administrator",
                email=f"audit-material-smoke-{marker}@example.invalid",
                league=League.A,
                role=UserRole.admin,
                mpw=0,
                audit_enabled=True,
                is_active=True,
            )
            db.add(admin)
            await db.commit()
            user_id = admin.id
            token = create_access_token({"sub": str(admin.id), "ver": admin.auth_version})

        status, created = request(
            "POST",
            "/api/audit/cases",
            token,
            json_body={
                "title": "Smoke audit material case",
                "digital_product": "SMOKE",
                "contract_reference": f"SMOKE-{marker}",
            },
        )
        created = expect(status, 201, created, "create audit case")
        case_id = uuid.UUID(created["id"])
        case_number = created["case_number"]

        body, content_type = multipart(
            {"kind": "protocol", "display_name": "Smoke protocol"},
            "commission-protocol.pdf",
            b"%PDF-1.7\nsmoke protocol",
        )
        status, uploaded = request(
            "POST",
            f"/api/audit/cases/{case_id}/documents",
            token,
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        uploaded = expect(status, 201, uploaded, "attach material")
        assert uploaded[0]["kind"] == "protocol"
        assert uploaded[0]["original_filename"] == "commission-protocol.pdf"

        async with AsyncSessionLocal() as db:
            document = await db.scalar(select(AuditDocument).where(AuditDocument.case_id == case_id))
            assert document is not None
            stored_path = audit_document_path(document)
            assert stored_path.is_file()

        status, _ = request(
            "DELETE",
            f"/api/audit/cases/{case_id}",
            token,
            json_body={"confirmation_code": case_number},
        )
        assert status == 409, status

        status, _ = request(
            "PATCH",
            f"/api/audit/cases/{case_id}",
            token,
            json_body={"status": "archived"},
        )
        assert status == 200, status
        status, _ = request(
            "DELETE",
            f"/api/audit/cases/{case_id}",
            token,
            json_body={"confirmation_code": "AUD-WRONG"},
        )
        assert status == 422, status
        status, deleted_payload = request(
            "DELETE",
            f"/api/audit/cases/{case_id}",
            token,
            json_body={"confirmation_code": case_number, "reason": "smoke cleanup"},
        )
        deleted_payload = expect(status, 200, deleted_payload, "delete archived case")
        assert deleted_payload["deleted_documents_count"] == 1
        assert stored_path is not None and not stored_path.exists()

        async with AsyncSessionLocal() as db:
            assert await db.get(AuditCase, case_id) is None
            deletion_event = await db.scalar(
                select(ActivityEvent).where(
                    ActivityEvent.actor_id == user_id,
                    ActivityEvent.event_type == "audit_case_deleted",
                )
            )
            assert deletion_event is not None
        case_id = None
        print("Audit material smoke OK: attach, immutable metadata, archive guard, delete confirmation, file cleanup, tombstone")
    finally:
        async with AsyncSessionLocal() as db:
            if case_id is not None:
                documents = list(await db.scalars(select(AuditDocument).where(AuditDocument.case_id == case_id)))
                await db.execute(delete(AuditCase).where(AuditCase.id == case_id))
                await db.commit()
                remove_audit_case_files(case_id, [document.stored_filename for document in documents])
            if user_id is not None:
                await db.execute(delete(ActivityEvent).where(ActivityEvent.actor_id == user_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()


if __name__ == "__main__":
    asyncio.run(run())
