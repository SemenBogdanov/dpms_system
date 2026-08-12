"""In-memory realtime hub for quick-note collaboration.

Tracks per-note WebSocket connections keyed by user id so that lightweight
events (note.updated, comment.created, attachment.created, access.changed,
access.revoked, note.deleted) can be broadcast after committed mutations.

The hub is intentionally process-local: it does not persist across restarts and
does not touch the database. All access decisions happen before a connection
joins the hub; the hub only routes messages to already-authorized sockets.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket

SEND_TIMEOUT_SECONDS = 2.0
CLOSE_TIMEOUT_SECONDS = 2.0


@dataclass
class QuickNoteConnection:
    websocket: WebSocket
    user_id: UUID
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class QuickNoteHub:
    """Per-note multicast hub supporting multiple tabs per user."""

    def __init__(self) -> None:
        self._connections: dict[UUID, list[QuickNoteConnection]] = {}

    @property
    def active_users(self) -> list[str]:
        return [str(user_id) for user_id in self._connections]

    def add(self, user_id: UUID, connection: QuickNoteConnection) -> None:
        self._connections.setdefault(user_id, []).append(connection)

    def remove(self, user_id: UUID, connection: QuickNoteConnection) -> None:
        conns = self._connections.get(user_id)
        if not conns:
            return
        try:
            conns.remove(connection)
        except ValueError:
            pass
        if not conns:
            self._connections.pop(user_id, None)

    async def _send(self, connection: QuickNoteConnection, message: dict[str, Any]) -> bool:
        try:
            async with connection.send_lock:
                await asyncio.wait_for(
                    connection.websocket.send_text(json.dumps(message, ensure_ascii=False)),
                    timeout=SEND_TIMEOUT_SECONDS,
                )
            return True
        except Exception:
            return False

    async def broadcast(self, message: dict[str, Any], *, exclude: UUID | None = None) -> None:
        sends = [
            self._send(connection, message)
            for user_id, conns in list(self._connections.items())
            if exclude is None or user_id != exclude
            for connection in conns
        ]
        if sends:
            await asyncio.gather(*sends)

    async def send_to_user(self, message: dict[str, Any], user_id: UUID) -> None:
        conns = list(self._connections.get(user_id, []))
        if conns:
            await asyncio.gather(*(self._send(connection, message) for connection in conns))

    @staticmethod
    async def _close(connection: QuickNoteConnection) -> None:
        try:
            await asyncio.wait_for(
                connection.websocket.close(code=1000),
                timeout=CLOSE_TIMEOUT_SECONDS,
            )
        except Exception:
            pass

    async def disconnect_user(self, user_id: UUID) -> None:
        conns = self._connections.pop(user_id, [])
        if conns:
            await asyncio.gather(*(self._close(connection) for connection in conns))

    async def disconnect_all(self) -> None:
        conns = [
            connection
            for user_connections in self._connections.values()
            for connection in user_connections
        ]
        self._connections.clear()
        if conns:
            await asyncio.gather(*(self._close(connection) for connection in conns))


class QuickNoteHubRegistry:
    """Process-wide registry of per-note hubs."""

    def __init__(self) -> None:
        self._hubs: dict[UUID, QuickNoteHub] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, note_id: UUID) -> QuickNoteHub:
        async with self._lock:
            hub = self._hubs.get(note_id)
            if hub is None:
                hub = QuickNoteHub()
                self._hubs[note_id] = hub
            return hub

    async def try_get(self, note_id: UUID) -> QuickNoteHub | None:
        async with self._lock:
            return self._hubs.get(note_id)

    async def remove_if_empty(self, note_id: UUID) -> None:
        async with self._lock:
            hub = self._hubs.get(note_id)
            if hub is not None and not hub.active_users:
                self._hubs.pop(note_id, None)


hub_registry = QuickNoteHubRegistry()
