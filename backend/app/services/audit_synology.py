"""Safe, bounded Synology File Station client for the Audit workspace."""

from __future__ import annotations

import base64
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import PurePosixPath
import re
import secrets
import ssl
from typing import Any, AsyncIterator
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
import httpx

from app.config import settings
from app.services.integration_crypto import get_integration_secret, integration_secret_configured


MAX_SYNOLOGY_FILES_PER_IMPORT = 20
MAX_SYNOLOGY_FILE_BYTES = 25 * 1024 * 1024
MAX_SYNOLOGY_BATCH_BYTES = 100 * 1024 * 1024
MAX_SYNOLOGY_LIST_LIMIT = 200
MAX_SYNOLOGY_JSON_BYTES = 2 * 1024 * 1024
SYNOLOGY_PREVIEW_TTL_SECONDS = 10 * 60
SYNOLOGY_PATH_TOKEN_TTL_SECONDS = 60 * 60
SYNOLOGY_SESSION_IDLE_TTL_SECONDS = 30 * 60
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx"}

_SAFE_API_PATH = re.compile(r"^[A-Za-z0-9_.\-/]+\.cgi$")
_ERROR_MESSAGES = {
    105: ("permission_denied", "Учетной записи Synology недостаточно прав"),
    106: ("session_expired", "Сессия Synology завершилась"),
    107: ("session_interrupted", "Сессия Synology была прервана другим входом"),
    119: ("session_missing", "Synology не распознал сессию"),
    400: ("invalid_credentials", "Неверное имя пользователя или пароль Synology"),
    401: ("account_disabled", "Учетная запись Synology отключена"),
    402: ("permission_denied", "Учетной записи Synology запрещен доступ"),
    403: ("two_factor_required", "Для учетной записи Synology требуется одноразовый код"),
    404: ("two_factor_failed", "Synology отклонил одноразовый код"),
    408: ("remote_not_found", "Файл или папка не найдены в Synology"),
}


