"""Bounded OpenAI-compatible client used by server-side DPMS features."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import ssl
from typing import Any, TYPE_CHECKING
from uuid import UUID
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.integration_crypto import get_integration_secret, integration_secret_configured
if TYPE_CHECKING:
    from app.models.ai_provider import AIProviderConfig


MAX_AI_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_AI_PROMPT_CHARS = 60_000


class AIProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
        *,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        seconds = int(float(value.strip()))
    except (TypeError, ValueError, OverflowError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return max(1, min(seconds, 3600))


def _integration_secret() -> str:
    value = get_integration_secret()
    if len(value) < 32:
        raise AIProviderError(
            "encryption_key_not_configured",
            "На сервере DPMS не настроен отдельный ключ интеграций",
            503,
        )
    return value


def ai_secret_configured() -> bool:
    return integration_secret_configured()


def _fernet() -> Fernet:
    material = sha256(b"dpms:ai-provider:credentials-v1:" + _integration_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_ai_api_key(api_key: str) -> str:
    if not api_key.strip():
        raise AIProviderError("api_key_required", "Укажите API key", 422)
    return "v1:" + _fernet().encrypt(api_key.strip().encode("utf-8")).decode("ascii")


def decrypt_ai_api_key(ciphertext: str) -> str:
    if not ciphertext.startswith("v1:"):
        raise AIProviderError("credential_version", "Версия сохраненного API key не поддерживается", 500)
    try:
        return _fernet().decrypt(ciphertext[3:].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise AIProviderError("credential_unavailable", "Не удалось расшифровать API key; сохраните его заново", 500)


def _canonical_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        raise AIProviderError("invalid_origin", "Некорректный API URL", 422)
    if parsed.scheme.lower() != "https":
        raise AIProviderError("https_required", "ИИ-провайдер можно подключить только по HTTPS", 422)
    if not parsed.hostname or parsed.username or parsed.password:
        raise AIProviderError("invalid_origin", "Укажите HTTPS-адрес без логина и пароля", 422)
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise AIProviderError("invalid_origin", "Некорректное имя хоста ИИ-провайдера", 422)
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}" if port in (None, 443) else f"https://{host}:{port}"


def normalize_ai_base_url(value: str) -> str:
    raw = value.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise AIProviderError("invalid_url", "Некорректный API URL", 422)
    if parsed.query or parsed.fragment:
        raise AIProviderError("invalid_url", "В API URL нельзя указывать query или fragment", 422)
    origin = _canonical_origin(raw)
    allowed: set[str] = set()
    for item in settings.AI_PROVIDER_ALLOWED_ORIGINS.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            allowed.add(_canonical_origin(item))
        except AIProviderError:
            continue
    if not allowed:
        raise AIProviderError(
            "allowlist_not_configured",
            "На сервере DPMS не настроен список разрешенных ИИ-провайдеров",
            503,
        )
    if origin not in allowed:
        raise AIProviderError("origin_not_allowed", "Этот ИИ-провайдер не разрешен конфигурацией сервера", 422)
    path = parsed.path.rstrip("/")
    if any(part in {".", ".."} for part in path.split("/")) or "\\" in path or len(path) > 300:
        raise AIProviderError("invalid_url", "Некорректный путь API", 422)
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    return origin + path


def ai_allowlist_configured() -> bool:
    for item in settings.AI_PROVIDER_ALLOWED_ORIGINS.split(","):
        if not item.strip():
            continue
        try:
            _canonical_origin(item)
            return True
        except AIProviderError:
            continue
    return False


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def ai_provider_ready(provider: "AIProviderConfig") -> bool:
    return bool(
        provider.enabled
        and provider.last_test_status == "ok"
        and provider.last_verified_config_version == provider.config_version
    )


async def get_ready_ai_provider(
    db: AsyncSession,
    provider_id: UUID | None = None,
) -> "AIProviderConfig":
    from app.models.ai_provider import AIProviderConfig

    query = select(AIProviderConfig).where(AIProviderConfig.provider_kind == "openai_compatible")
    if provider_id is not None:
        query = query.where(AIProviderConfig.id == provider_id)
    else:
        query = query.order_by(AIProviderConfig.created_at.asc(), AIProviderConfig.id.asc())
    provider = await db.scalar(query)
    if provider is None:
        raise AIProviderError("provider_missing", "ИИ-провайдер не настроен", 503)
    if not provider.enabled:
        raise AIProviderError("provider_disabled", "ИИ-провайдер отключен", 503)
    if not ai_provider_ready(provider):
        raise AIProviderError("provider_unverified", "Текущая версия ИИ-провайдера не проверена", 503)
    return provider


async def generate_text(
    provider: "AIProviderConfig",
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 512,
    temperature: float = 0.2,
    allow_disabled: bool = False,
    allow_unverified: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    if not provider.enabled and not allow_disabled:
        raise AIProviderError("provider_disabled", "ИИ-провайдер отключен", 409)
    if not allow_unverified and not ai_provider_ready(provider):
        raise AIProviderError("provider_unverified", "Текущая версия ИИ-провайдера не проверена", 409)
    if not messages or len(messages) > 40:
        raise AIProviderError("invalid_prompt", "Некорректный набор сообщений", 422)
    total_chars = 0
    clean_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise AIProviderError("invalid_prompt", "Некорректный формат сообщения", 422)
        total_chars += len(content)
        clean_messages.append({"role": role, "content": content})
    if total_chars > MAX_AI_PROMPT_CHARS:
        raise AIProviderError("prompt_too_large", "Запрос к ИИ превышает допустимый размер", 413)
    url = normalize_ai_base_url(provider.base_url).rstrip("/") + "/chat/completions"
    api_key = decrypt_ai_api_key(provider.api_key_ciphertext)
    timeout = httpx.Timeout(
        connect=settings.AI_PROVIDER_CONNECT_TIMEOUT_SECONDS,
        read=settings.AI_PROVIDER_READ_TIMEOUT_SECONDS,
        write=settings.AI_PROVIDER_READ_TIMEOUT_SECONDS,
        pool=settings.AI_PROVIDER_CONNECT_TIMEOUT_SECONDS,
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": provider.model_name,
        "messages": clean_messages,
        "max_tokens": max(1, min(max_tokens, 4096)),
        "temperature": max(0.0, min(temperature, 2.0)),
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=_ssl_context(),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.is_redirect:
                    raise AIProviderError("redirect_blocked", "ИИ-провайдер вернул redirect; проверьте точный API URL", 502)
                if response.status_code == 401:
                    raise AIProviderError("invalid_credentials", "ИИ-провайдер отклонил API key", 502)
                if response.status_code == 403:
                    raise AIProviderError(
                        "provider_access_forbidden",
                        "ИИ-провайдер запретил доступ; проверьте права API key, тариф и доступ к выбранной модели",
                        502,
                    )
                if response.status_code == 400:
                    raise AIProviderError(
                        "invalid_provider_request",
                        "Провайдер не принял параметры запроса; проверьте API URL и совместимость модели",
                        422,
                    )
                if response.status_code == 402:
                    raise AIProviderError(
                        "provider_balance_required",
                        "Провайдер отклонил запрос из-за баланса или тарифа",
                        402,
                    )
                if response.status_code == 404:
                    raise AIProviderError(
                        "model_or_endpoint_not_found",
                        "Провайдер не нашел endpoint или указанную модель",
                        422,
                    )
                if response.status_code == 429:
                    raise AIProviderError(
                        "rate_limited",
                        "Лимит запросов ИИ-провайдера исчерпан",
                        429,
                        retry_after_seconds=_parse_retry_after(response.headers.get("retry-after")),
                    )
                if response.status_code >= 500:
                    raise AIProviderError("provider_unavailable", "ИИ-провайдер временно недоступен", 503)
                if response.status_code < 200 or response.status_code >= 300:
                    raise AIProviderError("provider_error", "ИИ-провайдер отклонил запрос", 502)
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_AI_RESPONSE_BYTES:
                            raise AIProviderError("response_too_large", "Ответ ИИ-провайдера превышает допустимый размер", 502)
                    except ValueError:
                        raise AIProviderError("invalid_response", "ИИ-провайдер вернул некорректный размер ответа", 502)
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_AI_RESPONSE_BYTES:
                        raise AIProviderError("response_too_large", "Ответ ИИ-провайдера превышает допустимый размер", 502)
                    chunks.append(chunk)
                body = b"".join(chunks)
    except httpx.TimeoutException:
        raise AIProviderError("timeout", "ИИ-провайдер не ответил вовремя", 504)
    except (httpx.NetworkError, ssl.SSLError):
        raise AIProviderError("connection_failed", "Не удалось установить защищенное соединение с ИИ-провайдером", 502)
    finally:
        api_key = ""
        headers.clear()
    try:
        data: Any = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise AIProviderError("invalid_response", "ИИ-провайдер вернул некорректный ответ", 502)
    if not isinstance(content, str) or not content.strip():
        raise AIProviderError("empty_response", "ИИ-провайдер вернул пустой ответ", 502)
    return content.strip()
