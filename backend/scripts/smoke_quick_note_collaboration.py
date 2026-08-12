"""Transactional local smoke for quick-note realtime collaboration v1.

Covers:
- recipient (active share) cannot PATCH note content (owner-only);
- recipient cannot delete the note or attach it to their own project;
- owner save and recipient comment propagate through real WebSockets;
- stale base_revision => HTTP 409 with clear Russian detail;
- successful content patch increments revision exactly once;
- revision guard blocks a second concurrent patch on the stale base;
- access revocation reaches only the recipient and closes their channel.

No persistent test data: all created users/notes/shares are removed at the end.
Refuses non-local API host and non-local database, consistent with existing
smoke scripts.

Requires a running DPMS API at SMOKE_API_BASE (default 127.0.0.1:8000) that has
applied migration 055.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlparse

import websockets
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.user import League, User, UserRole


API_BASE = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
WS_BASE = API_BASE.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
SAFE_API_HOSTS = {"127.0.0.1", "localhost", "backend", "frontend"}
SAFE_DATABASE_HOSTS = {"127.0.0.1", "localhost", "db"}


def ensure_safe_target() -> None:
    if (urlparse(API_BASE).hostname or "") not in SAFE_API_HOSTS:
        raise RuntimeError("Quick-note collaboration smoke refuses a non-local API")
    if (make_url(settings.DATABASE_URL).host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Quick-note collaboration smoke refuses a non-local database")


def request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None
    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    api_request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(api_request, timeout=15) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, (json.loads(payload) if payload else None)


async def async_request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Run blocking urllib outside the WebSocket client's event loop."""
    return await asyncio.to_thread(
        request,
        method,
        path,
        token,
        json_body=json_body,
    )


def expect(status: int, expected: int, payload: Any, label: str) -> Any:
    if status != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {status}: {payload}")
    return payload


