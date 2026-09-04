"""Password hashing and signed local access tokens without external secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID


DATA_DIR = Path(os.environ.get("DPMS_DATA_DIR", "/data"))
SECRET_PATH = DATA_DIR / "instance_secret"
TOKEN_TTL_SECONDS = 12 * 60 * 60
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _instance_secret() -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_PATH.exists():
        secret = SECRET_PATH.read_bytes()
        if len(secret) >= 32:
            return secret
        raise RuntimeError("instance_secret is invalid")
    secret = secrets.token_bytes(48)
    fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(secret)
    return secret


def validate_password_strength(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 10:
        errors.append("Пароль должен содержать минимум 10 символов")
    if len(password.encode("utf-8")) > 128:
        errors.append("Пароль слишком длинный")
    if not any(character.isupper() for character in password):
        errors.append("Добавьте хотя бы одну заглавную букву")
    if not any(character.islower() for character in password):
        errors.append("Добавьте хотя бы одну строчную букву")
    if not any(character.isdigit() for character in password):
        errors.append("Добавьте хотя бы одну цифру")
    return errors


def get_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = _b64decode(raw_digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(raw_salt),
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: UUID, auth_version: int) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(
        json.dumps(
            {
                "sub": str(user_id),
                "ver": auth_version,
                "exp": int(time.time()) + TOKEN_TTL_SECONDS,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64encode(hmac.new(_instance_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> dict | None:
    try:
        header, payload, signature = token.split(".", 2)
        signing_input = f"{header}.{payload}".encode("ascii")
        expected = hmac.new(_instance_secret(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            return None
        decoded = json.loads(_b64decode(payload))
        if not isinstance(decoded, dict) or int(decoded.get("exp", 0)) <= int(time.time()):
            return None
        return decoded
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
