"""Real TCP regression tests; ephemeral loopback only, no external model."""

import asyncio
import json
import logging
import unittest
from unittest.mock import patch

import h11
import httpx
import uvicorn

from bounded_transport import BoundedH11Protocol
from gateway import Settings, create_app


def request(path=b"/", *, close=False):
    return (b"GET " + path + b" HTTP/1.1\r\nHost: localhost\r\n"
            + (b"Connection: close\r\n" if close else b"") + b"\r\n")


class WireClient:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.pending = b""

    async def send(self, data):
        self.writer.write(data)
        await self.writer.drain()

    async def response(self):
        async with asyncio.timeout(2):
            parser = h11.Connection(h11.CLIENT)
            # Requests are sent as raw fixtures; prime the maintained response
            # parser separately so it also works with pipelined responses.
            parser.send(h11.Request(method="GET", target="/", headers=[("Host", "localhost")]))
            parser.send(h11.EndOfMessage())
            if self.pending:
                parser.receive_data(self.pending)
            status, body = None, bytearray()
            while True:
                event = parser.next_event()
                if event is h11.NEED_DATA:
                    data = await self.reader.read(65536)
                    parser.receive_data(data)
                elif isinstance(event, h11.Response):
                    status = event.status_code
                elif isinstance(event, h11.Data):
                    body.extend(event.data)
                elif isinstance(event, h11.EndOfMessage):
                    self.pending = parser.trailing_data[0]
                    return status, bytes(body)
                else:
                    raise AssertionError("Unexpected response event")


class SocketHarness(unittest.IsolatedAsyncioTestCase):
    header_timeout = 0.25
    max_connections = 3

    async def asyncSetUp(self):
        self.clients = []
        self.protocols = []
        self.calls = asyncio.Queue()
        self.loop_errors = []
        self.loop = asyncio.get_running_loop()
        self.old_exception_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, context: self.loop_errors.append(context))
        self.addCleanup(self.loop.set_exception_handler, self.old_exception_handler)

        def protocol_factory(**kwargs):
            protocol = BoundedH11Protocol(**kwargs, header_timeout=self.header_timeout,
                                          max_connections=self.max_connections)
            self.protocols.append(protocol)
            return protocol

        config = uvicorn.Config(
            self.make_app(), host="127.0.0.1", port=0, http=protocol_factory,
            workers=1, loop="asyncio", lifespan="on", interface="asgi3", ws="none",
            timeout_keep_alive=2, timeout_graceful_shutdown=2,
            access_log=False, log_config=None, log_level="critical",
            proxy_headers=False, server_header=False,
            h11_max_incomplete_event_size=16 * 1024,
        )
        self.server = uvicorn.Server(config)
        self.server_task = asyncio.create_task(self.server.serve())
        self.addAsyncCleanup(self.stop_server)
        async with asyncio.timeout(3):
            while not self.server.started:
                if self.server_task.done():
                    await self.server_task
                    self.fail("Server stopped before startup")
                await asyncio.sleep(0.005)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]

    def make_app(self):
        return self.app

    async def app(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        self.calls.put_nowait(scope["path"])
        if scope["path"] == "/slow":
            await asyncio.sleep(self.header_timeout * 2.5)
        if scope["path"] == "/body":
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                if not event["more_body"]:
                    break
        streaming = scope["path"] == "/stream"
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"4" if streaming else b"2")]})
        await send({"type": "http.response.body", "body": b"ok", "more_body": streaming})
        if streaming:
            await asyncio.sleep(self.header_timeout * 2.5)
            await send({"type": "http.response.body", "body": b"ok"})

    async def stop_server(self):
        for client in self.clients:
            client.writer.close()
        for client in self.clients:
            try:
                await client.writer.wait_closed()
            except ConnectionError:
                pass
        self.server.should_exit = True
        await asyncio.wait_for(self.server_task, 4)
        self.assertFalse(self.server.server_state.connections)
        self.assertFalse(self.server.server_state.tasks)
        for protocol in self.protocols:
            self.assertIsNone(protocol._header_timer)
            self.assertIsNone(protocol._header_deadline)
            self.assertIsNone(protocol.timeout_keep_alive_task)
        self.assertFalse(self.loop_errors, "Unexpected event-loop exception")

    async def connect(self):
        client = WireClient(*await asyncio.open_connection("127.0.0.1", self.port))
        self.clients.append(client)
        return client

    async def wait_connections(self, count):
        async with asyncio.timeout(1):
            while len(self.server.server_state.connections) != count:
                await asyncio.sleep(0.005)

    async def assert_closed(self, client, timeout=1):
        try:
            data = await asyncio.wait_for(client.reader.read(1), timeout)
        except ConnectionError:
            data = b""
        self.assertEqual(data, b"")

    async def drip_until_closed(self, client):
        async def drip():
            while True:
                try:
                    await client.send(b"x")
                except ConnectionError:
                    return
                await asyncio.sleep(self.header_timeout / 8)

        start = self.loop.time()
        task = asyncio.create_task(drip())
        try:
            await self.assert_closed(client, self.header_timeout * 3)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertLess(self.loop.time() - start, self.header_timeout * 2)


