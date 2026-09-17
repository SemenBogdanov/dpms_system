"""Synthetic-only boundary tests. No DPMS settings, database, or credential files."""

import asyncio
from contextlib import asynccontextmanager
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.responses import JSONResponse

from gateway import (
    MAX_INFERENCE_DEADLINE_SECONDS,
    MAX_PROMPT_CHARS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    Settings,
    create_app,
)

BEARER = "test-only-not-a-real-credential-" + "x" * 32
MODEL = "synthetic-local-model"
HEADERS = {"Authorization": "Bearer " + BEARER}
PAYLOAD = {"model": MODEL, "messages": [{"role": "user", "content": "Synthetic requirement"}],
           "max_tokens": 512, "temperature": 0.2}


def response(data=None, *, status=200, raw=None, headers=None):
    body = raw if raw is not None else json.dumps(data).encode()
    return httpx.Response(status, stream=httpx.ByteStream(body),
                          headers={"Content-Type": "application/json", **(headers or {})})


def completed():
    return response({"model": MODEL, "choices": [{"message": {"content": '{"atoms": ["synthetic"]}'},
                                  "finish_reason": "stop"}],
                     "internal_path": "/private/do-not-return", "prompt": "do-not-return"})


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def client(self, handler=None, deadline=1):
        self.calls = []

        async def upstream(request):
            self.calls.append(request)
            return await handler(request) if handler else completed()

        app = create_app(Settings(BEARER, MODEL, deadline_seconds=deadline),
                         transport=httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
                yield client

    async def test_dpms_payload_and_redacted_result(self):
        async with self.client() as client:
            result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["choices"][0]["message"]["content"], '{"atoms": ["synthetic"]}')
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertNotIn("do-not-return", result.text)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(str(self.calls[0].url), "http://127.0.0.1:8080/v1/chat/completions")
        self.assertNotIn("authorization", self.calls[0].headers)
        self.assertIs(json.loads(self.calls[0].content)["stream"], False)

    async def test_no_upstream_without_exact_bearer(self):
        async with self.client() as client:
            for value in (None, "", "Bearer wrong", "Basic " + BEARER, "Bearer " + BEARER + " "):
                with self.subTest(value=value is None):
                    result = await client.post("/v1/chat/completions", json=PAYLOAD,
                                               headers={} if value is None else {"Authorization": value})
                    self.assertEqual(result.status_code, 401)
        self.assertEqual(self.calls, [])

    async def test_duplicate_bearer_blocked(self):
        async with self.client() as client:
            result = await client.post("/v1/chat/completions", json=PAYLOAD,
                                      headers=[("authorization", "Bearer " + BEARER)] * 2)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(self.calls, [])

    async def test_browser_origin_blocked(self):
        async with self.client() as client:
            for origin in ("https://example.invalid", "null", ""):
                result = await client.post("/v1/chat/completions", json=PAYLOAD,
                                           headers={**HEADERS, "Origin": origin})
                self.assertEqual(result.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_closed_routes_and_methods(self):
        async with self.client() as client:
            routes = ("/", "/docs", "/openapi.json", "/slots", "/props", "/health", "/metrics",
                      "/v1/chat/completions/", "/v1/chat/completions?url=http://example.invalid",
                      "/v1/chat/%63ompletions", "/v1/chat/completions/control", "/completion")
            for path in routes:
                with self.subTest(path=path):
                    self.assertEqual((await client.post(path, headers=HEADERS)).status_code, 404)
            for method in ("OPTIONS", "PUT", "DELETE", "HEAD", "CONNECT", "TRACE"):
                self.assertEqual((await client.request(method, "/v1/models", headers=HEADERS)).status_code, 404)
        self.assertEqual(self.calls, [])

    async def test_text_only_and_model_pin(self):
        candidates = [({**PAYLOAD, "model": "different"}, 404),
                      ({**PAYLOAD, "stream": True}, 400),
                      ({**PAYLOAD, "stream": 0}, 400),
                      ({**PAYLOAD, "tools": []}, 400),
                      ({**PAYLOAD, "messages": [{"role": "user", "content": [{"type": "image_url"}]}]}, 400),
                      ({**PAYLOAD, "messages": [{"role": "user", "content": "x", "tool_calls": []}]}, 400),
                      ({**PAYLOAD, "messages": [{"role": "tool", "content": "x"}]}, 400),
                      ({**PAYLOAD, "messages": []}, 400), ({**PAYLOAD, "messages": PAYLOAD["messages"] * 41}, 400),
                      ({**PAYLOAD, "max_tokens": True}, 400), ({**PAYLOAD, "max_tokens": 4097}, 400),
                      ({**PAYLOAD, "temperature": True}, 400), ({**PAYLOAD, "temperature": -1}, 400)]
        async with self.client() as client:
            for payload, status in candidates:
                with self.subTest(payload=payload):
                    self.assertEqual((await client.post("/v1/chat/completions", json=payload, headers=HEADERS)).status_code, status)
        self.assertEqual(self.calls, [])

    async def test_invalid_json_does_not_echo_values(self):
        async with self.client() as client:
            for body in (b'{"model":"private-marker","model":"duplicate"}',
                         b'{"temperature": NaN}', b'{"temperature": Infinity}', b'\xff', b'"private-marker"',
                         b'[' * 2000):
                result = await client.post("/v1/chat/completions", content=body,
                                           headers={**HEADERS, "Content-Type": "application/json"})
                self.assertEqual(result.status_code, 400)
                self.assertNotIn("private-marker", result.text)
        self.assertEqual(self.calls, [])

    async def test_request_bounds(self):
        async with self.client() as client:
            large = {**PAYLOAD, "messages": [{"role": "user", "content": "x" * (MAX_PROMPT_CHARS + 1)}]}
            self.assertEqual((await client.post("/v1/chat/completions", json=large, headers=HEADERS)).status_code, 413)
            self.assertEqual((await client.post("/v1/chat/completions", content=b"x" * (MAX_REQUEST_BYTES + 1),
                                               headers={**HEADERS, "Content-Type": "application/json"})).status_code, 413)
        self.assertEqual(self.calls, [])

    async def test_encoded_body_rejected(self):
        async with self.client() as client:
            for header in ({"Content-Encoding": "gzip"}, {"Transfer-Encoding": "chunked"},
                           {"Content-Length": "-1"}, {"Content-Type": "text/plain"}):
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers={**HEADERS, **header})
                self.assertIn(result.status_code, (400, 415))
        self.assertEqual(self.calls, [])

    async def test_models_returns_only_configured_loaded_model(self):
        async def upstream(request):
            return response({"data": [{"id": MODEL, "meta": "private"}, {"id": "other-private-model"}]})
        async with self.client(upstream) as client:
            result = await client.get("/v1/models", headers=HEADERS)
        self.assertEqual(result.json(), {"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    async def test_models_unloaded(self):
        async def upstream(request):
            return response({"data": [{"id": "other"}]})
        async with self.client(upstream) as client:
            self.assertEqual((await client.get("/v1/models", headers=HEADERS)).status_code, 503)

    async def test_errors_redirects_do_not_leak_or_retry(self):
        for upstream_status, expected in ((301, 502), (307, 502), (400, 502), (401, 502), (404, 502), (429, 429), (500, 503), (503, 503)):
            async def upstream(request):
                return response({"error": "private-marker"}, status=upstream_status,
                                headers={"Location": "https://example.invalid", "Retry-After": "900"})
            async with self.client(upstream) as client:
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            with self.subTest(status=upstream_status):
                self.assertEqual(result.status_code, expected)
                self.assertNotIn("private-marker", result.text)
                self.assertNotIn("location", result.headers)
                self.assertEqual(len(self.calls), 1)

    async def test_upstream_offline_no_fallback_and_recovery(self):
        failing = True
        async def upstream(request):
            if failing:
                raise httpx.ConnectError("private-marker", request=request)
            return completed()
        async with self.client(upstream) as client:
            result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("private-marker", result.text)
            failing = False
            self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 200)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(call.url.host == "127.0.0.1" for call in self.calls))

    async def test_inference_timeout_requires_verified_recovery(self):
        async def upstream(request):
            await asyncio.sleep(0.1)
            return completed()
        async with self.client(upstream, deadline=0.02) as client:
            timed_out = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(timed_out.status_code, 504)
            self.assertEqual(timed_out.headers["x-dpms-local-gateway-error"], "local_model_timeout")
            result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json()["error"]["code"], "local_model_recovery_required")
        self.assertEqual(len(self.calls), 1)

    async def test_broken_upstream_response_does_not_start_second_generation(self):
        async def upstream(request):
            raise httpx.RemoteProtocolError("private-marker")
        async with self.client(upstream) as client:
            for _ in range(2):
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                self.assertEqual(result.status_code, 503)
                self.assertNotIn("private-marker", result.text)
        self.assertEqual(len(self.calls), 1)

    async def test_concurrency_no_hidden_queue(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def upstream(request):
            entered.set()
            await release.wait()
            return completed()
        async with self.client(upstream) as client:
            first = asyncio.create_task(client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS))
            await entered.wait()
            second = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.headers["retry-after"], "5")
            release.set()
            self.assertEqual((await first).status_code, 200)
        self.assertEqual(len(self.calls), 1)

    async def test_invalid_or_incomplete_responses(self):
        bad = ({}, [], {"model": MODEL, "choices": []},
               {"model": MODEL, "choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
               {"model": MODEL, "choices": [{"message": {"content": "cut-off"}, "finish_reason": "length"}]},
               {"model": "different", "choices": [{"message": {"content": "wrong-model"}, "finish_reason": "stop"}]})
        for data in bad:
            async def upstream(request):
                return response(data)
            async with self.client(upstream) as client:
                self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 502)

    async def test_response_byte_limits_and_encoding(self):
        cases = [(b"x" * (MAX_RESPONSE_BYTES + 1), {}), (b"{}", {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}),
                 (b"{}", {"Content-Encoding": "gzip"}), (b"{}", {"Content-Type": "text/html"}),
                 (b'{"private":"marker","private":1}', {})]
        for body, headers in cases:
            async def upstream(request):
                return response(raw=body, headers=headers)
            async with self.client(upstream) as client:
                self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 502)

    async def test_early_upstream_rejection_requires_recovery(self):
        cases = [(b"{}", {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}),
                 (b"{}", {"Content-Type": "text/html"}), (b"{}", {"Content-Encoding": "gzip"}),
                 (b"x" * (MAX_RESPONSE_BYTES + 1), {})]
        for body, headers in cases:
            async def upstream(request):
                return response(raw=body, headers=headers)
            async with self.client(upstream) as client:
                first = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                second = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(first.status_code, 502)
            self.assertEqual(second.json()["error"]["code"], "local_model_recovery_required")
            self.assertEqual(len(self.calls), 1)

    async def test_invalid_unicode_or_huge_number_does_not_poison_gateway(self):
        async with self.client() as client:
            for payload in ({**PAYLOAD, "messages": [{"role": "user", "content": "\ud800"}]},
                            {**PAYLOAD, "temperature": 10 ** 400}):
                result = await client.post("/v1/chat/completions", content=json.dumps(payload).encode(),
                                           headers={**HEADERS, "Content-Type": "application/json"})
                self.assertEqual(result.status_code, 400)
                self.assertEqual(self.calls, [])
            self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 200)
        self.assertEqual(len(self.calls), 1)

    async def test_final_serialized_response_limit_exact_and_plus_one(self):
        def normalized(content):
            return {"object": "chat.completion", "model": MODEL, "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}
        overhead = len(JSONResponse(normalized("")).body)
        for delta, status in ((0, 200), (1, 502)):
            text = "x" * (MAX_RESPONSE_BYTES - overhead + delta)
            data = {"model": MODEL, "choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
            raw = json.dumps(data, separators=(",", ":")).encode()
            self.assertLessEqual(len(raw), MAX_RESPONSE_BYTES)
            async def upstream(request):
                return response(raw=raw)
            async with self.client(upstream) as client:
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
            self.assertEqual(result.status_code, status)
            if delta == 0:
                self.assertEqual(len(result.content), MAX_RESPONSE_BYTES)

    async def test_proxy_environment_is_ignored(self):
        with patch.dict("os.environ", {"HTTP_PROXY": "http://example.invalid:1", "ALL_PROXY": "http://example.invalid:1"}):
            async with self.client() as client:
                self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 200)
        self.assertEqual(self.calls[0].url.host, "127.0.0.1")

    def test_settings_fail_closed_and_repr_redacted(self):
        self.assertNotIn(BEARER, repr(Settings(BEARER, MODEL)))
        for bearer in ("", "short", "x" * 42, "x" * 257, "x" * 43 + "\n"):
            with self.assertRaises(ValueError):
                Settings(bearer, MODEL)
        for model in ("", "x" * 201, "line\nbreak"):
            with self.assertRaises(ValueError):
                Settings(BEARER, model)
        self.assertEqual(Settings(BEARER, MODEL).deadline_seconds, 900)
        for deadline in (False, 0, MAX_INFERENCE_DEADLINE_SECONDS + 1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                Settings(BEARER, MODEL, deadline_seconds=deadline)


if __name__ == "__main__":
    unittest.main()
