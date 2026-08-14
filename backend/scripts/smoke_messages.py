#!/usr/bin/env python3
"""Transactional local smoke test for Messages and attention.

The FastAPI app runs in-process against the configured local PostgreSQL
database. Every application session joins one outer transaction through a
savepoint, so endpoint-level commits remain rollbackable. A fixture-scoped
cleanup pass runs after the rollback as a second line of defense.

This script deliberately bypasses token issuance. A test-only dependency
override authenticates only the three users created inside the transaction;
the authorization checks exercised by the routes remain active.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any, AsyncGenerator, Callable
from urllib.parse import SplitResult, urlsplit

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import Request
from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_user, get_db
from app.database import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.email_outbox import EmailOutbox
from app.models.messages import (
    CommunicationEvent,
    MessagePost,
    MessageThread,
    MessageThreadParticipant,
    UserAttentionItem,
)
from app.models.notification import Notification
from app.models.quick_note import QuickNote
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.user import League, User, UserRole
from app.services.notifications import create_notification


SMOKE_USER_HEADER = "x-dpms-smoke-user"
REQUIRED_TABLES = {
    "users",
    "contacts",
    "quick_notes",
    "quick_note_shares",
    "quick_note_comments",
    "notifications",
    "communication_events",
    "user_attention_items",
    "message_threads",
    "message_thread_participants",
    "message_posts",
    "email_outbox",
}


class SmokeFailure(RuntimeError):
    """A smoke assertion failed."""


class LocalOnlyRefusal(RuntimeError):
    """The configured API or database is not provably local."""


@dataclass
class FixtureState:
    marker: str = field(default_factory=lambda: uuid.uuid4().hex)
    sender_id: uuid.UUID = field(default_factory=uuid.uuid4)
    recipient_id: uuid.UUID = field(default_factory=uuid.uuid4)
    outsider_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source_keys: set[str] = field(default_factory=set)

    @property
    def user_ids(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        return self.sender_id, self.recipient_id, self.outsider_id


@dataclass(frozen=True)
class AsgiResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body)


class LocalAsgiClient:
    """Minimal JSON ASGI client with no test-only third-party dependency."""

    def __init__(self, app: Callable[..., Any], base_url: SplitResult) -> None:
        self.app = app
        self.base_url = base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        user_id: uuid.UUID | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> AsgiResponse:
        target = urlsplit(path)
        if target.scheme or target.netloc:
            raise SmokeFailure("ASGI request paths must be relative")

        base_path = self.base_url.path.rstrip("/")
        request_path = f"{base_path}/{target.path.lstrip('/')}" or "/"
        body = (
            json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            if json_body is not None
            else b""
        )
        headers: list[tuple[bytes, bytes]] = [
            (b"host", self.base_url.netloc.encode("ascii")),
            (b"accept", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if json_body is not None:
            headers.append((b"content-type", b"application/json"))
        if user_id is not None:
            headers.append((SMOKE_USER_HEADER.encode("ascii"), str(user_id).encode("ascii")))

        request_sent = False
        response_status: int | None = None
        response_headers: dict[str, str] = {}
        response_body: list[bytes] = []

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                response_headers.update(
                    {
                        key.decode("latin-1"): value.decode("latin-1")
                        for key, value in message.get("headers", [])
                    }
                )
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": self.base_url.scheme,
            "path": request_path,
            "raw_path": request_path.encode("ascii"),
            "query_string": target.query.encode("ascii"),
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 43123),
            "server": (
                self.base_url.hostname or "127.0.0.1",
                self.base_url.port or 80,
            ),
            "state": {},
        }
        await self.app(scope, receive, send)
        if response_status is None:
            raise SmokeFailure(f"{method.upper()} {path} produced no ASGI response")
        return AsgiResponse(
            status_code=response_status,
            headers=response_headers,
            body=b"".join(response_body),
        )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def assert_local_api_url(value: str) -> SplitResult:
    parsed = urlsplit(value)
    if parsed.scheme != "http":
        raise LocalOnlyRefusal("API URL must use plain HTTP on a local interface")
    if parsed.username or parsed.password:
        raise LocalOnlyRefusal("API URL must not contain credentials")
    if not parsed.hostname or not _is_loopback_host(parsed.hostname):
        raise LocalOnlyRefusal("API host must be localhost or a loopback address")
    if parsed.query or parsed.fragment:
        raise LocalOnlyRefusal("API base URL must not contain a query or fragment")
    return parsed


def assert_local_database(*, allow_compose_db: bool = False) -> None:
    url = engine.url
    if not url.drivername.startswith("postgresql"):
        raise LocalOnlyRefusal("Messages smoke requires a local PostgreSQL database")

    configured_host = url.host
    if configured_host is None:
        query_host = url.query.get("host")
        if isinstance(query_host, tuple):
            query_host = query_host[0] if query_host else None
        configured_host = str(query_host) if query_host else None

    if configured_host and not configured_host.startswith("/"):
        compose_db_allowed = allow_compose_db and configured_host == "db"
        if not _is_loopback_host(configured_host) and not compose_db_allowed:
            raise LocalOnlyRefusal(
                "Database host must be localhost, loopback, a local Unix socket, "
                "or the explicitly approved Compose service 'db'"
            )

    database_name = (url.database or "").lower()
    if not database_name:
        raise LocalOnlyRefusal("Database name is required")
    if "prod" in database_name or "production" in database_name:
        raise LocalOnlyRefusal("Production-like database names are refused")


async def api_json(
    client: LocalAsgiClient,
    method: str,
    path: str,
    user_id: uuid.UUID | None,
    expected_status: int,
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(
        method,
        path,
        user_id=user_id,
        json_body=json_body,
    )
    if response.status_code != expected_status:
        detail = " ".join(response.text.split())[:500]
        raise SmokeFailure(
            f"{method.upper()} {path}: expected {expected_status}, "
            f"got {response.status_code}: {detail}"
        )
    if not response.body:
        return None
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{method.upper()} {path} returned non-JSON data") from exc


def find_one(items: list[dict[str, Any]], description: str, **fields: Any) -> dict[str, Any]:
    matches = [
        item
        for item in items
        if all(item.get(field_name) == value for field_name, value in fields.items())
    ]
    require(len(matches) == 1, f"Expected one {description}, found {len(matches)}")
    return matches[0]


def build_users(state: FixtureState) -> dict[str, User]:
    short = state.marker[:10]
    common = {
        "league": League.C,
        "role": UserRole.executor,
        "mpw": 0,
        "wip_limit": 2,
        "is_active": True,
        "auth_version": 0,
        "password_change_required": False,
    }
    return {
        "sender": User(
            id=state.sender_id,
            full_name=f"Messages Smoke Sender {short}",
            email=f"messages-smoke-sender-{state.marker}@local.invalid",
            **common,
        ),
        "recipient": User(
            id=state.recipient_id,
            full_name=f"Messages Smoke Recipient {short}",
            email=f"messages-smoke-recipient-{state.marker}@local.invalid",
            **common,
        ),
        "outsider": User(
            id=state.outsider_id,
            full_name=f"Messages Smoke Outsider {short}",
            email=f"messages-smoke-outsider-{state.marker}@local.invalid",
            **common,
        ),
    }


async def verify_required_tables(connection: Any) -> None:
    def missing_tables(sync_connection: Any) -> list[str]:
        inspector = inspect(sync_connection)
        return sorted(name for name in REQUIRED_TABLES if not inspector.has_table(name))

    missing = await connection.run_sync(missing_tables)
    if missing:
        raise SmokeFailure(
            "Required migrations are missing tables: " + ", ".join(missing)
        )


async def count_rows(
    session_factory: async_sessionmaker[AsyncSession],
    model: Any,
    *conditions: Any,
) -> int:
    async with session_factory() as session:
        statement = select(func.count()).select_from(model)
        if conditions:
            statement = statement.where(*conditions)
        return int((await session.execute(statement)).scalar_one())


def fixture_event_condition(state: FixtureState) -> Any:
    clauses = [
        CommunicationEvent.actor_id.in_(state.user_ids),
        CommunicationEvent.idempotency_key.like(f"%{state.marker}%"),
    ]
    if state.source_keys:
        clauses.append(CommunicationEvent.source_key.in_(state.source_keys))
    return or_(*clauses)


async def cleanup_fixtures(state: FixtureState) -> None:
    """Delete fixture rows if anything escaped the outer rollback, then verify."""
    user_ids = state.user_ids
    async with AsyncSessionLocal() as session:
        event_ids = list(
            (
                await session.execute(
                    select(CommunicationEvent.id).where(fixture_event_condition(state))
                )
            ).scalars()
        )
        thread_ids = select(MessageThread.id).where(
            MessageThread.created_by_id.in_(user_ids)
        )
        note_ids = select(QuickNote.id).where(QuickNote.owner_id.in_(user_ids))

        attention_filter = UserAttentionItem.user_id.in_(user_ids)
        if event_ids:
            attention_filter = or_(
                attention_filter,
                UserAttentionItem.event_id.in_(event_ids),
            )
        await session.execute(delete(UserAttentionItem).where(attention_filter))
        await session.execute(
            delete(EmailOutbox).where(EmailOutbox.recipient_user_id.in_(user_ids))
        )
        await session.execute(
            delete(MessagePost).where(
                or_(
                    MessagePost.author_id.in_(user_ids),
                    MessagePost.thread_id.in_(thread_ids),
                )
            )
        )
        await session.execute(
            delete(MessageThreadParticipant).where(
                or_(
                    MessageThreadParticipant.user_id.in_(user_ids),
                    MessageThreadParticipant.thread_id.in_(thread_ids),
                )
            )
        )
        await session.execute(
            delete(MessageThread).where(MessageThread.created_by_id.in_(user_ids))
        )
        await session.execute(
            delete(QuickNoteComment).where(
                or_(
                    QuickNoteComment.author_id.in_(user_ids),
                    QuickNoteComment.note_id.in_(note_ids),
                )
            )
        )
        await session.execute(
            delete(QuickNoteShare).where(
                or_(
                    QuickNoteShare.owner_id.in_(user_ids),
                    QuickNoteShare.recipient_id.in_(user_ids),
                    QuickNoteShare.note_id.in_(note_ids),
                )
            )
        )
        await session.execute(
            delete(Contact).where(
                or_(
                    Contact.requester_id.in_(user_ids),
                    Contact.recipient_id.in_(user_ids),
                )
            )
        )
        await session.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await session.execute(
            delete(CommunicationEvent).where(fixture_event_condition(state))
        )
        await session.execute(delete(QuickNote).where(QuickNote.owner_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()

    checks = {
        "users": select(func.count(User.id)).where(User.id.in_(user_ids)),
        "contacts": select(func.count(Contact.id)).where(
            or_(Contact.requester_id.in_(user_ids), Contact.recipient_id.in_(user_ids))
        ),
        "quick notes": select(func.count(QuickNote.id)).where(
            QuickNote.owner_id.in_(user_ids)
        ),
        "quick-note shares": select(func.count(QuickNoteShare.id)).where(
            or_(
                QuickNoteShare.owner_id.in_(user_ids),
                QuickNoteShare.recipient_id.in_(user_ids),
            )
        ),
        "quick-note comments": select(func.count(QuickNoteComment.id)).where(
            QuickNoteComment.author_id.in_(user_ids)
        ),
        "message threads": select(func.count(MessageThread.id)).where(
            MessageThread.created_by_id.in_(user_ids)
        ),
        "message participants": select(func.count(MessageThreadParticipant.id)).where(
            MessageThreadParticipant.user_id.in_(user_ids)
        ),
        "message posts": select(func.count(MessagePost.id)).where(
            MessagePost.author_id.in_(user_ids)
        ),
        "email outbox": select(func.count(EmailOutbox.id)).where(
            EmailOutbox.recipient_user_id.in_(user_ids)
        ),
        "notifications": select(func.count(Notification.id)).where(
            Notification.user_id.in_(user_ids)
        ),
        "attention items": select(func.count(UserAttentionItem.id)).where(
            UserAttentionItem.user_id.in_(user_ids)
        ),
    }
    if event_ids:
        checks["communication events"] = select(func.count(CommunicationEvent.id)).where(
            CommunicationEvent.id.in_(event_ids)
        )

    async with AsyncSessionLocal() as session:
        remaining = {
            label: int((await session.execute(statement)).scalar_one())
            for label, statement in checks.items()
        }
    leaked = {label: count for label, count in remaining.items() if count}
    require(not leaked, f"Fixture cleanup left rows behind: {leaked}")


async def exercise_slice(
    client: LocalAsgiClient,
    session_factory: async_sessionmaker[AsyncSession],
    users: dict[str, User],
    state: FixtureState,
    coverage: list[str],
) -> None:
    sender = users["sender"]
    recipient = users["recipient"]
    outsider = users["outsider"]

    health = await api_json(client, "GET", "/health", None, 200)
    require(health == {"status": "ok"}, "Local in-process API health check failed")

    contact = await api_json(
        client,
        "POST",
        "/api/contacts",
        sender.id,
        200,
        {"email": recipient.email},
    )
    contact_id = str(contact["id"])
    state.source_keys.add(contact_id)
    require(contact["status"] == "pending", "Contact request was not pending")

    summary = await api_json(
        client, "GET", "/api/messages/summary", recipient.id, 200
    )
    require(summary == {"direct_count": 1, "important_count": 0}, "Contact request badge mismatch")
    direct_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=true",
        recipient.id,
        200,
    )
    request_item = find_one(
        direct_items,
        "contact request attention item",
        kind="direct",
        event_type="contact.request.received",
        source_type="contact",
        source_key=contact_id,
        is_read=False,
    )
    await api_json(
        client,
        "POST",
        f"/api/messages/attention/{request_item['id']}/read",
        recipient.id,
        200,
    )
    all_direct = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=false",
        recipient.id,
        200,
    )
    read_request_item = find_one(
        all_direct,
        "read contact request attention item",
        event_type="contact.request.received",
        source_key=contact_id,
    )
    require(read_request_item["is_read"] is True, "Exact attention read did not persist")

    accepted = await api_json(
        client,
        "PATCH",
        f"/api/contacts/{contact_id}/accept",
        recipient.id,
        200,
    )
    require(accepted["status"] == "accepted", "Contact request was not accepted")
    sender_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=true",
        sender.id,
        200,
    )
    find_one(
        sender_items,
        "accepted contact response",
        event_type="contact.request.accepted",
        source_type="contact",
        source_key=contact_id,
        is_read=False,
    )
    context_read = await api_json(
        client,
        "POST",
        "/api/messages/attention/context/read",
        sender.id,
        200,
        {"source_type": "contact", "source_key": contact_id},
    )
    require(context_read["marked"] == 1, "Contact context read did not mark one item")
    coverage.append("contact request direct attention, exact/context read, accepted response")

    rejection_cycle = await api_json(
        client,
        "POST",
        "/api/contacts",
        sender.id,
        200,
        {"email": outsider.email},
    )
    rejection_contact_id = str(rejection_cycle["id"])
    state.source_keys.add(rejection_contact_id)
    await api_json(
        client,
        "PATCH",
        f"/api/contacts/{rejection_contact_id}/reject",
        outsider.id,
        200,
    )
    await api_json(
        client,
        "POST",
        "/api/messages/attention/context/read",
        sender.id,
        200,
        {"source_type": "contact", "source_key": rejection_contact_id},
    )
    reopened = await api_json(
        client,
        "POST",
        "/api/contacts",
        outsider.id,
        200,
        {"email": sender.email},
    )
    require(
        reopened["id"] == rejection_contact_id
        and reopened["status"] == "pending"
        and reopened["requester_id"] == str(outsider.id),
        "Rejected contact pair did not reopen as a reversed request",
    )
    await api_json(
        client,
        "PATCH",
        f"/api/contacts/{rejection_contact_id}/reject",
        sender.id,
        200,
    )
    outsider_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=true",
        outsider.id,
        200,
    )
    latest_rejection = find_one(
        outsider_items,
        "second-cycle contact rejection",
        event_type="contact.request.rejected",
        source_key=rejection_contact_id,
        is_read=False,
    )
    require(
        latest_rejection["actor_id"] == str(sender.id)
        and sender.full_name in latest_rejection["body"],
        "Repeated rejection reused the first cycle actor or message",
    )
    require(
        await count_rows(
            session_factory,
            CommunicationEvent,
            CommunicationEvent.event_type == "contact.request.rejected",
            CommunicationEvent.source_key == rejection_contact_id,
        )
        == 2,
        "Repeated rejection did not retain two immutable communication events",
    )
    await api_json(
        client,
        "POST",
        "/api/messages/attention/context/read",
        outsider.id,
        200,
        {"source_type": "contact", "source_key": rejection_contact_id},
    )
    coverage.append("reopened contact rejection keeps the current actor and event history")

    note = await api_json(
        client,
        "POST",
        "/api/quick-notes",
        sender.id,
        200,
        {
            "title": f"Messages smoke note {state.marker[:10]}",
            "body": f"Owned note fixture {state.marker}",
            "context": "messages-smoke",
            "tags": ["smoke", "messages"],
        },
    )
    note_id = str(note["id"])
    state.source_keys.add(note_id)
    thread_request_id = str(uuid.uuid4())
    thread_payload = {
        "recipient_id": str(recipient.id),
        "subject": f"Transactional smoke {state.marker[:12]}",
        "body": f"Initial message {state.marker}",
        "quick_note_id": note_id,
        "request_id": thread_request_id,
    }
    thread = await api_json(
        client, "POST", "/api/messages/threads", sender.id, 201, thread_payload
    )
    thread_retry = await api_json(
        client, "POST", "/api/messages/threads", sender.id, 201, thread_payload
    )
    thread_id = str(thread["id"])
    first_post_id = str(thread["posts"][0]["id"])
    require(thread_retry["id"] == thread_id, "Thread retry created another thread")
    require(
        len(thread_retry["posts"]) == 1
        and str(thread_retry["posts"][0]["id"]) == first_post_id,
        "Thread retry created another first post",
    )
    require(
        thread["posts"][0]["quick_note_available"] is True
        and str(thread["posts"][0]["quick_note_id"]) == note_id,
        "Owned quick note was not attached to the first post",
    )
    require(
        await count_rows(
            session_factory,
            MessageThread,
            MessageThread.created_by_id == sender.id,
            MessageThread.request_id == uuid.UUID(thread_request_id),
        )
        == 1,
        "Thread idempotency key is not unique",
    )
    async with session_factory() as session:
        email_jobs = list(
            (
                await session.execute(
                    select(EmailOutbox).where(
                        EmailOutbox.message_post_id == uuid.UUID(first_post_id)
                    )
                )
            ).scalars()
        )
    require(len(email_jobs) == 1, "Thread retry duplicated its email job")
    require(
        email_jobs[0].recipient_user_id == recipient.id
        and email_jobs[0].deep_link_path == f"/messages/{thread_id}",
        "First message email job points to the wrong recipient or thread",
    )
    email_projection = " ".join(
        str(value)
        for value in (
            email_jobs[0].event_type,
            email_jobs[0].template_key,
            email_jobs[0].source_type,
            email_jobs[0].sender_name,
            email_jobs[0].deep_link_path,
        )
    )
    require(thread_payload["body"] not in email_projection, "Email outbox leaked message body")
    require(thread_payload["subject"] not in email_projection, "Email outbox leaked thread subject")

    recipient_threads = await api_json(
        client, "GET", "/api/messages/threads", recipient.id, 200
    )
    recipient_thread = find_one(recipient_threads, "recipient thread", id=thread_id)
    require(recipient_thread["unread_count"] == 1, "Recipient unread count was not incremented")
    summary = await api_json(
        client, "GET", "/api/messages/summary", recipient.id, 200
    )
    require(summary["direct_count"] == 1, "Unread thread was not included in direct badge")
    recipient_attention = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=true",
        recipient.id,
        200,
    )
    require(
        not any(item["event_type"] == "quick_note.share.received" for item in recipient_attention),
        "Message attachment emitted a duplicate quick-note share attention item",
    )
    shared_note = await api_json(
        client, "GET", f"/api/quick-notes/{note_id}", recipient.id, 200
    )
    require(str(shared_note["note"]["id"]) == note_id, "Recipient cannot read attached note")
    shares = await api_json(
        client, "GET", f"/api/quick-notes/{note_id}/shares", sender.id, 200
    )
    share = find_one(shares, "automatic note share", recipient_id=str(recipient.id))
    require(share["status"] == "active", "Automatic note share is not active")

    await api_json(
        client, "GET", f"/api/messages/threads/{thread_id}", outsider.id, 404
    )
    await api_json(
        client,
        "POST",
        f"/api/messages/threads/{thread_id}/posts",
        outsider.id,
        404,
        {"body": "Outsider reply", "request_id": str(uuid.uuid4())},
    )
    await api_json(
        client, "GET", f"/api/quick-notes/{note_id}", outsider.id, 404
    )
    await api_json(
        client,
        "POST",
        "/api/messages/threads",
        outsider.id,
        403,
        {
            "recipient_id": str(sender.id),
            "subject": "Outsider attempt",
            "body": "Must be blocked",
            "request_id": str(uuid.uuid4()),
        },
    )

    await api_json(
        client, "POST", f"/api/messages/threads/{thread_id}/read", recipient.id, 200
    )
    recipient_thread = await api_json(
        client, "GET", f"/api/messages/threads/{thread_id}", recipient.id, 200
    )
    require(recipient_thread["unread_count"] == 0, "Recipient thread did not become read")
    summary = await api_json(
        client, "GET", "/api/messages/summary", recipient.id, 200
    )
    require(summary["direct_count"] == 0, "Recipient direct badge did not clear")
    coverage.append("subject thread idempotency, recipient unread/read, outsider denial")
    coverage.append("owned quick-note attachment and automatic recipient share")

    await api_json(
        client,
        "POST",
        f"/api/messages/threads/{thread_id}/posts",
        recipient.id,
        404,
        {
            "body": "Shared notes are not owned attachments",
            "quick_note_id": note_id,
            "request_id": str(uuid.uuid4()),
        },
    )
    reply_request_id = str(uuid.uuid4())
    reply_payload = {
        "body": f"Idempotent reply {state.marker}",
        "request_id": reply_request_id,
    }
    reply = await api_json(
        client,
        "POST",
        f"/api/messages/threads/{thread_id}/posts",
        recipient.id,
        200,
        reply_payload,
    )
    reply_retry = await api_json(
        client,
        "POST",
        f"/api/messages/threads/{thread_id}/posts",
        recipient.id,
        200,
        reply_payload,
    )
    require(reply_retry["id"] == reply["id"], "Reply retry created another post")
    require(
        await count_rows(
            session_factory,
            MessagePost,
            MessagePost.author_id == recipient.id,
            MessagePost.request_id == uuid.UUID(reply_request_id),
        )
        == 1,
        "Reply idempotency key is not unique",
    )
    require(
        await count_rows(
            session_factory,
            EmailOutbox,
            EmailOutbox.recipient_user_id.in_([sender.id, recipient.id]),
        )
        == 2,
        "Reply retry did not preserve exactly one email job per post",
    )
    sender_thread = await api_json(
        client, "GET", f"/api/messages/threads/{thread_id}", sender.id, 200
    )
    require(
        sender_thread["unread_count"] == 1 and len(sender_thread["posts"]) == 2,
        "Reply did not increment sender unread state exactly once",
    )
    require(
        str(sender_thread["posts"][0]["id"]) == str(reply["id"])
        and str(sender_thread["posts"][1]["id"]) == first_post_id,
        "Thread detail is not ordered from newest to oldest",
    )
    await api_json(
        client, "POST", f"/api/messages/threads/{thread_id}/read", sender.id, 200
    )
    coverage.append("reply idempotency, newest-first order, and sender unread transition")
    coverage.append("transactional body-free email outbox per message recipient")

    first_comment = await api_json(
        client,
        "POST",
        f"/api/quick-notes/{note_id}/comments",
        recipient.id,
        200,
        {"body": f"First coalesced comment {state.marker}"},
    )
    second_comment_text = f"Latest coalesced comment {state.marker}"
    second_comment = await api_json(
        client,
        "POST",
        f"/api/quick-notes/{note_id}/comments",
        recipient.id,
        200,
        {"body": second_comment_text, "parent_id": first_comment["id"]},
    )
    require(second_comment["parent_id"] == first_comment["id"], "Comment reply was not linked")
    sender_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=direct&unread_only=true",
        sender.id,
        200,
    )
    comment_items = [
        item
        for item in sender_items
        if item["event_type"] == "quick_note.comment.received"
        and item["source_key"] == note_id
    ]
    require(len(comment_items) == 1, "Note comments did not coalesce to one attention item")
    require(
        second_comment_text in comment_items[0]["body"],
        "Coalesced attention item does not point to the latest comment",
    )
    require(
        await count_rows(
            session_factory,
            CommunicationEvent,
            CommunicationEvent.event_type == "quick_note.comment.received",
            CommunicationEvent.source_key == note_id,
        )
        == 2,
        "Each note comment did not retain its immutable communication event",
    )
    require(
        await count_rows(
            session_factory,
            UserAttentionItem,
            UserAttentionItem.user_id == sender.id,
            UserAttentionItem.dedupe_key == f"quick-note-discussion:{note_id}",
        )
        == 1,
        "Note-comment attention projection was not deduplicated",
    )
    context_read = await api_json(
        client,
        "POST",
        "/api/messages/attention/context/read",
        sender.id,
        200,
        {"source_type": "quick_note", "source_key": note_id},
    )
    require(context_read["marked"] == 1, "Quick-note context did not clear attention")
    coverage.append("note-comment attention coalescing with immutable source events")

    async with session_factory() as session:
        notification = await create_notification(
            session,
            user_id=sender.id,
            type="quality_alert",
            title=f"Legacy bridge smoke {state.marker}",
            message="Whitelisted legacy notification",
            link=f"/messages-smoke/{state.marker}",
            actor_id=recipient.id,
        )
        await session.commit()
        notification_id = str(notification.id)
    state.source_keys.add(notification_id)

    important_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=important&unread_only=true",
        sender.id,
        200,
    )
    important_item = find_one(
        important_items,
        "important legacy notification bridge",
        kind="important",
        event_type="quality_alert",
        source_type="notification",
        source_key=notification_id,
        is_read=False,
    )
    summary = await api_json(client, "GET", "/api/messages/summary", sender.id, 200)
    require(summary["important_count"] == 1, "Important badge did not include legacy notification")
    await api_json(
        client,
        "POST",
        f"/api/messages/attention/{important_item['id']}/read",
        outsider.id,
        404,
    )
    await api_json(
        client,
        "POST",
        f"/api/messages/attention/{important_item['id']}/read",
        sender.id,
        200,
    )
    unread_notifications = await api_json(
        client,
        "GET",
        "/api/notifications?unread_only=true",
        sender.id,
        200,
    )
    require(
        all(str(item["id"]) != notification_id for item in unread_notifications),
        "Attention read did not mark the legacy notification read",
    )
    summary = await api_json(client, "GET", "/api/messages/summary", sender.id, 200)
    require(summary["important_count"] == 0, "Important badge did not clear")

    async with session_factory() as session:
        exact_notification = await create_notification(
            session,
            user_id=sender.id,
            type="quality_alert",
            title=f"Legacy exact read {state.marker}",
            message="Read through the legacy exact endpoint",
            link=f"/messages-smoke/{state.marker}/exact",
            actor_id=recipient.id,
        )
        bulk_notification = await create_notification(
            session,
            user_id=sender.id,
            type="quality_alert",
            title=f"Legacy bulk read {state.marker}",
            message="Read through the legacy bulk endpoint",
            link=f"/messages-smoke/{state.marker}/bulk",
            actor_id=recipient.id,
        )
        await session.commit()
        exact_notification_id = str(exact_notification.id)
        bulk_notification_id = str(bulk_notification.id)
    state.source_keys.update({exact_notification_id, bulk_notification_id})

    await api_json(
        client,
        "POST",
        f"/api/notifications/{exact_notification_id}/read",
        sender.id,
        200,
    )
    important_items = await api_json(
        client,
        "GET",
        "/api/messages/attention?kind=important&unread_only=true",
        sender.id,
        200,
    )
    require(
        all(item["source_key"] != exact_notification_id for item in important_items),
        "Legacy exact read did not clear its attention mirror",
    )
    find_one(
        important_items,
        "remaining bulk-read notification mirror",
        source_key=bulk_notification_id,
        is_read=False,
    )
    read_all = await api_json(
        client,
        "POST",
        "/api/notifications/read-all",
        sender.id,
        200,
    )
    require(read_all["marked"] == 1, "Legacy bulk read did not mark one notification")
    summary = await api_json(client, "GET", "/api/messages/summary", sender.id, 200)
    require(
        summary["important_count"] == 0,
        "Legacy bulk read did not clear the remaining important badge",
    )
    coverage.append(
        "bidirectional legacy notification and attention read synchronization"
    )


async def run_smoke(api_url: str, *, allow_compose_db: bool = False) -> list[str]:
    parsed_api_url = assert_local_api_url(api_url)
    assert_local_database(allow_compose_db=allow_compose_db)

    from app.main import app

    state = FixtureState()
    coverage: list[str] = []
    cleanup_ready = False
    try:
        async with engine.connect() as connection:
            outer_transaction = await connection.begin()
            previous_db_override = app.dependency_overrides.get(get_db)
            had_db_override = get_db in app.dependency_overrides
            previous_user_override = app.dependency_overrides.get(get_current_user)
            had_user_override = get_current_user in app.dependency_overrides
            try:
                await verify_required_tables(connection)
                cleanup_ready = True
                session_factory = async_sessionmaker(
                    bind=connection,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                    join_transaction_mode="create_savepoint",
                )
                users = build_users(state)
                async with session_factory() as session:
                    session.add_all(list(users.values()))
                    await session.commit()

                allowed_users = {user.id: user for user in users.values()}

                async def smoke_db() -> AsyncGenerator[AsyncSession, None]:
                    async with session_factory() as session:
                        try:
                            yield session
                            await session.commit()
                        except Exception:
                            await session.rollback()
                            raise

                async def smoke_user(request: Request) -> User:
                    raw_user_id = request.headers.get(SMOKE_USER_HEADER)
                    try:
                        user_id = uuid.UUID(raw_user_id) if raw_user_id else None
                    except ValueError as exc:
                        raise SmokeFailure("Invalid smoke user header") from exc
                    user = allowed_users.get(user_id)
                    if user is None:
                        raise SmokeFailure("Request did not identify a fixture user")
                    return user

                app.dependency_overrides[get_db] = smoke_db
                app.dependency_overrides[get_current_user] = smoke_user
                client = LocalAsgiClient(app, parsed_api_url)
                await exercise_slice(client, session_factory, users, state, coverage)
            finally:
                if had_db_override:
                    app.dependency_overrides[get_db] = previous_db_override
                else:
                    app.dependency_overrides.pop(get_db, None)
                if had_user_override:
                    app.dependency_overrides[get_current_user] = previous_user_override
                else:
                    app.dependency_overrides.pop(get_current_user, None)
                if outer_transaction.is_active:
                    await outer_transaction.rollback()
    finally:
        if cleanup_ready:
            await cleanup_fixtures(state)

    coverage.append("outer rollback plus verified fixture-scoped cleanup")
    return coverage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000",
        help="Local base URL used for the in-process ASGI request scope",
    )
    parser.add_argument(
        "--allow-compose-db",
        action="store_true",
        help="Explicitly allow the local Docker Compose database hostname 'db'",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        coverage = asyncio.run(
            run_smoke(args.api_url, allow_compose_db=args.allow_compose_db)
        )
    except LocalOnlyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("PASS: DPMS Messages/attention smoke")
    for item in coverage:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
