"""Real HTTP parser/client smoke, with ephemeral loopback ports and fake model."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import socket
import threading
import time
import unittest

import httpx
import uvicorn

from gateway import Settings, create_app
from bounded_transport import BoundedH11Protocol
from test_gateway import BEARER, HEADERS, MODEL, PAYLOAD


class FakeModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.calls.append((self.path, dict(self.headers), json.loads(body)))
        data = json.dumps({"model": MODEL, "choices": [{"message": {"content": '{"atoms":["synthetic"]}'},
                                       "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        cls.model.calls = []
        cls.model_thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.model_thread.start()
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.port = cls.sock.getsockname()[1]
        cls.output = io.StringIO()
        cls.handler = logging.StreamHandler(cls.output)
        cls.loggers = [logging.getLogger(name) for name in ("uvicorn.error", "uvicorn.access", "httpx", "httpcore")]
        cls.levels = [logger.level for logger in cls.loggers]
        for logger in cls.loggers:
            logger.addHandler(cls.handler)
            logger.setLevel(logging.CRITICAL)
        config = uvicorn.Config(create_app(Settings(BEARER, MODEL, cls.model.server_port, 0.3)),
                                access_log=False, log_config=None, log_level="critical",
                                limit_concurrency=16, proxy_headers=False, server_header=False,
                                http=BoundedH11Protocol, ws="none", h11_max_incomplete_event_size=16 * 1024)
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.server.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not cls.server.started:
            raise RuntimeError("test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.model.shutdown()
        cls.model.server_close()
        cls.model_thread.join(5)
        cls.sock.close()
        for logger, level in zip(cls.loggers, cls.levels):
            logger.removeHandler(cls.handler)
            logger.setLevel(level)
        if cls.thread.is_alive():
            raise RuntimeError("test gateway did not stop")

    def raw(self, request):
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as sock:
            sock.sendall(request)
            result = b""
            while True:
                data = sock.recv(65536)
                if not data:
                    return result
                result += data

    def request_bytes(self, headers=b"", body=b"", path=b"/v1/chat/completions"):
        return (b"POST " + path + b" HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
                + b"Authorization: Bearer " + BEARER.encode() + b"\r\nContent-Type: application/json\r\n"
                + headers + b"\r\n" + body)

    def test_native_completion_and_no_sensitive_logs(self):
        with httpx.Client(trust_env=False) as client:
            result = client.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        self.assertEqual(result.status_code, 200)
        path, headers, payload = self.model.calls[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertIs(payload["stream"], False)
        self.assertNotIn("authorization", {key.lower() for key in headers})
        self.assertNotIn(BEARER, self.output.getvalue())
        self.assertNotIn("Synthetic requirement", self.output.getvalue())

    def test_duplicate_content_length_rejected_by_parser(self):
        before = len(self.model.calls)
        result = self.raw(self.request_bytes(b"Content-Length: 1\r\nContent-Length: 2\r\n", b"{}"))
        self.assertIn(b" 400 ", result.split(b"\r\n", 1)[0])
        self.assertEqual(len(self.model.calls), before)

    def test_cl_te_rejected_and_not_forwarded(self):
        before = len(self.model.calls)
        result = self.raw(self.request_bytes(b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n", b"0\r\n\r\n"))
        self.assertIn(b" 400 ", result.split(b"\r\n", 1)[0])
        self.assertEqual(len(self.model.calls), before)

    def test_duplicate_bearer_rejected(self):
        before = len(self.model.calls)
        result = self.raw(self.request_bytes(b"Authorization: Bearer wrong\r\nContent-Length: 2\r\n", b"{}"))
        self.assertIn(b" 401 ", result.split(b"\r\n", 1)[0])
        self.assertEqual(len(self.model.calls), before)

    def test_incomplete_body_total_deadline(self):
        before = len(self.model.calls)
        start = time.monotonic()
        result = self.raw(self.request_bytes(b"Content-Length: 500\r\n", b"{"))
        self.assertIn(b" 504 ", result.split(b"\r\n", 1)[0])
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(len(self.model.calls), before)

    def test_parser_bounds_incomplete_header_size(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as sock:
            sock.sendall(b"GET /v1/models HTTP/1.1\r\nHost: localhost\r\nX-Padding: " + b"x" * 20000)
            result = sock.recv(65536)
        self.assertIn(b" 400 ", result.split(b"\r\n", 1)[0])

    def test_pipelined_management_request_never_forwarded(self):
        before = len(self.model.calls)
        first = self.request_bytes(b"Content-Length: 0\r\n", path=b"/props")
        result = self.raw(first + first)
        self.assertIn(b" 404 ", result.split(b"\r\n", 1)[0])
        self.assertEqual(len(self.model.calls), before)


if __name__ == "__main__":
    unittest.main()
