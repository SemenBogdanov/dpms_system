"""Transactional local smoke for versioned personal-task artifacts."""
from __future__ import annotations

import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlparse
from zipfile import ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.personal_task import PersonalTask, PersonalTaskEvent
from app.models.personal_task_artifact import (
    PersonalTaskArtifact,
    PersonalTaskArtifactVersion,
)
from app.models.user import League, User, UserRole
from app.services.attachments import read_attachment_upload, stored_attachment_path


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Personal artifact smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Personal artifact smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
    parse_json: bool = True,
) -> tuple[int, Any, dict[str, str]]:
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
        with urllib.request.urlopen(api_request, timeout=15) as response:
            payload = response.read()
            value = json.loads(payload) if parse_json and payload else payload
            return response.status, value, {
                key.lower(): item for key, item in response.headers.items()
            }
    except urllib.error.HTTPError as error:
        payload = error.read()
        value = json.loads(payload) if parse_json and payload else payload
        return error.code, value, {
            key.lower(): item for key, item in error.headers.items()
        }


def multipart(
    fields: dict[str, str],
    *,
    filename: str | None = None,
    content: bytes | None = None,
) -> tuple[bytes, str]:
    boundary = f"dpms-smoke-{uuid.uuid4().hex}"
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
    if filename is not None and content is not None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="file"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: application/octet-stream\r\n\r\n",
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def expect(status: int, expected: int, payload: Any, label: str) -> Any:
    if status != expected:
        raise AssertionError(
            f"{label}: expected HTTP {expected}, got {status}: {payload}"
        )
    return payload


async def create_fixtures() -> tuple[list[uuid.UUID], uuid.UUID, dict[str, str]]:
    marker = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        owner = User(
            full_name="Personal artifact smoke owner",
            email=f"personal-artifact-owner-{marker}@example.invalid",
            league=League.A,
            role=UserRole.executor,
            mpw=0,
            task_workspace_enabled=True,
            is_active=True,
        )
        outsider = User(
            full_name="Personal artifact smoke outsider",
            email=f"personal-artifact-outsider-{marker}@example.invalid",
            league=League.C,
            role=UserRole.admin,
            mpw=0,
            task_workspace_enabled=True,
            is_active=True,
        )
        db.add_all([owner, outsider])
        await db.flush()
        task = PersonalTask(
            owner_id=owner.id,
            title="Personal artifact smoke task",
            status="in_progress",
            priority="medium",
            category="work",
            tags=[],
        )
        db.add(task)
        await db.commit()
        return (
            [owner.id, outsider.id],
            task.id,
            {
                "owner": create_access_token(
                    {"sub": str(owner.id), "ver": owner.auth_version}
                ),
                "outsider": create_access_token(
                    {"sub": str(outsider.id), "ver": outsider.auth_version}
                ),
            },
        )


async def stored_files(task_id: uuid.UUID) -> list[Path]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(PersonalTaskArtifactVersion.stored_filename)
                .join(
                    PersonalTaskArtifact,
                    PersonalTaskArtifactVersion.artifact_id
                    == PersonalTaskArtifact.id,
                )
                .where(
                    PersonalTaskArtifact.task_id == task_id,
                    PersonalTaskArtifactVersion.stored_filename.is_not(None),
                )
            )
        ).scalars()
        paths: list[Path] = []
        for value in rows:
            if not value:
                continue
            try:
                paths.append(stored_attachment_path(value))
            except HTTPException:
                continue
        return paths


async def set_stored_filename(version_id: uuid.UUID, value: str) -> None:
    async with AsyncSessionLocal() as db:
        version = await db.get(PersonalTaskArtifactVersion, version_id)
        assert version is not None
        version.stored_filename = value
        await db.commit()


async def version_storage_path(version_id: uuid.UUID) -> Path:
    async with AsyncSessionLocal() as db:
        version = await db.get(PersonalTaskArtifactVersion, version_id)
        assert version is not None and version.stored_filename
        return stored_attachment_path(version.stored_filename)