class TransportTests(SocketHarness):
    async def test_idle_initial_socket_expires(self):
        start = self.loop.time()
        client = await self.connect()
        await self.assert_closed(client)
        self.assertGreaterEqual(self.loop.time() - start, self.header_timeout * 0.8)
        self.assertLess(self.loop.time() - start, self.header_timeout * 2)
        self.assertTrue(self.calls.empty())

    async def test_incomplete_initial_header_expires(self):
        client = await self.connect()
        await client.send(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Padding: ")
        await self.assert_closed(client, self.header_timeout * 2)
        self.assertTrue(self.calls.empty())

    async def test_drip_initial_header_has_total_deadline(self):
        client = await self.connect()
        await client.send(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Padding: ")
        await self.drip_until_closed(client)
        self.assertTrue(self.calls.empty())

    async def test_drip_request_line_has_total_deadline(self):
        client = await self.connect()
        await client.send(b"G")
        await self.drip_until_closed(client)
        self.assertTrue(self.calls.empty())

    async def test_keepalive_second_header_has_total_deadline(self):
        client = await self.connect()
        await client.send(request())
        self.assertEqual(await client.response(), (200, b"ok"))
        await client.send(b"GET /second HTTP/1.1\r\nHost: localhost\r\nX-Padding: ")
        await self.drip_until_closed(client)
        self.assertEqual(self.calls.qsize(), 1)

    async def test_keepalive_idle_expires(self):
        client = await self.connect()
        await client.send(request())
        self.assertEqual(await client.response(), (200, b"ok"))
        await self.assert_closed(client, self.header_timeout * 2)

    async def test_keepalive_normal_second_request_succeeds(self):
        client = await self.connect()
        for path in (b"/first", b"/second", b"/third"):
            await client.send(request(path))
            self.assertEqual(await client.response(), (200, b"ok"))
        self.assertEqual(self.calls.qsize(), 3)

    async def test_socket_exhaustion_rejects_before_headers_and_recovers(self):
        holders = [await self.connect() for _ in range(self.max_connections)]
        await self.wait_connections(self.max_connections)
        rejected = await self.connect()
        await self.assert_closed(rejected, self.header_timeout / 2)
        self.assertEqual(len(self.server.server_state.connections), self.max_connections)
        self.assertTrue(self.calls.empty())
        self.assertIsNone(self.protocols[-1]._header_timer)
        holders[0].writer.close()
        await holders[0].writer.wait_closed()
        await self.wait_connections(self.max_connections - 1)
        replacement = await self.connect()
        await replacement.send(request(close=True))
        self.assertEqual(await replacement.response(), (200, b"ok"))

    async def test_active_and_keepalive_connections_count_toward_limit(self):
        active = await self.connect()
        await active.send(request(b"/slow", close=True))
        self.assertEqual(await asyncio.wait_for(self.calls.get(), 1), "/slow")
        idle = await self.connect()
        await idle.send(request())
        self.assertEqual(await idle.response(), (200, b"ok"))
        await self.connect()
        await self.wait_connections(self.max_connections)
        rejected = await self.connect()
        await self.assert_closed(rejected, self.header_timeout / 2)
        self.assertEqual(await active.response(), (200, b"ok"))

    async def test_expired_slots_are_reusable(self):
        holders = [await self.connect() for _ in range(self.max_connections)]
        for client in holders:
            await self.assert_closed(client)
        await self.wait_connections(0)
        client = await self.connect()
        await client.send(request(close=True))
        self.assertEqual(await client.response(), (200, b"ok"))

    async def test_active_response_outlives_header_deadline(self):
        client = await self.connect()
        await client.send(request(b"/slow", close=True))
        await asyncio.wait_for(self.calls.get(), 1)
        self.assertIsNone(self.protocols[-1]._header_timer)
        self.assertEqual(await client.response(), (200, b"ok"))

    async def test_streaming_response_outlives_header_deadline(self):
        client = await self.connect()
        await client.send(request(b"/stream", close=True))
        self.assertEqual(await client.response(), (200, b"okok"))

    async def test_complete_headers_leave_body_to_asgi(self):
        client = await self.connect()
        await client.send(b"POST /body HTTP/1.1\r\nHost: localhost\r\nContent-Length: 2\r\n\r\na")
        await asyncio.wait_for(self.calls.get(), 1)
        self.assertIsNone(self.protocols[-1]._header_timer)
        await asyncio.sleep(self.header_timeout * 1.5)
        await client.send(b"b")
        self.assertEqual(await client.response(), (200, b"ok"))

    async def test_complete_pipeline_survives_slow_responses(self):
        client = await self.connect()
        await client.send(request(b"/slow") + request(b"/slow") + request(close=True))
        for _ in range(3):
            self.assertEqual(await client.response(), (200, b"ok"))
        await self.assert_closed(client)
        self.assertEqual(self.calls.qsize(), 3)

    async def test_incomplete_pipeline_gets_deadline_after_active_response(self):
        client = await self.connect()
        await client.send(request(b"/slow") + b"GET /next HTTP/1.1\r\nHost: localhost\r\nX: ")
        self.assertEqual(await client.response(), (200, b"ok"))
        await self.drip_until_closed(client)
        self.assertEqual(self.calls.qsize(), 1)

    async def test_fragmented_pipeline_can_complete_after_active_response(self):
        client = await self.connect()
        await client.send(request(b"/slow") + b"GET /next HTTP/1.1\r\nHost: ")
        self.assertEqual(await client.response(), (200, b"ok"))
        await client.send(b"localhost\r\nConnection: close\r\n\r\n")
        self.assertEqual(await client.response(), (200, b"ok"))

    async def test_h11_still_rejects_invalid_framing_and_oversized_header(self):
        for wire in (
            b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n",
            b"GET / HTTP/1.1\r\nHost: localhost\r\nX: " + b"x" * 20000,
        ):
            client = await self.connect()
            await client.send(wire)
            status, _ = await client.response()
            self.assertEqual(status, 400)
            await self.assert_closed(client)
        self.assertTrue(self.calls.empty())

    async def test_disconnect_cancels_header_timer(self):
        client = await self.connect()
        await self.wait_connections(1)
        handle = self.protocols[-1]._header_timer
        client.writer.close()
        await client.writer.wait_closed()
        await self.wait_connections(0)
        self.assertTrue(handle.cancelled())

    async def test_shutdown_cancels_header_and_keepalive_timers(self):
        client = await self.connect()
        await client.send(request())
        self.assertEqual(await client.response(), (200, b"ok"))
        protocol = self.protocols[-1]
        header, keepalive = protocol._header_timer, protocol.timeout_keep_alive_task
        protocol.shutdown()
        self.assertTrue(header.cancelled())
        self.assertTrue(keepalive.cancelled())
        await self.assert_closed(client)

    async def test_shutdown_does_not_interrupt_active_response(self):
        client = await self.connect()
        await client.send(request(b"/slow"))
        await asyncio.wait_for(self.calls.get(), 1)
        self.protocols[-1].shutdown()
        self.assertEqual(await client.response(), (200, b"ok"))
        await self.assert_closed(client)

    async def test_no_access_content_logging_with_shared_logger(self):
        with patch.object(logging.getLogger("uvicorn.access"), "info") as log:
            client = await self.connect()
            await client.send(request(b"/synthetic-private-content", close=True))
            self.assertEqual(await client.response(), (200, b"ok"))
            log.assert_not_called()


class GatewayTests(SocketHarness):
    def make_app(self):
        self.upstream_delay = 0

        async def upstream(request):
            await asyncio.sleep(self.upstream_delay)
            data = json.dumps({
                "model": "synthetic-model", "choices": [{
                    "message": {"content": "synthetic result"}, "finish_reason": "stop",
                }],
            }).encode()
            return httpx.Response(200, headers={"Content-Type": "application/json"},
                                  stream=httpx.ByteStream(data))

        return create_app(Settings("b" * 43, "synthetic-model", deadline_seconds=1.2),
                          transport=httpx.MockTransport(upstream))

    def completion_request(self, body):
        return (b"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n"
                b"Connection: close\r\nAuthorization: Bearer " + b"b" * 43
                + b"\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body)

    async def test_gateway_generation_outlives_header_budget(self):
        self.upstream_delay = self.header_timeout * 2.5
        body = json.dumps({"model": "synthetic-model", "messages": [
            {"role": "user", "content": "synthetic request"},
        ]}).encode()
        client = await self.connect()
        await client.send(self.completion_request(body))
        start = self.loop.time()
        status, response = await client.response()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response)["choices"][0]["message"]["content"], "synthetic result")
        self.assertGreater(self.loop.time() - start, self.header_timeout)

    async def test_gateway_incomplete_body_uses_asgi_timeout(self):
        client = await self.connect()
        await client.send(self.completion_request(b"{}")[:-1])
        start = self.loop.time()
        status, body = await client.response()
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(body)["error"]["code"], "local_model_timeout")
        self.assertGreater(self.loop.time() - start, 1)


class ConfigurationTests(unittest.TestCase):
    def test_reviewed_dependency_pins(self):
        self.assertEqual(uvicorn.__version__, "0.52.4")
        self.assertEqual(h11.__version__, "0.16.0")

    def test_invalid_bounds_rejected(self):
        for bound in (0, -1, True, 1.5, None):
            with self.subTest(max_connections=bound), self.assertRaises(ValueError):
                BoundedH11Protocol(None, None, None, max_connections=bound)
        for bound in (0, -1, True, float("inf"), float("nan"), None):
            with self.subTest(header_timeout=bound), self.assertRaises(ValueError):
                BoundedH11Protocol(None, None, None, header_timeout=bound)


if __name__ == "__main__":
    unittest.main()
