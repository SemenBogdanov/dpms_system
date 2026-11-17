"""Queue transactions. Never commit import separately from its receipt."""
from datetime import timedelta

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail_import import utc_now
from app.models.mail_import_queue import MailImportDBDevice, MailImportDBLogin, MailImportQueue
from app.schemas.mail_import import MAX_BATCH_BYTES, SyncRequest
from app.services import mail_import


RECEIPT_RETENTION = timedelta(days=7)
CLEANUP_LIMIT = 100
SAFE_ERRORS = {
    "invalid_device": 401, "mailbox_mismatch": 409, "mailbox_scope_mismatch": 409,
    "body_not_granted": 403, "attachments_not_granted": 403,
    "item_version_conflict": 409, "item_count_limit": 409, "content_storage_limit": 413,
}


def reject(row: MailImportQueue, code: str, status: int) -> None:
    row.state, row.error_code, row.error_status = "error", code, status
    row.payload, row.result, row.finished_at = None, None, utc_now()


async def require_db_login(db, row, device):
    """Owner/device locks precede binding/login locks, matching FK delete order."""
    binding = (await db.scalars(select(MailImportDBDevice).where(
        MailImportDBDevice.device_id == device.id,
    ).with_for_update(read=True).execution_options(populate_existing=True))).one_or_none()
    if binding is None and row.login_role_oid is None:
        return  # Legacy SQL-paired device; new DB secrets cannot enter this path.
    if binding is None or (binding.role_oid, binding.role_name) != (row.login_role_oid, row.login_role_name):
        raise mail_import.error(401, "invalid_device")
    login = (await db.scalars(select(MailImportDBLogin).where(
        MailImportDBLogin.role_oid == binding.role_oid,
        MailImportDBLogin.role_name == binding.role_name,
    ).with_for_update(read=True).execution_options(populate_existing=True))).one_or_none()
    if login is None or not login.enabled or login.owner_id != device.owner_id or (
        device.include_body and not login.include_body
    ) or (device.include_attachments and not login.include_attachments):
        raise mail_import.error(401, "invalid_device")
    role_exists = await db.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles
            WHERE oid = :role_oid AND rolname = :role_name AND rolcanlogin
            AND (rolvaliduntil IS NULL OR rolvaliduntil > pg_catalog.clock_timestamp()))
    """), {"role_oid": login.role_oid, "role_name": login.role_name})
    if not role_exists:
        raise mail_import.error(401, "invalid_device")


async def process_next(db: AsyncSession) -> bool:
    """Queue -> owner -> device -> binding/login -> import; enqueue has no row locks."""
    row = (await db.scalars(select(MailImportQueue).where(
        MailImportQueue.state == "pending",
    ).order_by(MailImportQueue.created_at, MailImportQueue.device_id, MailImportQueue.request_id)
        .with_for_update(skip_locked=True).limit(1))).one_or_none()
    if row is None:
        return False
    if row.expires_at <= utc_now():
        reject(row, "request_expired", 408)
        await db.flush()
        return True
    try:
        async with db.begin_nested():
            device, owner = await mail_import.locked_device_by_digest(db, row.device_digest, device_id=row.device_id)
            if owner.id != row.owner_id:
                raise mail_import.error(401, "invalid_device")
            await require_db_login(db, row, device)
            if row.payload is None or len(row.payload.encode("utf-8")) > MAX_BATCH_BYTES:
                raise mail_import.error(413, "batch_too_large")
            body = SyncRequest.model_validate_json(row.payload)
            result = await mail_import.sync_locked(db, device, owner, body)
    except (ValidationError, UnicodeError, RecursionError):
        reject(row, "invalid_payload", 422)
    except HTTPException as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
        if code == "batch_too_large":
            reject(row, code, 413)
        elif code in SAFE_ERRORS and SAFE_ERRORS[code] == exc.status_code:
            reject(row, code, exc.status_code)
        else:
            reject(row, "request_rejected", 400)
    else:
        row.state, row.result = "done", result.model_dump(mode="json")
        row.payload, row.finished_at = None, utc_now()
    await db.flush()
    return True


async def cleanup(db: AsyncSession, *, limit: int = CLEANUP_LIMIT) -> int:
    now = utc_now()
    rows = (await db.scalars(select(MailImportQueue).where(or_(
        (MailImportQueue.state == "pending") & (MailImportQueue.expires_at <= now),
        MailImportQueue.finished_at < now - RECEIPT_RETENTION,
    )).order_by(MailImportQueue.created_at).with_for_update(skip_locked=True)
        .limit(max(1, min(limit, CLEANUP_LIMIT))))).all()
    for row in rows:
        if row.state == "pending":
            reject(row, "request_expired", 408)
        else:
            await db.delete(row)
    await db.flush()
    return len(rows)