async def cleanup(user_ids: list[uuid.UUID], task_id: uuid.UUID | None) -> None:
    paths = await stored_files(task_id) if task_id else []
    async with AsyncSessionLocal() as db:
        if task_id:
            artifact_ids = select(PersonalTaskArtifact.id).where(
                PersonalTaskArtifact.task_id == task_id
            )
            await db.execute(
                delete(PersonalTaskArtifactVersion).where(
                    PersonalTaskArtifactVersion.artifact_id.in_(artifact_ids)
                )
            )
            await db.execute(
                delete(PersonalTaskArtifact).where(
                    PersonalTaskArtifact.task_id == task_id
                )
            )
            await db.execute(
                delete(PersonalTaskEvent).where(PersonalTaskEvent.task_id == task_id)
            )
            await db.execute(delete(PersonalTask).where(PersonalTask.id == task_id))
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()
    for path in paths:
        path.unlink(missing_ok=True)


def ooxml_fixture(prefix: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(f"{prefix}fixture.xml", "<fixture />")
    return buffer.getvalue()


async def assert_shared_file_policy() -> None:
    for filename, prefix, expected_type in (
        (
            "brief.docx",
            "word/",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "plan.xlsx",
            "xl/",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "slides.pptx",
            "ppt/",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ):
        upload = UploadFile(file=BytesIO(ooxml_fixture(prefix)), filename=filename)
        _, content_type, _, _ = await read_attachment_upload(upload)
        assert content_type == expected_type
    fake_docx = UploadFile(file=BytesIO(ooxml_fixture("xl/")), filename="fake.docx")
    try:
        await read_attachment_upload(fake_docx)
    except HTTPException as error:
        assert error.status_code == 400
    else:
        raise AssertionError("OOXML package spoof was accepted")


async def run() -> None:
    ensure_safe_target()
    await assert_shared_file_policy()
    user_ids: list[uuid.UUID] = []
    task_id: uuid.UUID | None = None
    try:
        user_ids, task_id, tokens = await create_fixtures()
        pdf_v1 = b"%PDF-1.7\nDPMS artifact version one\n%%EOF\n"
        body, content_type = multipart(
            {
                "artifact_type": "document",
                "title": "Project brief",
                "description": "Source document",
                "change_note": "Initial version",
            },
            filename="brief.pdf",
            content=pdf_v1,
        )
        status, document, _ = request(
            "POST",
            f"/api/personal-tasks/{task_id}/artifacts",
            tokens["owner"],
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        document = expect(status, 201, document, "create document")
        assert document["current_version"] == 1
        assert document["versions"][0]["sha256"]
        document_id = document["id"]
        version_one_id = document["versions"][0]["id"]

        status, _, _ = request(
            "GET",
            f"/api/personal-tasks/{task_id}/artifacts",
            tokens["outsider"],
        )
        assert status == 404, status

        status, downloaded, headers = request(
            "GET",
            (
                f"/api/personal-tasks/{task_id}/artifacts/{document_id}"
                f"/versions/{version_one_id}/content"
            ),
            tokens["owner"],
            parse_json=False,
        )
        expect(status, 200, downloaded, "download v1")
        assert downloaded == pdf_v1
        assert headers.get("x-content-type-options") == "nosniff"
        assert "attachment" in headers.get("content-disposition", "").lower()

        pdf_v2 = b"%PDF-1.7\nDPMS artifact version two\n%%EOF\n"
        body, content_type = multipart(
            {"change_note": "Accepted edits"},
            filename="brief-v2.pdf",
            content=pdf_v2,
        )
        status, document, _ = request(
            "POST",
            f"/api/personal-tasks/{task_id}/artifacts/{document_id}/versions",
            tokens["owner"],
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        document = expect(status, 201, document, "add v2")
        assert document["current_version"] == 2
        assert [item["version_number"] for item in document["versions"]] == [2, 1]

        body, content_type = multipart(
            {
                "artifact_type": "link",
                "title": "Published result",
                "url": "https://example.com/result",
            }
        )
        status, link, _ = request(
            "POST",
            f"/api/personal-tasks/{task_id}/artifacts",
            tokens["owner"],
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        link = expect(status, 201, link, "create link")
        assert link["versions"][0]["source_kind"] == "link"
        link_id = link["id"]

        body, content_type = multipart(
            {"artifact_type": "document", "title": "Fake PDF"},
            filename="fake.pdf",
            content=b"<html>not a PDF</html>",
        )
        status, _, _ = request(
            "POST",
            f"/api/personal-tasks/{task_id}/artifacts",
            tokens["owner"],
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        assert status == 400, status

        latest_version = document["versions"][0]
        original_path = await version_storage_path(uuid.UUID(latest_version["id"]))
        relative_original = original_path.relative_to(Path(settings.UPLOAD_DIR).resolve())
        await set_stored_filename(uuid.UUID(latest_version["id"]), "../../etc/passwd")
        try:
            status, _, _ = request(
                "GET",
                (
                    f"/api/personal-tasks/{task_id}/artifacts/{document_id}"
                    f"/versions/{latest_version['id']}/content"
                ),
                tokens["owner"],
                parse_json=False,
            )
            assert status == 404, status
        finally:
            await set_stored_filename(
                uuid.UUID(latest_version["id"]),
                str(relative_original),
            )

        status, document, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}/artifacts/{document_id}",
            tokens["owner"],
            json_body={"status": "archived"},
        )
        expect(status, 200, document, "archive document")
        status, _, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}",
            tokens["owner"],
            json_body={"status": "archived"},
        )
        assert status == 200, status

        status, downloaded, _ = request(
            "GET",
            (
                f"/api/personal-tasks/{task_id}/artifacts/{document_id}"
                f"/versions/{version_one_id}/content"
            ),
            tokens["owner"],
            parse_json=False,
        )
        expect(status, 200, downloaded, "download after task archive")
        body, content_type = multipart(
            {"change_note": "Blocked version"},
            filename="blocked.pdf",
            content=pdf_v2,
        )
        status, _, _ = request(
            "POST",
            f"/api/personal-tasks/{task_id}/artifacts/{document_id}/versions",
            tokens["owner"],
            raw_body=body,
            headers={"Content-Type": content_type},
        )
        assert status == 409, status
        status, _, _ = request(
            "DELETE",
            f"/api/personal-tasks/{task_id}",
            tokens["owner"],
        )
        assert status == 409, status

        status, _, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}/artifacts/{link_id}",
            tokens["owner"],
            json_body={"status": "archived"},
        )
        assert status == 409, status
        status, _, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}",
            tokens["owner"],
            json_body={"status": "in_progress"},
        )
        assert status == 200, status
        status, link, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}/artifacts/{link_id}",
            tokens["owner"],
            json_body={"status": "archived"},
        )
        assert status == 200, status
        status, _, _ = request(
            "PATCH",
            f"/api/personal-tasks/{task_id}",
            tokens["owner"],
            json_body={"status": "archived"},
        )
        assert status == 200, status

        paths_before_delete = await stored_files(task_id)
        for artifact_id in (document_id, link_id):
            status, _, _ = request(
                "DELETE",
                f"/api/personal-tasks/{task_id}/artifacts/{artifact_id}",
                tokens["owner"],
            )
            assert status == 200, status
        assert all(not path.exists() for path in paths_before_delete)

        status, events, _ = request(
            "GET",
            f"/api/personal-tasks/{task_id}/events",
            tokens["owner"],
        )
        expect(status, 200, events, "read audit")
        event_types = {item["event_type"] for item in events}
        assert {
            "artifact_created",
            "artifact_version_added",
            "artifact_archived",
            "artifact_deleted",
        } <= event_types
        serialized_events = json.dumps(events)
        assert "stored_filename" not in serialized_events
        assert "personal-tasks/" not in serialized_events

        status, _, _ = request(
            "DELETE",
            f"/api/personal-tasks/{task_id}",
            tokens["owner"],
        )
        assert status == 200, status
        task_id = None
        print(
            "Personal task artifact smoke OK: owner isolation, signature checks, "
            "safe download, immutable versions, archive read-only behavior, "
            "explicit deletion, file cleanup, and audit privacy"
        )
    finally:
        await cleanup(user_ids, task_id)


if __name__ == "__main__":
    asyncio.run(run())
