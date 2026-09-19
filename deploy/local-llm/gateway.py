"""Loopback-only DPMS adapter. Publish only behind reviewed private HTTPS Serve."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hmac
import json
import math
import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
from recovery_state import RecoveryState
from bounded_transport import BoundedH11Protocol

MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROMPT_CHARS = 60_000
MAX_RESPONSE_FORMAT_BYTES = 64 * 1024
MAX_INFERENCE_DEADLINE_SECONDS = 900.0


@dataclass(frozen=True)
class Settings:
    bearer: str = field(repr=False)
    model: str
    upstream_port: int = 8080
    deadline_seconds: float = MAX_INFERENCE_DEADLINE_SECONDS
    state_directory: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,256}", self.bearer):
            raise ValueError("Supply a random URL-safe bearer of at least 32 bytes")
        if not self.model.strip() or len(self.model) > 200 or any(ord(c) < 32 for c in self.model):
            raise ValueError("Supply the exact local model identifier")
        self.model.encode("utf-8")
        if type(self.upstream_port) is not int or not 1024 <= self.upstream_port <= 65535:
            raise ValueError("Invalid loopback port")
        if (
            type(self.deadline_seconds) not in (int, float)
            or not math.isfinite(self.deadline_seconds)
            or not 0 < self.deadline_seconds <= MAX_INFERENCE_DEADLINE_SECONDS
        ):
            raise ValueError("Deadline must be positive and no longer than 15 minutes")


class GatewayError(Exception):
    def __init__(self, status: int, code: str, *, inference_uncertain: bool = False):
        self.status = status
        self.code = code
        self.inference_uncertain = inference_uncertain


def error(status: int, code: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store", "X-DPMS-Local-Gateway-Error": code}
    if status in (429, 503):
        headers["Retry-After"] = "5"
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse({"error": {"code": code, "message": code}}, status_code=status, headers=headers)


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("duplicate field")
            result[name] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def validate_response_format(value) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"type", "json_schema"}:
        raise GatewayError(400, "invalid_response_format")
    wrapper = value.get("json_schema")
    if value.get("type") != "json_schema" or not isinstance(wrapper, dict):
        raise GatewayError(400, "invalid_response_format")
    if set(wrapper) != {"name", "strict", "schema"}:
        raise GatewayError(400, "invalid_response_format")
    name = wrapper.get("name")
    schema = wrapper.get("schema")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
        or wrapper.get("strict") is not True
        or not isinstance(schema, dict)
        or schema.get("type") != "object"
    ):
        raise GatewayError(400, "invalid_response_format")

    nodes = 0

    def validate_node(node, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 20 or nodes > 2_000:
            raise GatewayError(400, "invalid_response_format")
        if isinstance(node, dict):
            for key, item in node.items():
                if not isinstance(key, str) or len(key) > 100:
                    raise GatewayError(400, "invalid_response_format")
                if key == "$ref" and (not isinstance(item, str) or not item.startswith("#/")):
                    raise GatewayError(400, "invalid_response_format")
                validate_node(item, depth + 1)
        elif isinstance(node, list):
            for item in node:
                validate_node(item, depth + 1)
        elif isinstance(node, str):
            if len(node) > 4_000:
                raise GatewayError(400, "invalid_response_format")
        elif isinstance(node, float) and not math.isfinite(node):
            raise GatewayError(400, "invalid_response_format")
        elif node is not None and type(node) not in {bool, int, float}:
            raise GatewayError(400, "invalid_response_format")

    validate_node(value)
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_RESPONSE_FORMAT_BYTES:
        raise GatewayError(400, "invalid_response_format")
    return value


def validate_payload(value, model: str) -> dict:
    allowed = {"model", "messages", "max_tokens", "temperature", "stream", "response_format"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise GatewayError(400, "unsupported_fields")
    if value.get("model") != model:
        raise GatewayError(404, "model_not_allowed")
    if value.get("stream", False) is not False:
        raise GatewayError(400, "streaming_not_supported")
    messages = value.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
        raise GatewayError(400, "invalid_messages")
    total = 0
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise GatewayError(400, "text_messages_only")
        if message["role"] not in ("system", "user", "assistant") or not isinstance(message["content"], str):
            raise GatewayError(400, "text_messages_only")
        try:
            message["content"].encode("utf-8")
        except UnicodeError:
            raise GatewayError(400, "invalid_unicode") from None
        total += len(message["content"])
    if total > MAX_PROMPT_CHARS:
        raise GatewayError(413, "prompt_too_large")
    limit = value.get("max_tokens", 512)
    temperature = value.get("temperature", 0.2)
    if type(limit) is not int or not 1 <= limit <= 4096:
        raise GatewayError(400, "invalid_max_tokens")
    if type(temperature) not in (int, float) or not 0 <= temperature <= 2:
        raise GatewayError(400, "invalid_temperature")
    result = {"model": model, "messages": messages, "max_tokens": limit,
              "temperature": temperature, "stream": False}
    response_format = validate_response_format(value.get("response_format"))
    if response_format is not None:
        result["response_format"] = response_format
    return result


async def read_payload(request: Request) -> bytes:
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or (lengths and not re.fullmatch(r"[0-9]{1,9}", lengths[0])):
        raise GatewayError(400, "invalid_length")
    if request.headers.get("transfer-encoding"):
        raise GatewayError(400, "transfer_encoding_not_supported")
    if request.headers.get("content-encoding", "identity") != "identity":
        raise GatewayError(415, "encoded_body_not_supported")
    if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
        raise GatewayError(413, "request_too_large")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise GatewayError(415, "json_required")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            raise GatewayError(413, "request_too_large")
    if lengths and len(body) != int(lengths[0]):
        raise GatewayError(400, "invalid_length")
    return bytes(body)


async def upstream_json(client: httpx.AsyncClient, method: str, path: str, payload=None):
    # No inbound header, host, credential, URL or proxy is forwarded to llama.cpp.
    async with client.stream(method, path, json=payload if method == "POST" else None) as response:
        if response.status_code == 429:
            # A complete explicit refusal is retryable; a broken/oversized error
            # response is ambiguous and must retain the crash marker.
            size = 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > 32 * 1024:
                    raise GatewayError(502, "invalid_model_response", inference_uncertain=True)
            raise GatewayError(429, "local_model_busy")
        if response.status_code in (400, 422):
            # A complete 4xx response is proof that inference never started.
            # Preserve that distinction so DPMS can retry once without JSON Schema.
            size = 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > 32 * 1024:
                    raise GatewayError(502, "invalid_model_response", inference_uncertain=True)
            raise GatewayError(400, "local_model_rejected_request")
        if response.is_redirect:
            raise GatewayError(502, "upstream_redirect_blocked", inference_uncertain=True)
        if response.status_code >= 500:
            raise GatewayError(503, "local_model_unavailable", inference_uncertain=True)
        if response.status_code != 200:
            raise GatewayError(502, "local_model_rejected_request", inference_uncertain=True)
        if response.headers.get("content-encoding", "identity") != "identity":
            raise GatewayError(502, "encoded_response_not_supported", inference_uncertain=True)
        if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise GatewayError(502, "invalid_model_response", inference_uncertain=True)
        length = response.headers.get("content-length")
        if length is not None and (not re.fullmatch(r"[0-9]{1,9}", length) or int(length) > MAX_RESPONSE_BYTES):
            raise GatewayError(502, "response_too_large", inference_uncertain=True)
        body = bytearray()
        async for chunk in response.aiter_raw():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise GatewayError(502, "response_too_large", inference_uncertain=True)
        try:
            return strict_json(bytes(body))
        except (ValueError, RecursionError):
            raise GatewayError(502, "invalid_model_response") from None


def create_app(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    recovery = RecoveryState(settings.state_directory) if settings.state_directory else None
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{settings.upstream_port}",
            timeout=httpx.Timeout(settings.deadline_seconds, connect=3.0),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            follow_redirects=False, trust_env=False, transport=transport,
            headers={"Accept-Encoding": "identity"},
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.state.busy = False
    app.state.recovery_required = bool(recovery and recovery.pending)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        # Serve strips network identity into a loopback proxy: ACLs are a separate gate.
        # Browser/CORS use is not supported, including authenticated cross-origin calls.
        if request.headers.getlist("origin"):
            return error(403, "browser_access_blocked")
        values = request.headers.getlist("authorization")
        expected = ("Bearer " + settings.bearer).encode("ascii")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode("utf-8"), expected):
            return error(401, "invalid_credentials")
        path = request.scope.get("raw_path", b"").decode("ascii", errors="replace")
        if request.scope.get("query_string") or (request.method, path) not in {
            ("GET", "/v1/models"), ("POST", "/v1/chat/completions"),
        }:
            return error(404, "route_not_allowed")
        return await call_next(request)

    async def execute(request: Request, *, models: bool):
        if not models and app.state.recovery_required:
            return error(503, "local_model_recovery_required")
        # Event-loop-local admission is atomic until the first await; no hidden queue.
        if app.state.busy:
            return error(429, "local_model_busy")
        app.state.busy = True
        inference_started = False
        inference_finished_safely = False
        try:
            async with asyncio.timeout(settings.deadline_seconds):
                payload = None
                if not models:
                    raw = await read_payload(request)
                    try:
                        payload = validate_payload(strict_json(raw), settings.model)
                    except (ValueError, RecursionError):
                        raise GatewayError(400, "invalid_json") from None
                if not models and recovery:
                    try:
                        recovery.begin()
                    except (OSError, RuntimeError):
                        app.state.recovery_required = True
                        raise GatewayError(503, "local_model_recovery_required") from None
                inference_started = not models
                data = await upstream_json(app.state.client, request.method, request.url.path, payload)
                if models:
                    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                        raise GatewayError(502, "invalid_model_response")
                    if not any(isinstance(item, dict) and item.get("id") == settings.model for item in data["data"]):
                        raise GatewayError(503, "configured_model_not_loaded")
                    result = {"object": "list", "data": [{"id": settings.model, "object": "model"}]}
                else:
                    if not isinstance(data, dict) or data.get("model") != settings.model:
                        raise GatewayError(502, "response_model_mismatch")
                    try:
                        choice = data["choices"][0]
                        content = choice["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        raise GatewayError(502, "invalid_model_response") from None
                    if not isinstance(content, str) or not content.strip():
                        raise GatewayError(502, "empty_model_response")
                    if choice.get("finish_reason") != "stop":
                        raise GatewayError(502, "incomplete_model_response")
                    inference_finished_safely = True
                    result = {"object": "chat.completion", "model": settings.model, "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"},
                    ]}
                outgoing = JSONResponse(result, headers={"Cache-Control": "no-store"})
                if len(outgoing.body) > MAX_RESPONSE_BYTES:
                    raise GatewayError(502, "response_too_large")
                return outgoing
        except GatewayError as exc:
            if exc.code in {"local_model_busy", "local_model_rejected_request"} and not exc.inference_uncertain:
                inference_finished_safely = True
            app.state.recovery_required |= inference_started and exc.inference_uncertain
            return error(exc.status, exc.code)
        except (httpx.ConnectTimeout, httpx.ConnectError):
            inference_finished_safely = True
            return error(503, "local_model_unavailable")
        except (TimeoutError, httpx.TimeoutException):
            # A closed socket is not proof that llama stopped generating. Fail closed
            # until an operator confirms it is idle and restarts this gateway.
            app.state.recovery_required |= inference_started
            return error(504, "local_model_timeout")
        except httpx.HTTPError:
            app.state.recovery_required |= inference_started
            return error(503, "local_model_unavailable")
        except asyncio.CancelledError:
            app.state.recovery_required |= inference_started
            raise
        except Exception:
            # Upstream errors can contain a prompt or local path: never echo/log them.
            app.state.recovery_required |= inference_started
            return error(502, "gateway_error")
        finally:
            if inference_started and not inference_finished_safely:
                app.state.recovery_required = True
            if inference_started and recovery and not app.state.recovery_required:
                try:
                    recovery.finish()
                except (OSError, RuntimeError):
                    app.state.recovery_required = True
            app.state.busy = False

    @app.get("/v1/models")
    async def models(request: Request):
        return await execute(request, models=True)

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        return await execute(request, models=False)

    return app


def main():
    import uvicorn

    try:
        settings = Settings(bearer=os.environ.pop("DPMS_LOCAL_LLM_BEARER", ""),
                            model=os.environ.get("DPMS_LOCAL_LLM_MODEL", ""),
                            state_directory=os.environ.get("DPMS_LOCAL_LLM_STATE_DIRECTORY") or str(
                                Path.home() / "Library/Application Support/DPMSLocalLLM/state"))
        port = int(os.environ.get("DPMS_LOCAL_LLM_PORT", "18080"))
        if not 1024 <= port <= 65535 or port == settings.upstream_port:
            raise ValueError("Invalid gateway port")
    except (ValueError, TypeError):
        raise SystemExit("Invalid gateway configuration; model and random bearer are required") from None
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, workers=1,
                limit_concurrency=16, backlog=16, timeout_keep_alive=2,
                timeout_graceful_shutdown=85, access_log=False, log_level="critical",
                proxy_headers=False, server_header=False, http=BoundedH11Protocol,
                h11_max_incomplete_event_size=16 * 1024, ws="none")


if __name__ == "__main__":
    main()
