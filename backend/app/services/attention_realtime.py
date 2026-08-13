"""Process-local realtime invalidation channel for the Messages section."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket


SEND_TIMEOUT_SECONDS = 2.0


@dataclass
class AttentionConnection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AttentionHub:
    """Routes lightweight resync hints to all tabs of a user."""

    def __init__(self) -> None:
        self._connections: dict[UUID, list[AttentionConnection]] = {}

    def add(self, user_id: UUID, connection: AttentionConnection) -> None:
        self._connections.setdefault(user_id, []).append(connection)

    def remove(self, user_id: UUID, connection: AttentionConnection) -> None:
        connections = self._connections.get(user_id)
        if not connections:
            return
        try:
            connections.remove(connection)
        except ValueError:
            pass
        if not connections:
            self._connections.pop(user_id, None)

    async def _send(self, connection: AttentionConnection, payload: dict[str, Any]) -> None:
        try:
            async with connection.send_lock:
                await asyncio.wait_for(
                    connection.websocket.send_text(
                        json.dumps(payload, ensure_ascii=False)
                    ),
                    timeout=SEND_TIMEOUT_SECONDS,
                )
        except Exception:
            pass

    async def send_to_user(self, user_id: UUID, payload: dict[str, Any]) -> None:
        connections = list(self._connections.get(user_id, []))
        if connections:
            await asyncio.gather(
                *(self._send(connection, payload) for connection in connections)
            )

    async def send_to_users(self, user_ids: list[UUID], payload: dict[str, Any]) -> None:
        unique_ids = list(dict.fromkeys(user_ids))
        if unique_ids:
            await asyncio.gather(
                *(self.send_to_user(user_id, payload) for user_id in unique_ids)
            )


attention_hub = AttentionHub()
