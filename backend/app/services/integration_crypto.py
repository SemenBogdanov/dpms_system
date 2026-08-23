"""Runtime loading for the shared integration encryption secret."""

from pathlib import Path

from app.config import settings


MAX_INTEGRATION_SECRET_BYTES = 4096


def _read_secret_file() -> str:
    if not settings.INTEGRATION_SECRET_KEY_FILE:
        return ""
    try:
        data = Path(settings.INTEGRATION_SECRET_KEY_FILE).read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_INTEGRATION_SECRET_BYTES:
        return ""
    try:
        return data.decode("utf-8").strip()
    except UnicodeError:
        return ""


def get_integration_secret(*, allow_legacy: bool = False) -> str:
    if settings.INTEGRATION_SECRET_KEY is not None:
        return settings.INTEGRATION_SECRET_KEY.strip()
    file_secret = _read_secret_file()
    if file_secret:
        return file_secret
    if allow_legacy:
        return (settings.AUDIT_CONNECTOR_SECRET_KEY or "").strip()
    return ""


def integration_secret_configured(*, allow_legacy: bool = False) -> bool:
    return len(get_integration_secret(allow_legacy=allow_legacy)) >= 32