async def receive_event(socket, expected_type: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Read until one event type appears, tolerating presence/pong traffic."""
    deadline = asyncio.get_running_loop().time() + timeout
    seen: list[str] = []
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(f"WebSocket event {expected_type!r} not received; seen={seen}")
        raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
        event = json.loads(raw)
        event_type = event.get("type")
        seen.append(str(event_type))
        if event_type == expected_type:
            return event


async def open_live_socket(note_id: uuid.UUID, token: str):
    socket = await websockets.connect(f"{WS_BASE}/api/quick-notes/{note_id}/live")
    await socket.send(json.dumps({"type": "auth", "token": token}))
    ready = await receive_event(socket, "ready")
    assert ready["note_id"] == str(note_id), f"unexpected ready payload: {ready}"
    return socket


async def create_fixtures() -> tuple[dict[str, uuid.UUID], uuid.UUID, dict[str, str]]:
    marker = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        owner = User(
            full_name="Note smoke owner",
            email=f"note-smoke-owner-{marker}@example.invalid",
            league=League.B,
            role=UserRole.executor,
            mpw=0,
            is_active=True,
            task_workspace_enabled=True,
        )
        recipient = User(
            full_name="Note smoke recipient",
            email=f"note-smoke-recipient-{marker}@example.invalid",
            league=League.B,
            role=UserRole.executor,
            mpw=0,
            is_active=True,
            task_workspace_enabled=True,
        )
        db.add_all([owner, recipient])
        await db.flush()
        contact = Contact(
            requester_id=owner.id,
            recipient_id=recipient.id,
            status="accepted",
        )
        db.add(contact)
        await db.flush()
        note = QuickNote(
            owner_id=owner.id,
            title="Smoke note",
            body="Начальный текст заметки",
            context=None,
            status="draft",
            tags=["smoke"],
        )
        db.add(note)
        await db.commit()
        return (
            {"owner": owner.id, "recipient": recipient.id},
            note.id,
            {
                "owner": create_access_token({"sub": str(owner.id), "ver": owner.auth_version}),
                "recipient": create_access_token({"sub": str(recipient.id), "ver": recipient.auth_version}),
            },
        )


async def cleanup(user_ids: dict[str, uuid.UUID], note_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        if note_id:
            await db.execute(
                delete(QuickNoteAttachment).where(QuickNoteAttachment.note_id == note_id)
            )
            await db.execute(delete(QuickNoteComment).where(QuickNoteComment.note_id == note_id))
            await db.execute(delete(QuickNoteShare).where(QuickNoteShare.note_id == note_id))
            await db.execute(delete(QuickNote).where(QuickNote.id == note_id))
        ids = list(user_ids.values())
        if ids:
            await db.execute(delete(Contact).where(Contact.requester_id.in_(ids)))
            await db.execute(Contact.__table__.delete().where(Contact.recipient_id.in_(ids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
        await db.commit()


async def assert_permissions_and_revision(
    tokens: dict[str, str],
    user_ids: dict[str, uuid.UUID],
    note_id: uuid.UUID,
) -> None:
    note_path = f"/api/quick-notes/{note_id}"
    share_path = f"{note_path}/shares"

    status, data = request("GET", note_path, tokens["owner"])
    expect(status, 200, data, "owner reads note")
    base_revision = data["revision"]
    assert base_revision == 1, f"initial revision must be 1, got {base_revision}"

    status, shares = request(
        "POST", share_path, tokens["owner"],
        json_body={"recipient_ids": [str(user_ids["recipient"])]},
    )
    expect(status, 200, shares, "owner shares note")
    assert len(shares) == 1, f"expected one share, got {shares}"
    share_id = shares[0]["id"]

    status, entity = request(
        "POST",
        "/api/work-entities",
        tokens["recipient"],
        json_body={
            "entity_type": "project",
            "title": "Recipient smoke project",
            "status": "draft",
            "visibility": "private",
            "planning_mode": "free",
        },
    )
    expect(status, 201, entity, "recipient creates own project")

    status, data = request(
        "POST",
        f"/api/work-entities/{entity['id']}/links",
        tokens["recipient"],
        json_body={
            "target_type": "quick_note",
            "target_id": str(note_id),
            "relation_type": "contains",
        },
    )
    expect(status, 403, data, "recipient cannot change note project links")

    owner_socket = await open_live_socket(note_id, tokens["owner"])
    recipient_socket = await open_live_socket(note_id, tokens["recipient"])
    try:
        status, data = await async_request(
            "PATCH", note_path, tokens["recipient"],
            json_body={"base_revision": base_revision, "body": "Попытка получателя"},
        )
        assert status in (403, 404), (
            f"recipient PATCH content must be rejected (403/404), got {status}: {data}"
        )

        status, data = await async_request("DELETE", note_path, tokens["recipient"])
        expect(status, 404, data, "recipient cannot delete shared note")

        status, data = await async_request(
            "PATCH", note_path, tokens["owner"],
            json_body={"base_revision": 999, "body": "Новый текст"},
        )
        expect(status, 409, data, "stale base_revision => 409")
        assert isinstance(data, dict) and "detail" in data, "409 must include detail"
        detail = data["detail"]
        assert "устарел" in detail.lower(), f"409 detail must be clear Russian conflict: {detail!r}"

        status, data = await async_request(
            "PATCH", note_path, tokens["owner"],
            json_body={"base_revision": base_revision, "body": "Обновлённый текст"},
        )
        expect(status, 200, data, "owner fresh patch")
        assert data["revision"] == base_revision + 1, (
            f"revision must increment once to {base_revision + 1}, got {data['revision']}"
        )
        assert data["body"] == "Обновлённый текст", f"body must be updated, got {data['body']!r}"
        owner_event = await receive_event(owner_socket, "note.updated")
        recipient_event = await receive_event(recipient_socket, "note.updated")
        assert owner_event["revision"] == data["revision"]
        assert recipient_event["revision"] == data["revision"]

        status, comment = await async_request(
            "POST",
            f"{note_path}/comments",
            tokens["recipient"],
            json_body={"body": "Комментарий получателя", "parent_id": None},
        )
        expect(status, 200, comment, "recipient comments")
        comment_event = await receive_event(owner_socket, "comment.created")
        assert comment_event["comment_id"] == comment["id"]

        status, data = await async_request(
            "PATCH", note_path, tokens["owner"],
            json_body={"base_revision": base_revision, "body": "Конкурентная правка"},
        )
        expect(status, 409, data, "second patch on stale base => 409")

        status, data = await async_request(
            "PATCH", note_path, tokens["owner"],
            json_body={"base_revision": base_revision + 1, "status": "processed"},
        )
        expect(status, 200, data, "owner status-only patch")
        assert data["revision"] == base_revision + 2, (
            f"status patch must increment revision, got {data['revision']}"
        )
        await receive_event(recipient_socket, "note.updated")

        status, data = await async_request("GET", note_path, tokens["recipient"])
        expect(status, 200, data, "recipient reads shared note")

        status, revoked = await async_request(
            "DELETE", f"/api/quick-notes/shares/{share_id}", tokens["owner"]
        )
        expect(status, 200, revoked, "owner revokes recipient")
        revoked_event = await receive_event(recipient_socket, "access.revoked")
        assert revoked_event["recipient_id"] == str(user_ids["recipient"])

        status, denied = await async_request("GET", note_path, tokens["recipient"])
        expect(status, 404, denied, "revoked recipient loses read access")

        status, deleted = await async_request("DELETE", note_path, tokens["owner"])
        expect(status, 200, deleted, "owner deletes note")
        await receive_event(owner_socket, "note.deleted")
    finally:
        await owner_socket.close()
        await recipient_socket.close()


async def main() -> None:
    ensure_safe_target()
    user_ids, note_id, tokens = await create_fixtures()
    try:
        await assert_permissions_and_revision(tokens, user_ids, note_id)
        print("SMOKE OK quick-note collaboration v1")
    finally:
        await cleanup(user_ids, note_id)


if __name__ == "__main__":
    asyncio.run(main())
