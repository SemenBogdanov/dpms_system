"""Pre-header admission for pinned Uvicorn 0.52.4 / h11 0.16.0.

Pass ``http=BoundedH11Protocol`` to the existing single-worker Uvicorn runner.
Keep its loopback binding, backlog, ASGI deadline, parser size limit and logging
policy. Tests can use functools.partial to override the positive bounds.

The header budget includes idle time, starting at admission or when h11 can
start the next request. Pipelined bytes wait behind the current response under
Uvicorn's existing backpressure; they cannot time out an active ASGI request.
This bounds admitted transports, not the kernel backlog or transient accepts.
Re-review the adapter and run its socket tests when either pin changes.
"""

from __future__ import annotations

import asyncio
import math

import h11
from uvicorn.protocols.http.h11_impl import H11Protocol


class BoundedH11Protocol(H11Protocol):
    def __init__(self, config, server_state, app_state, _loop=None, *,
                 max_connections: int = 16, header_timeout: float = 5.0):
        if type(max_connections) is not int or max_connections < 1:
            raise ValueError("max_connections must be a positive integer")
        if (type(header_timeout) not in (int, float)
                or not math.isfinite(header_timeout) or header_timeout <= 0):
            raise ValueError("header_timeout must be positive and finite")
        super().__init__(config, server_state, app_state, _loop)
        self.max_connections = max_connections
        self.header_timeout = header_timeout
        self._admitted = False
        self._shutting_down = False
        self._header_timer: asyncio.TimerHandle | None = None
        self._header_deadline: float | None = None
        # This HTTP-only boundary must not transfer admission to a WS protocol.
        self.ws_protocol_class = None
        self.access_log = False

    def connection_made(self, transport: asyncio.Transport) -> None:
        # One event loop / ServerState: check and registration have no await.
        self.transport = transport
        if len(self.connections) >= self.max_connections:
            transport.abort()
            return
        self._admitted = True
        super().connection_made(transport)
        self._update_header_timer()

    def data_received(self, data: bytes) -> None:
        if self._admitted and not self.transport.is_closing():
            super().data_received(data)

    def handle_events(self) -> None:
        if not self._admitted or self.transport.is_closing():
            return
        # Ready socket callbacks can run before an already-due timer callback.
        if self._header_deadline is not None and self.loop.time() >= self._header_deadline:
            self._expire_headers()
            return
        try:
            super().handle_events()
        finally:
            self._update_header_timer()

    def on_response_complete(self) -> None:
        try:
            super().on_response_complete()
        finally:
            self._update_header_timer()

    def _update_header_timer(self) -> None:
        # h11 alone identifies header completion, including buffered pipelines
        # and a new cycle entered after an early response's body is drained.
        if (not self._admitted or self._shutting_down or self.transport.is_closing()
                or self.conn.their_state is not h11.IDLE):
            self._cancel_header_timer()
        elif self._header_timer is None:
            self._header_deadline = self.loop.time() + self.header_timeout
            self._header_timer = self.loop.call_at(self._header_deadline, self._expire_headers)

    def _cancel_header_timer(self) -> None:
        if self._header_timer is not None:
            self._header_timer.cancel()
            self._header_timer = None
        self._header_deadline = None

    def _expire_headers(self) -> None:
        self._cancel_header_timer()
        self._unset_keepalive_if_required()
        self.transport.abort()

    def connection_lost(self, exc: Exception | None) -> None:
        self._cancel_header_timer()
        # Uvicorn only clears its keepalive timer for exc=None.
        self._unset_keepalive_if_required()
        if self._admitted:
            try:
                super().connection_lost(exc)
            finally:
                self._admitted = False

    def shutdown(self) -> None:
        self._shutting_down = True
        self._cancel_header_timer()
        self._unset_keepalive_if_required()
        if self._admitted:
            super().shutdown()
