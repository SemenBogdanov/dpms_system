"""Encryption for confidential audit contract references."""

from __future__ import annotations

import base64
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.services.integration_crypto import get_integration_secret


class AuditContractReferenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fernet() -> Fernet:
    secret = get_integration_secret()
    if len(secret) < 32:
        raise AuditContractReferenceError(
            "encryption_key_not_configured",
            "На сервере DPMS не настроен ключ для конфиденциальных реквизитов",
        )
    material = sha256(
        b"dpms:audit:contract-reference:v1:" + secret.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_contract_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AuditContractReferenceError(
            "contract_reference_required",
            "Укажите номер договора",
        )
    if len(normalized) > 255:
        raise AuditContractReferenceError(
            "contract_reference_too_long",
            "Номер договора не должен быть длиннее 255 символов",
        )
    return "v1:" + _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_contract_reference(ciphertext: str | None) -> str:
    if not ciphertext or not ciphertext.startswith("v1:"):
        raise AuditContractReferenceError(
            "contract_reference_unavailable",
            "Полный номер договора не сохранен; укажите его через редактирование карточки",
        )
    try:
        value = _fernet().decrypt(ciphertext[3:].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise AuditContractReferenceError(
            "contract_reference_unavailable",
            "Не удалось расшифровать номер договора; сохраните его заново",
        )
    if not value or len(value) > 255:
        raise AuditContractReferenceError(
            "contract_reference_unavailable",
            "Зашифрованный номер договора поврежден",
        )
    return value
