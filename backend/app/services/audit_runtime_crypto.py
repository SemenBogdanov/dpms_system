"""Encryption and keyed idempotency for transient canonical runtime identities."""

from __future__ import annotations

import base64
from hashlib import sha256
import hmac
import json

from cryptography.fernet import Fernet, InvalidToken

from app.services.integration_crypto import get_integration_secret


class AuditRuntimeCryptoError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _secret() -> bytes:
    value = get_integration_secret()
    if len(value) < 32:
        raise AuditRuntimeCryptoError(
            "encryption_key_not_configured",
            "На сервере DPMS не настроен отдельный ключ интеграций",
        )
    return value.encode("utf-8")


def _fernet() -> Fernet:
    material = sha256(b"dpms:audit-tz:runtime-identifiers:v1:" + _secret()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _canonical_json(identifiers: list[str]) -> bytes:
    return json.dumps(identifiers, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def identifier_digest(identifiers: list[str]) -> str:
    return hmac.new(
        _secret(),
        b"audit-tz-identifiers-v1\0" + _canonical_json(identifiers),
        sha256,
    ).hexdigest()


def encrypt_identifiers(identifiers: list[str]) -> str:
    if not identifiers:
        raise AuditRuntimeCryptoError("identifiers_required", "Укажите номер договора")
    return "v1:" + _fernet().encrypt(_canonical_json(identifiers)).decode("ascii")


def decrypt_identifiers(ciphertext: str | None) -> list[str]:
    if not ciphertext or not ciphertext.startswith("v1:"):
        raise AuditRuntimeCryptoError(
            "runtime_identity_unavailable",
            "Зашифрованные идентификаторы запуска недоступны",
        )
    try:
        raw = _fernet().decrypt(ciphertext[3:].encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        raise AuditRuntimeCryptoError(
            "runtime_identity_unavailable",
            "Не удалось расшифровать идентификаторы запуска",
        )
    if (
        not isinstance(payload, list)
        or not payload
        or len(payload) > 20
        or any(not isinstance(item, str) or not item or len(item) > 160 for item in payload)
    ):
        raise AuditRuntimeCryptoError(
            "runtime_identity_invalid",
            "Зашифрованные идентификаторы запуска повреждены",
        )
    return payload


def build_run_key(
    *,
    case_id: str,
    document_sha256: str,
    skill_sha256: str,
    identifiers_digest: str,
    mode: str,
) -> str:
    payload = "\0".join(
        (case_id, document_sha256, skill_sha256, identifiers_digest, mode)
    ).encode("utf-8")
    return hmac.new(_secret(), b"audit-tz-run-key-v1\0" + payload, sha256).hexdigest()
