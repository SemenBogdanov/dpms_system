"""Atomic personal-storage accounting and quota request workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.storage_quota import (
    StorageQuotaRequest,
    UserStorageFile,
    UserStorageQuota,
)
from app.services.attachments import stored_attachment_path


MIB = 1024 * 1024
DEFAULT_QUOTA_BYTES = settings.PERSONAL_STORAGE_DEFAULT_BYTES
WARNING_RATIO = 0.80
CRITICAL_RATIO = 0.90
RESERVATION_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class StorageReservation:
    id: UUID
    stored_filename: str
    size_bytes: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_unlink(stored_filename: str) -> bool:
    try:
        stored_attachment_path(stored_filename).unlink(missing_ok=True)
    except (HTTPException, OSError):
        return False
    return True


async def _locked_account(db: AsyncSession, user_id: UUID) -> UserStorageQuota:
    await db.execute(
        pg_insert(UserStorageQuota)
        .values(
            user_id=user_id,
            limit_bytes=DEFAULT_QUOTA_BYTES,
            used_bytes=0,
            reserved_bytes=0,
        )
        .on_conflict_do_nothing(index_elements=[UserStorageQuota.user_id])
    )
    account = (
        await db.execute(
            select(UserStorageQuota)
            .where(UserStorageQuota.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one()
    return account


async def _cleanup_locked_account(
    db: AsyncSession,
    account: UserStorageQuota,
    *,
    now: datetime,
) -> None:
    files = list(
        (
            await db.execute(
                select(UserStorageFile)
                .where(
                    UserStorageFile.owner_id == account.user_id,
                    or_(
                        (
                            (UserStorageFile.status == "reserved")
                            & (UserStorageFile.expires_at <= now)
                        ),
                        UserStorageFile.status == "pending_delete",
                    ),
                )
                .with_for_update()
            )
        ).scalars()
    )
    for stored_file in files:
        if not _safe_unlink(stored_file.stored_filename):
            continue
        if stored_file.status == "reserved":
            account.reserved_bytes = max(
                0,
                account.reserved_bytes - stored_file.size_bytes,
            )
        else:
            account.used_bytes = max(0, account.used_bytes - stored_file.size_bytes)
        stored_file.status = "released"
        stored_file.expires_at = None
        stored_file.released_at = now
        stored_file.updated_at = now
    account.updated_at = now


async def get_storage_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    cleanup: bool = True,
) -> UserStorageQuota:
    account = await _locked_account(db, user_id)
    if cleanup:
        await _cleanup_locked_account(db, account, now=_utc_now())
    return account


def quota_state(account: UserStorageQuota) -> tuple[int, float, str, str]:
    committed = max(0, int(account.used_bytes))
    reserved = max(0, int(account.reserved_bytes))
    limit = max(1, int(account.limit_bytes))
    occupied = committed + reserved
    available = max(0, limit - occupied)
    ratio = occupied / limit
    percent = round(ratio * 100, 1)
    if occupied >= limit:
        return (
            available,
            percent,
            "blocked",
            "Хранилище заполнено. Новые файлы заблокированы до освобождения места или увеличения лимита.",
        )
    if ratio >= CRITICAL_RATIO:
        return (
            available,
            percent,
            "critical",
            "Использовано не менее 90% хранилища. Освободите место или запросите увеличение лимита.",
        )
    if ratio >= WARNING_RATIO:
        return (
            available,
            percent,
            "warning",
            "Использовано не менее 80% хранилища. Проверьте старые файлы и версии.",
        )
    return available, percent, "normal", "Свободного места достаточно."


async def reserve_storage_file(
    *,
    owner_id: UUID,
    stored_filename: str,
    size_bytes: int,
    category: str,
) -> StorageReservation:
    if size_bytes <= 0:
        raise ValueError("storage_file_size_must_be_positive")
    if category not in {"quick_note", "personal_task_artifact"}:
        raise ValueError("unsupported_personal_storage_category")

    now = _utc_now()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            account = await _locked_account(db, owner_id)
            await _cleanup_locked_account(db, account, now=now)
            projected = account.used_bytes + account.reserved_bytes + size_bytes
            if projected > account.limit_bytes:
                available, percent, level, message = quota_state(account)
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "storage_quota_exceeded",
                        "message": message,
                        "quota_bytes": account.limit_bytes,
                        "used_bytes": account.used_bytes,
                        "reserved_bytes": account.reserved_bytes,
                        "available_bytes": available,
                        "requested_bytes": size_bytes,
                        "usage_percent": percent,
                        "warning_level": level,
                    },
                )
            stored_file = UserStorageFile(
                owner_id=owner_id,
                stored_filename=stored_filename,
                size_bytes=size_bytes,
                category=category,
                status="reserved",
                expires_at=now + RESERVATION_TTL,
            )
            account.reserved_bytes += size_bytes
            account.updated_at = now
            db.add(stored_file)
            await db.flush()
            reservation = StorageReservation(
                id=stored_file.id,
                stored_filename=stored_file.stored_filename,
                size_bytes=stored_file.size_bytes,
            )
    return reservation


async def activate_storage_file(db: AsyncSession, storage_file_id: UUID) -> UserStorageFile:
    now = _utc_now()
    snapshot = (
        await db.execute(
            select(UserStorageFile).where(UserStorageFile.id == storage_file_id)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_reservation_unavailable",
                "message": "Резервация файла недоступна. Повторите загрузку.",
            },
        )
    account = await _locked_account(db, snapshot.owner_id)
    stored_file = (
        await db.execute(
            select(UserStorageFile)
            .where(UserStorageFile.id == storage_file_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if stored_file is None or stored_file.status != "reserved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_reservation_unavailable",
                "message": "Резервация файла недоступна. Повторите загрузку.",
            },
        )
    if stored_file.expires_at is not None and stored_file.expires_at <= now:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_reservation_expired",
                "message": "Время загрузки истекло. Повторите загрузку файла.",
            },
        )
    account.reserved_bytes = max(0, account.reserved_bytes - stored_file.size_bytes)
    account.used_bytes += stored_file.size_bytes
    account.updated_at = now
    stored_file.status = "active"
    stored_file.expires_at = None
    stored_file.activated_at = now
    stored_file.updated_at = now
    return stored_file


async def abandon_storage_reservation(storage_file_id: UUID) -> None:
    now = _utc_now()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            snapshot = (
                await db.execute(
                    select(UserStorageFile).where(UserStorageFile.id == storage_file_id)
                )
            ).scalar_one_or_none()
            if snapshot is None:
                return
            account = await _locked_account(db, snapshot.owner_id)
            stored_file = (
                await db.execute(
                    select(UserStorageFile)
                    .where(UserStorageFile.id == storage_file_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if stored_file is None or stored_file.status != "reserved":
                return
            if not _safe_unlink(stored_file.stored_filename):
                stored_file.expires_at = now
                return
            account.reserved_bytes = max(0, account.reserved_bytes - stored_file.size_bytes)
            account.updated_at = now
            stored_file.status = "released"
            stored_file.expires_at = None
            stored_file.released_at = now
            stored_file.updated_at = now


async def schedule_storage_file_deletion(
    db: AsyncSession,
    *,
    owner_id: UUID,
    stored_filename: str,
) -> UUID:
    now = _utc_now()
    snapshot = (
        await db.execute(
            select(UserStorageFile).where(
                UserStorageFile.owner_id == owner_id,
                UserStorageFile.stored_filename == stored_filename,
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_ledger_missing",
                "message": "Файл не найден в журнале хранилища. Обратитесь к администратору.",
            },
        )
    await _locked_account(db, owner_id)
    stored_file = (
        await db.execute(
            select(UserStorageFile)
            .where(
                UserStorageFile.owner_id == owner_id,
                UserStorageFile.stored_filename == stored_filename,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if stored_file is None:
        raise HTTPException(status_code=409, detail="Файл уже изменен другим запросом")
    if stored_file.status == "active":
        stored_file.status = "pending_delete"
        stored_file.delete_requested_at = now
        stored_file.updated_at = now
    return stored_file.id


async def finalize_storage_file_deletion(storage_file_id: UUID) -> bool:
    now = _utc_now()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            snapshot = (
                await db.execute(
                    select(UserStorageFile).where(UserStorageFile.id == storage_file_id)
                )
            ).scalar_one_or_none()
            if snapshot is None:
                return True
            account = await _locked_account(db, snapshot.owner_id)
            stored_file = (
                await db.execute(
                    select(UserStorageFile)
                    .where(UserStorageFile.id == storage_file_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if stored_file is None or stored_file.status == "released":
                return True
            if stored_file.status != "pending_delete":
                return False
            if not _safe_unlink(stored_file.stored_filename):
                return False
            account.used_bytes = max(0, account.used_bytes - stored_file.size_bytes)
            account.updated_at = now
            stored_file.status = "released"
            stored_file.released_at = now
            stored_file.updated_at = now
            return True


def storage_file_path(stored_filename: str) -> Path:
    return stored_attachment_path(stored_filename)