class SynologyConnectorError(Exception):
    """Public, sanitized connector failure."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SynologyFileInfo:
    path: str
    name: str
    is_dir: bool
    size_bytes: int
    modified_at: int
    extension: str

    @property
    def selectable(self) -> bool:
        return (
            not self.is_dir
            and self.extension in SUPPORTED_DOCUMENT_EXTENSIONS
            and 0 < self.size_bytes <= MAX_SYNOLOGY_FILE_BYTES
        )


@dataclass(frozen=True)
class SynologyFolderPage:
    path: str
    offset: int
    total: int
    items: list[SynologyFileInfo]


def _key_material(domain: str) -> bytes:
    configured_secret = get_integration_secret(allow_legacy=True)
    if len(configured_secret) < 32:
        raise SynologyConnectorError(
            "encryption_key_not_configured",
            "На сервере DPMS не настроен отдельный ключ шифрования коннекторов",
            503,
        )
    secret = configured_secret.encode("utf-8")
    return sha256(b"dpms:audit-connector:" + domain.encode("ascii") + b":" + secret).digest()


def connector_secret_configured() -> bool:
    return integration_secret_configured(allow_legacy=True)


def _credential_fernet(connection_id: UUID) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_key_material(f"credentials:{connection_id}:v1")))


def encrypt_synology_password(password: str, connection_id: UUID) -> str:
    if not password:
        raise SynologyConnectorError("password_required", "Укажите пароль Synology", 422)
    return "v1:" + _credential_fernet(connection_id).encrypt(password.encode("utf-8")).decode("ascii")


def decrypt_synology_password(ciphertext: str | None, connection_id: UUID) -> str:
    if not ciphertext:
        raise SynologyConnectorError(
            "credential_missing",
            "Для профиля не сохранен пароль; проверьте и сохраните подключение заново",
            409,
        )
    if not ciphertext.startswith("v1:"):
        raise SynologyConnectorError(
            "credential_version",
            "Версия сохраненного пароля не поддерживается",
            500,
        )
    try:
        return _credential_fernet(connection_id).decrypt(ciphertext[3:].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise SynologyConnectorError(
            "credential_unavailable",
            "Не удалось расшифровать пароль; сохраните профиль заново",
            500,
        )


def _canonical_https_origin(value: str) -> str:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise SynologyConnectorError("invalid_origin", "Некорректный адрес Synology", 422)
    if parsed.scheme.lower() != "https":
        raise SynologyConnectorError("https_required", "Synology можно подключить только по HTTPS", 422)
    if not parsed.hostname or parsed.username or parsed.password:
        raise SynologyConnectorError("invalid_origin", "Укажите HTTPS-адрес без логина и пароля", 422)
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise SynologyConnectorError("invalid_origin", "В адресе Synology нельзя указывать путь, query или fragment", 422)
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise SynologyConnectorError("invalid_origin", "Некорректное имя хоста Synology", 422)
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == 443:
        return f"https://{host}"
    return f"https://{host}:{port}"


def normalize_synology_base_url(value: str) -> str:
    origin = _canonical_https_origin(value)
    configured = [part.strip() for part in settings.SYNOLOGY_ALLOWED_ORIGINS.split(",") if part.strip()]
    if not configured:
        raise SynologyConnectorError(
            "allowlist_not_configured",
            "На сервере DPMS не настроен список разрешенных адресов Synology",
            503,
        )
    allowed: set[str] = set()
    for item in configured:
        try:
            allowed.add(_canonical_https_origin(item))
        except SynologyConnectorError:
            continue
    if origin not in allowed:
        raise SynologyConnectorError(
            "origin_not_allowed",
            "Этот адрес Synology не разрешен конфигурацией сервера DPMS",
            422,
        )
    return origin


def synology_allowlist_configured() -> bool:
    for item in settings.SYNOLOGY_ALLOWED_ORIGINS.split(","):
        if not item.strip():
            continue
        try:
            _canonical_https_origin(item)
            return True
        except SynologyConnectorError:
            continue
    return False


def normalize_remote_path(value: str) -> str:
    raw = value.strip()
    if not raw.startswith("/") or "\x00" in raw or "\\" in raw or len(raw) > 1000:
        raise SynologyConnectorError("invalid_path", "Некорректный путь Synology", 422)
    if raw == "/":
        return raw
    raw = raw.rstrip("/")
    parts = raw[1:].split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SynologyConnectorError("invalid_path", "Некорректный путь Synology", 422)
    return "/" + "/".join(parts)


def normalize_root_path(value: str) -> str:
    return normalize_remote_path(value)


def ensure_path_within_root(path: str, root_path: str) -> str:
    normalized = normalize_remote_path(path)
    root = normalize_root_path(root_path)
    if root == "/":
        return normalized
    path_parts = PurePosixPath(normalized).parts
    root_parts = PurePosixPath(root).parts
    if path_parts[: len(root_parts)] != root_parts:
        raise SynologyConnectorError("path_outside_root", "Путь находится вне разрешенной папки Synology", 403)
    return normalized


def remote_path_fingerprint(base_url: str, path: str) -> str:
    message = f"{normalize_synology_base_url(base_url)}:{normalize_remote_path(path)}".encode("utf-8")
    return hmac.new(_key_material("remote-path-v2"), message, sha256).hexdigest()


def build_path_token(*, connection_id: UUID, config_version: int, user_id: UUID, path: str) -> str:
    payload = {
        "v": 1,
        "connection_id": str(connection_id),
        "config_version": config_version,
        "user_id": str(user_id),
        "path": normalize_remote_path(path),
    }
    key = base64.urlsafe_b64encode(_key_material("path-token-v1"))
    return Fernet(key).encrypt(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")


def verify_path_token(
    token: str,
    *,
    connection_id: UUID,
    config_version: int,
    user_id: UUID,
) -> str:
    key = base64.urlsafe_b64encode(_key_material("path-token-v1"))
    try:
        raw = Fernet(key).decrypt(token.encode("ascii"), ttl=SYNOLOGY_PATH_TOKEN_TTL_SECONDS)
        payload = json.loads(raw)
    except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise SynologyConnectorError("invalid_path_token", "Ссылка на папку или файл устарела", 409)
    if (
        payload.get("v") != 1
        or payload.get("connection_id") != str(connection_id)
        or payload.get("config_version") != config_version
        or payload.get("user_id") != str(user_id)
    ):
        raise SynologyConnectorError("invalid_path_token", "Ссылка принадлежит другому подключению", 409)
    return normalize_remote_path(str(payload.get("path") or ""))


def build_preview_token(
    *,
    connection_id: UUID,
    config_version: int,
    user_id: UUID,
    files: list[SynologyFileInfo],
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    payload = {
        "v": 1,
        "connection_id": str(connection_id),
        "config_version": config_version,
        "user_id": str(user_id),
        "expires_at": issued_at + SYNOLOGY_PREVIEW_TTL_SECONDS,
        "files": [
            {"path": item.path, "size_bytes": item.size_bytes, "modified_at": item.modified_at}
            for item in sorted(files, key=lambda item: item.path)
        ],
    }
    key = base64.urlsafe_b64encode(_key_material("preview-v1"))
    return Fernet(key).encrypt(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")


def verify_preview_token(token: str, *, user_id: UUID, now: int | None = None) -> dict[str, Any]:
    key = base64.urlsafe_b64encode(_key_material("preview-v1"))
    try:
        payload = json.loads(Fernet(key).decrypt(token.encode("ascii")))
    except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise SynologyConnectorError("invalid_preview", "Предварительная проверка повреждена", 409)
    current = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    if payload.get("v") != 1 or payload.get("user_id") != str(user_id):
        raise SynologyConnectorError("invalid_preview", "Предварительная проверка принадлежит другому пользователю", 409)
    if not isinstance(payload.get("expires_at"), int) or payload["expires_at"] < current:
        raise SynologyConnectorError("preview_expired", "Предварительная проверка устарела; проверьте выбор еще раз", 409)
    if not isinstance(payload.get("files"), list):
        raise SynologyConnectorError("invalid_preview", "Предварительная проверка повреждена", 409)
    return payload


def _api_error(error: Any) -> SynologyConnectorError:
    code = error.get("code") if isinstance(error, dict) else None
    known = _ERROR_MESSAGES.get(code)
    if known:
        return SynologyConnectorError(known[0], known[1], 502)
    return SynologyConnectorError("remote_error", "Synology отклонил запрос", 502)


class SynologyFileStationClient:
    """Authenticated File Station session kept only in backend memory."""

    def __init__(
        self,
        *,
        base_url: str,
        account_name: str,
        password: str,
        root_path: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = normalize_synology_base_url(base_url)
        self.account_name = account_name.strip()
        self._password = password
        self.root_path = normalize_root_path(root_path)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._api_info: dict[str, dict[str, Any]] = {}
        self._sid: str | None = None
        self._syno_token: str | None = None
        self._uses_session_cookie = False
        self._gateway_cookie_seen = False
        self._sid_from_login_response = False
        self._id_cookie_bridged = False
        self._is_portal_port: bool | None = None
        self._session_attempts: list[str] = []

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if settings.SYNOLOGY_CA_BUNDLE:
            context.load_verify_locations(cafile=settings.SYNOLOGY_CA_BUNDLE)
        return context

    async def connect(self, otp_code: str | None = None) -> SynologyFileStationClient:
        if self._client is not None:
            return self
        timeout = httpx.Timeout(
            connect=settings.SYNOLOGY_CONNECT_TIMEOUT_SECONDS,
            read=settings.SYNOLOGY_READ_TIMEOUT_SECONDS,
            write=settings.SYNOLOGY_READ_TIMEOUT_SECONDS,
            pool=settings.SYNOLOGY_CONNECT_TIMEOUT_SECONDS,
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=self._ssl_context(),
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
        )
        try:
            info = await self._post_json(
                "/webapi/entry.cgi",
                {
                    "api": "SYNO.API.Info",
                    "version": "1",
                    "method": "query",
                    "query": "SYNO.API.Auth,SYNO.FileStation.List,SYNO.FileStation.Download",
                },
            )
            data = info.get("data")
            if not isinstance(data, dict):
                raise SynologyConnectorError("api_discovery_failed", "Synology не вернул описание File Station API")
            for name in ("SYNO.API.Auth", "SYNO.FileStation.List", "SYNO.FileStation.Download"):
                value = data.get(name)
                if not isinstance(value, dict):
                    raise SynologyConnectorError("api_missing", f"Synology не поддерживает обязательный API {name}")
                self._validated_api_path(value.get("path"))
                self._api_info[name] = value
            self._gateway_cookie_seen = any(cookie.name != "id" for cookie in self._client.cookies.jar)
            login_params: dict[str, Any] = {
                "account": self.account_name,
                "passwd": self._password,
                "format": "sid",
                "enable_syno_token": "yes",
            }
            if otp_code and otp_code.strip():
                login_params["otp_code"] = otp_code.strip()
            login = await self._request_json(
                "SYNO.API.Auth",
                "login",
                login_params,
                include_session=False,
                preferred_version=6,
            )
            login_data = login.get("data")
            if not isinstance(login_data, dict):
                raise SynologyConnectorError("login_failed", "Synology не создал сессию File Station")
            sid = login_data.get("sid")
            self._sid = sid if isinstance(sid, str) and sid else None
            self._sid_from_login_response = self._sid is not None
            portal_port = login_data.get("is_portal_port")
            self._is_portal_port = portal_port if isinstance(portal_port, bool) else None
            self._gateway_cookie_seen = self._gateway_cookie_seen or any(
                cookie.name != "id" for cookie in self._client.cookies.jar
            )
            cookie_sid = self._session_cookie_value()
            if self._sid is None:
                self._sid = cookie_sid
            elif cookie_sid != self._sid:
                # Some gateways preserve their own affinity cookie but suppress
                # DSM's `id` cookie. DSM explicitly accepts the returned SID in
                # that cookie, so bridge it inside this backend-only client.
                self._set_session_cookie(self._sid)
                self._id_cookie_bridged = True
            self._uses_session_cookie = self._session_cookie_value() is not None
            if self._sid is None and not self._uses_session_cookie:
                raise SynologyConnectorError("login_failed", "Synology не создал сессию File Station")
            token = login_data.get("synotoken")
            if isinstance(token, str):
                normalized_token = token.strip()
                self._syno_token = normalized_token if normalized_token.strip("-") else None
            else:
                self._syno_token = None
            return self
        except Exception:
            await self._close_client()
            raise
        finally:
            self._password = ""

    async def __aenter__(self) -> SynologyFileStationClient:
        return await self.connect()

    async def close(self) -> None:
        try:
            if self._sid or self._uses_session_cookie:
                await self._request_json(
                    "SYNO.API.Auth",
                    "logout",
                    {},
                    preferred_version=6,
                )
        except Exception:
            pass
        finally:
            self._sid = None
            self._syno_token = None
            self._uses_session_cookie = False
            self._password = ""
            await self._close_client()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _close_client(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _session_cookie_value(self) -> str | None:
        if self._client is None:
            return None
        for cookie in self._client.cookies.jar:
            if cookie.name == "id" and cookie.value:
                return cookie.value
        return None

    def _set_session_cookie(self, sid: str) -> None:
        if self._client is None:
            return
        self._drop_session_cookies()
        hostname = urlsplit(self.base_url).hostname
        if not hostname:
            return
        self._client.cookies.set("id", sid, domain=hostname, path="/")
        self._uses_session_cookie = True

    def _drop_session_cookies(self) -> None:
        if self._client is None:
            return
        session_cookies = [cookie for cookie in self._client.cookies.jar if cookie.name == "id"]
        for cookie in session_cookies:
            try:
                self._client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
            except KeyError:
                continue
        self._uses_session_cookie = False

    def diagnostic_summary(self) -> dict[str, Any]:
        """Return protocol metadata that cannot expose credentials or session values."""

        return {
            "auth_format": "sid_cookie_bridge",
            "gateway_cookie_seen": self._gateway_cookie_seen,
            "sid_from_login_response": self._sid_from_login_response,
            "id_cookie_bridged": self._id_cookie_bridged,
            "id_cookie_active": self._session_cookie_value() is not None,
            "synotoken_present": self._syno_token is not None,
            "is_portal_port": self._is_portal_port,
            "session_attempts": self._session_attempts[-8:],
        }

    @staticmethod
    def _validated_api_path(value: Any) -> str:
        if not isinstance(value, str):
            raise SynologyConnectorError("invalid_api_path", "Synology вернул некорректный API path")
        path = value.lstrip("/")
        if not _SAFE_API_PATH.fullmatch(path) or ".." in path.split("/"):
            raise SynologyConnectorError("invalid_api_path", "Synology вернул небезопасный API path")
        return "/webapi/" + path

    def _version(self, api_name: str, preferred: int) -> int:
        info = self._api_info[api_name]
        try:
            minimum = int(info.get("minVersion", 1))
            maximum = int(info.get("maxVersion", preferred))
        except (TypeError, ValueError):
            raise SynologyConnectorError("invalid_api_version", "Synology вернул некорректную версию API")
        selected = min(preferred, maximum)
        if selected < minimum:
            raise SynologyConnectorError("api_version_missing", f"Версия API {api_name} не поддерживается")
        return selected

    async def _post_json(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise SynologyConnectorError("client_closed", "Подключение к Synology закрыто", 500)
        try:
            headers = {"X-SYNO-TOKEN": self._syno_token} if self._syno_token else None
            async with self._client.stream("POST", path, data=data, headers=headers) as response:
                if response.is_redirect:
                    raise SynologyConnectorError("redirect_blocked", "Synology вернул redirect; проверьте точный HTTPS-адрес", 502)
                if response.status_code != 200:
                    raise SynologyConnectorError("http_error", "Synology вернул ошибку соединения", 502)
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_SYNOLOGY_JSON_BYTES:
                            raise SynologyConnectorError("response_too_large", "Ответ Synology превышает допустимый размер", 502)
                    except ValueError:
                        raise SynologyConnectorError("invalid_response", "Synology вернул некорректный размер ответа", 502)
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_SYNOLOGY_JSON_BYTES:
                        raise SynologyConnectorError("response_too_large", "Ответ Synology превышает допустимый размер", 502)
                    chunks.append(chunk)
                body = b"".join(chunks)
        except httpx.TimeoutException:
            raise SynologyConnectorError("timeout", "Synology не ответил вовремя", 504)
        except (httpx.NetworkError, ssl.SSLError):
            raise SynologyConnectorError("connection_failed", "Не удалось установить защищенное соединение с Synology", 502)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise SynologyConnectorError("invalid_response", "Synology вернул некорректный ответ", 502)
        if not isinstance(payload, dict):
            raise SynologyConnectorError("invalid_response", "Synology вернул некорректный ответ", 502)
        if payload.get("success") is not True:
            raise _api_error(payload.get("error"))
        return payload

    async def _request_json(
        self,
        api_name: str,
        method: str,
        params: dict[str, Any],
        *,
        include_session: bool = True,
        preferred_version: int = 2,
    ) -> dict[str, Any]:
        info = self._api_info[api_name]
        data: dict[str, Any] = {
            "api": api_name,
            "version": str(self._version(api_name, preferred_version)),
            "method": method,
            **params,
        }
        if include_session and self._sid and not self._uses_session_cookie:
            data["_sid"] = self._sid
        if include_session and self._syno_token:
            data["SynoToken"] = self._syno_token
        path = self._validated_api_path(info.get("path"))
        if include_session:
            mode = "cookie" if self._uses_session_cookie else "sid" if self._sid else "none"
            self._session_attempts.append(f"{api_name}:{mode}")
        try:
            return await self._post_json(path, data)
        except SynologyConnectorError as error:
            if (
                error.code == "session_missing"
                and include_session
                and self._uses_session_cookie
                and self._sid
            ):
                # DSM may prefer an invalid/portal-scoped id cookie over a valid
                # explicit SID. Retry once with an unambiguous SID-only request.
                self._drop_session_cookies()
                data["_sid"] = self._sid
                self._session_attempts.append(f"{api_name}:sid")
                return await self._post_json(path, data)
            raise

    def _file_info(self, raw: Any) -> SynologyFileInfo:
        if not isinstance(raw, dict):
            raise SynologyConnectorError("invalid_file", "Synology вернул некорректное описание файла")
        path = ensure_path_within_root(str(raw.get("path") or ""), self.root_path)
        name = str(raw.get("name") or PurePosixPath(path).name).strip()
        if not name or "/" in name or "\\" in name:
            raise SynologyConnectorError("invalid_file", "Synology вернул некорректное имя файла")
        additional = raw.get("additional") if isinstance(raw.get("additional"), dict) else {}
        time_info = additional.get("time") if isinstance(additional.get("time"), dict) else {}
        try:
            size_bytes = int(additional.get("size", 0))
            modified_at = int(time_info.get("mtime", 0))
        except (TypeError, ValueError):
            raise SynologyConnectorError("invalid_file", "Synology вернул некорректный размер или дату файла")
        if size_bytes < 0 or modified_at < 0:
            raise SynologyConnectorError("invalid_file", "Synology вернул некорректный размер или дату файла")
        is_dir = raw.get("isdir") is True
        extension = "" if is_dir else PurePosixPath(name).suffix.lower()
        return SynologyFileInfo(path, name, is_dir, size_bytes, modified_at, extension)

    async def list_folder(self, path: str, *, offset: int = 0, limit: int = 100) -> SynologyFolderPage:
        folder_path = ensure_path_within_root(path, self.root_path)
        limit = max(1, min(limit, MAX_SYNOLOGY_LIST_LIMIT))
        if folder_path == "/" and self.root_path == "/":
            result = await self._request_json(
                "SYNO.FileStation.List",
                "list_share",
                {
                    "offset": str(max(0, offset)),
                    "limit": str(limit),
                    "sort_by": json.dumps("name"),
                    "sort_direction": json.dumps("asc"),
                    "additional": json.dumps(["time"]),
                },
                preferred_version=2,
            )
            data = result.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("shares"), list):
                raise SynologyConnectorError("invalid_listing", "Synology вернул некорректный список общих папок")
            items = [self._file_info({**item, "isdir": True}) for item in data["shares"]]
            try:
                total = int(data.get("total", len(items)))
                returned_offset = int(data.get("offset", offset))
            except (TypeError, ValueError):
                raise SynologyConnectorError("invalid_listing", "Synology вернул некорректную пагинацию")
            return SynologyFolderPage(folder_path, returned_offset, total, items)
        result = await self._request_json(
            "SYNO.FileStation.List",
            "list",
            {
                "folder_path": json.dumps(folder_path, ensure_ascii=False),
                "offset": str(max(0, offset)),
                "limit": str(limit),
                "sort_by": json.dumps("name"),
                "sort_direction": json.dumps("asc"),
                "filetype": json.dumps("all"),
                "additional": json.dumps(["size", "time", "type"]),
            },
            preferred_version=2,
        )
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            raise SynologyConnectorError("invalid_listing", "Synology вернул некорректный список файлов")
        items = [self._file_info(item) for item in data["files"]]
        try:
            total = int(data.get("total", len(items)))
            returned_offset = int(data.get("offset", offset))
        except (TypeError, ValueError):
            raise SynologyConnectorError("invalid_listing", "Synology вернул некорректную пагинацию")
        return SynologyFolderPage(folder_path, returned_offset, total, items)

    async def get_files(self, paths: list[str]) -> list[SynologyFileInfo]:
        normalized = [ensure_path_within_root(path, self.root_path) for path in paths]
        result = await self._request_json(
            "SYNO.FileStation.List",
            "getinfo",
            {
                "path": json.dumps(normalized, ensure_ascii=False),
                "additional": json.dumps(["size", "time", "type"]),
            },
            preferred_version=2,
        )
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            raise SynologyConnectorError("invalid_file_info", "Synology вернул некорректные сведения о файлах")
        items = [self._file_info(item) for item in data["files"]]
        by_path = {item.path: item for item in items}
        if set(by_path) != set(normalized):
            raise SynologyConnectorError("file_set_changed", "Набор выбранных файлов изменился; повторите проверку", 409)
        return [by_path[path] for path in normalized]

    async def download_file(self, path: str, *, max_bytes: int = MAX_SYNOLOGY_FILE_BYTES) -> bytes:
        if self._client is None:
            raise SynologyConnectorError("client_closed", "Подключение к Synology закрыто", 500)
        normalized = ensure_path_within_root(path, self.root_path)
        info = self._api_info["SYNO.FileStation.Download"]
        data: dict[str, Any] = {
            "api": "SYNO.FileStation.Download",
            "version": str(self._version("SYNO.FileStation.Download", 2)),
            "method": "download",
            "path": json.dumps([normalized], ensure_ascii=False),
            "mode": json.dumps("download"),
        }
        if self._sid and not self._uses_session_cookie:
            data["_sid"] = self._sid
        if self._syno_token:
            data["SynoToken"] = self._syno_token
        try:
            async with self._client.stream(
                "POST",
                self._validated_api_path(info.get("path")),
                data=data,
                headers={"X-SYNO-TOKEN": self._syno_token} if self._syno_token else None,
            ) as response:
                if response.is_redirect:
                    raise SynologyConnectorError("redirect_blocked", "Synology попытался перенаправить скачивание", 502)
                if response.status_code != 200:
                    raise SynologyConnectorError("download_failed", "Не удалось скачать файл из Synology", 502)
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise SynologyConnectorError("file_too_large", "Файл Synology превышает 25 МБ", 400)
                    except ValueError:
                        raise SynologyConnectorError("invalid_response", "Synology вернул некорректный размер ответа", 502)
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise SynologyConnectorError("file_too_large", "Файл Synology превышает 25 МБ", 400)
                    chunks.append(chunk)
                body = b"".join(chunks)
                if "json" in response.headers.get("content-type", "").lower():
                    try:
                        payload = json.loads(body)
                    except (ValueError, TypeError):
                        raise SynologyConnectorError("download_failed", "Synology вернул некорректный ответ скачивания", 502)
                    if isinstance(payload, dict) and payload.get("success") is False:
                        raise _api_error(payload.get("error"))
                return body
        except httpx.TimeoutException:
            raise SynologyConnectorError("timeout", "Скачивание из Synology превысило лимит времени", 504)
        except httpx.NetworkError:
            raise SynologyConnectorError("connection_failed", "Соединение с Synology было прервано", 502)


@dataclass
class ActiveSynologySession:
    token: str
    user_id: UUID
    connection_id: UUID
    config_version: int
    client: SynologyFileStationClient
    expires_at: datetime
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SynologySessionStore:
    """Process-local SID store. OTP and DSM session tokens are never persisted."""

    def __init__(self) -> None:
        self._sessions: dict[str, ActiveSynologySession] = {}
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self._guard = asyncio.Lock()

    @staticmethod
    def _next_expiry() -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=SYNOLOGY_SESSION_IDLE_TTL_SECONDS)

    async def create(
        self,
        *,
        user_id: UUID,
        connection_id: UUID,
        config_version: int,
        client: SynologyFileStationClient,
        replace_user_sessions: bool = True,
    ) -> ActiveSynologySession:
        token = secrets.token_urlsafe(48)
        session = ActiveSynologySession(
            token=token,
            user_id=user_id,
            connection_id=connection_id,
            config_version=config_version,
            client=client,
            expires_at=self._next_expiry(),
        )
        replaced: list[ActiveSynologySession] = []
        replaced_tasks: list[asyncio.Task[None]] = []
        async with self._guard:
            if replace_user_sessions:
                for current_token, current in list(self._sessions.items()):
                    if current.user_id == user_id:
                        replaced.append(self._sessions.pop(current_token))
                        task = self._expiry_tasks.pop(current_token, None)
                        if task:
                            replaced_tasks.append(task)
            self._sessions[token] = session
            self._expiry_tasks[token] = asyncio.create_task(self._expire_when_idle(token))
        for task in replaced_tasks:
            task.cancel()
        for current in replaced:
            async with current.lock:
                await current.client.close()
        return session

    async def rebind(
        self,
        token: str,
        *,
        user_id: UUID,
        connection_id: UUID,
        from_config_version: int,
        to_config_version: int,
    ) -> ActiveSynologySession:
        async with self._guard:
            session = self._sessions.get(token)
            if (
                session is None
                or session.user_id != user_id
                or session.connection_id != connection_id
                or session.config_version != from_config_version
            ):
                raise SynologyConnectorError(
                    "session_expired",
                    "Сессия Synology завершилась; подключитесь еще раз",
                    409,
                )
            session.config_version = to_config_version
            session.expires_at = self._next_expiry()
            return session

    async def _expire_when_idle(self, token: str) -> None:
        try:
            while True:
                async with self._guard:
                    session = self._sessions.get(token)
                    if session is None:
                        return
                    delay = (session.expires_at - datetime.now(timezone.utc)).total_seconds()
                    if delay <= 0:
                        self._sessions.pop(token, None)
                        self._expiry_tasks.pop(token, None)
                        expired = session
                    else:
                        expired = None
                if expired is not None:
                    async with expired.lock:
                        await expired.client.close()
                    return
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

    async def get(
        self,
        token: str,
        *,
        user_id: UUID,
        connection_id: UUID,
        config_version: int,
    ) -> ActiveSynologySession:
        now = datetime.now(timezone.utc)
        expired: list[ActiveSynologySession] = []
        expired_tasks: list[asyncio.Task[None]] = []
        async with self._guard:
            for current_token, current in list(self._sessions.items()):
                if current.expires_at <= now:
                    expired.append(self._sessions.pop(current_token))
                    task = self._expiry_tasks.pop(current_token, None)
                    if task and task is not asyncio.current_task():
                        expired_tasks.append(task)
            session = self._sessions.get(token)
            if session is not None:
                if (
                    session.user_id != user_id
                    or session.connection_id != connection_id
                    or session.config_version != config_version
                ):
                    session = None
                else:
                    session.expires_at = self._next_expiry()
        for task in expired_tasks:
            task.cancel()
        for current in expired:
            async with current.lock:
                await current.client.close()
        if session is None:
            raise SynologyConnectorError(
                "session_expired",
                "Сессия Synology завершилась; подключитесь еще раз",
                409,
            )
        return session

    async def remove(self, token: str, *, user_id: UUID) -> bool:
        async with self._guard:
            session = self._sessions.get(token)
            if session is None or session.user_id != user_id:
                return False
            self._sessions.pop(token, None)
            task = self._expiry_tasks.pop(token, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        async with session.lock:
            await session.client.close()
        return True

    async def revoke_profile(self, connection_id: UUID, *, except_token: str | None = None) -> int:
        revoked: list[ActiveSynologySession] = []
        tasks: list[asyncio.Task[None]] = []
        async with self._guard:
            for token, session in list(self._sessions.items()):
                if session.connection_id != connection_id or token == except_token:
                    continue
                revoked.append(self._sessions.pop(token))
                task = self._expiry_tasks.pop(token, None)
                if task and task is not asyncio.current_task():
                    tasks.append(task)
        for task in tasks:
            task.cancel()
        for session in revoked:
            async with session.lock:
                await session.client.close()
        return len(revoked)

    async def close_all(self) -> None:
        async with self._guard:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            tasks = list(self._expiry_tasks.values())
            self._expiry_tasks.clear()
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        for session in sessions:
            async with session.lock:
                await session.client.close()


synology_session_store = SynologySessionStore()
synology_profile_mutation_lock = asyncio.Lock()


def connector_request_hash(domain: str, *values: str) -> str:
    message = "\x1f".join(values).encode("utf-8")
    return hmac.new(_key_material(f"request:{domain}:v1"), message, sha256).hexdigest()


@asynccontextmanager
async def open_synology_connection(
    *,
    base_url: str,
    account_name: str,
    password: str,
    root_path: str,
    otp_code: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[SynologyFileStationClient]:
    client = SynologyFileStationClient(
        base_url=base_url,
        account_name=account_name,
        password=password,
        root_path=root_path,
        transport=transport,
    )
    try:
        await client.connect(otp_code=otp_code)
        yield client
    finally:
        await client.close()
