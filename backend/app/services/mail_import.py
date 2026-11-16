"""Transactional Inbox import, deliberately independent of messaging/outbox services.

Callers must commit before returning an ACK. Lock order is owner row (share),
device row, owner advisory lock, mailbox advisory lock, item rows. The owner
advisory lock also makes the quota safe across different mailboxes.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.models.mail_import import MailImportAttachment, MailImportDevice, MailImportItem, utc_now
from app.models.user import User
from app.schemas.mail_import import (
    AttachmentRead, DeviceCreate, DeviceCreated, DeviceRead, ImportedItemInput, ImportedItemRead,
    ItemsRead, PairRead, SyncRead, SyncRequest,
)


MAX_ITEMS_PER_USER = 10000
MAX_CONTENT_BYTES_PER_USER = 2 * 1024 * 1024 * 1024
MAX_DEVICES_PER_USER = 100
PAIR_LIFETIME = timedelta(minutes=10)
DEVICE_LIFETIME = timedelta(days=365)


def error(status: int, code: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status_code=status, detail={"code": code}, headers=headers)


def digest(value: str, purpose: str) -> str:
    return hashlib.sha256(f"dpms-mail-import:{purpose}:{value}".encode("ascii")).hexdigest()


def advisory_id(owner_id: UUID, mailbox_id: str | None = None) -> int:
    value = f"dpms-mail-import:{owner_id}:{mailbox_id or 'quota'}"
    return int.from_bytes(hashlib.sha256(value.encode("ascii")).digest()[:8], "big", signed=True)


async def lock_import(db: AsyncSession, owner_id: UUID, mailbox_id: str | None = None) -> None:
    await db.execute(select(func.pg_advisory_xact_lock(advisory_id(owner_id))))
    if mailbox_id is not None:
        await db.execute(select(func.pg_advisory_xact_lock(advisory_id(owner_id, mailbox_id))))


async def require_owner(
    db: AsyncSession, owner_id: UUID, expected_version: int | None = None, *, device: bool = False,
):
    # Select scalar columns so an identity-map snapshot cannot bypass revocation.
    owner = (await db.execute(select(
        User.id, User.full_name, User.is_active, User.auth_version,
    ).where(User.id == owner_id).with_for_update(read=True))).one_or_none()
    if owner is None or not owner.is_active or (
        expected_version is not None and owner.auth_version != expected_version
    ):
        raise error(401 if device else 403, "invalid_device" if device else "owner_inactive")
    return owner


def device_read(device: MailImportDevice, owner_version: int, now: datetime) -> DeviceRead:
    expires = device.expires_at if device.paired_at is not None else device.pairing_expires_at
    if device.revoked_at is not None or device.owner_auth_version != owner_version:
        status = "revoked"
    elif expires is None or expires <= now:
        status = "expired"
    else:
        status = "active" if device.paired_at is not None else "pending"
    return DeviceRead(
        id=device.id, name=device.name, status=status, include_body=device.include_body,
        include_attachments=device.include_attachments,
        mailbox_label=device.mailbox_label, created_at=device.created_at,
        last_sync_at=device.last_sync_at, source_state=device.source_state, expires_at=expires,
        last_scan_complete=device.last_scan_complete, last_skipped_items=device.last_skipped_items,
    )


async def list_devices(db: AsyncSession, user: User) -> list[DeviceRead]:
    owner = await require_owner(db, user.id, user.auth_version)
    rows = (await db.scalars(select(MailImportDevice).where(
        MailImportDevice.owner_id == owner.id,
    ).order_by(MailImportDevice.created_at.desc(), MailImportDevice.id.desc()))).all()
    now = utc_now()
    return [device_read(row, owner.auth_version, now) for row in rows]


async def create_device(db: AsyncSession, user: User, body: DeviceCreate) -> DeviceCreated:
    owner = await require_owner(db, user.id, user.auth_version)
    await lock_import(db, owner.id)
    now = utc_now()
    # Expired/revoked rows remain visible without exhausting the live-device cap.
    count = await db.scalar(select(func.count()).select_from(MailImportDevice).where(
        MailImportDevice.owner_id == owner.id, MailImportDevice.revoked_at.is_(None),
        MailImportDevice.owner_auth_version == owner.auth_version,
        func.coalesce(MailImportDevice.expires_at, MailImportDevice.pairing_expires_at) > now,
    ))
    if count >= MAX_DEVICES_PER_USER:
        raise error(409, "device_count_limit")
    code = secrets.token_urlsafe(32)
    row = MailImportDevice(
        owner_id=owner.id, name=body.name, include_body=body.include_body,
        include_attachments=body.include_attachments,
        owner_auth_version=owner.auth_version, pairing_code_hash=digest(code, "pair"),
        pairing_expires_at=now + PAIR_LIFETIME, created_at=now,
    )
    db.add(row)
    await db.flush()
    return DeviceCreated(
        device=device_read(row, owner.auth_version, now), pairing_code=code,
        expires_at=row.pairing_expires_at,
    )


async def revoke_device(db: AsyncSession, user: User, device_id: UUID) -> DeviceRead:
    owner = await require_owner(db, user.id, user.auth_version)
    row = (await db.scalars(select(MailImportDevice).where(
        MailImportDevice.id == device_id, MailImportDevice.owner_id == owner.id,
    ).with_for_update().execution_options(populate_existing=True))).one_or_none()
    if row is None:
        raise error(404, "device_not_found")
    if row.revoked_at is None:
        row.revoked_at = utc_now()
    row.pairing_code_hash = None
    row.device_secret_hash = None
    await db.flush()
    return device_read(row, owner.auth_version, utc_now())


async def locked_device(db: AsyncSession, value: str, *, pairing: bool = False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise error(401, "invalid_device")
    hashed = digest(value, "pair" if pairing else "device")
    field = MailImportDevice.pairing_code_hash if pairing else MailImportDevice.device_secret_hash
    identity = (await db.execute(select(
        MailImportDevice.id, MailImportDevice.owner_id,
    ).where(field == hashed))).one_or_none()
    if identity is None:
        raise error(401, "invalid_device")
    owner = await require_owner(db, identity.owner_id, device=True)
    row = (await db.scalars(select(MailImportDevice).where(
        MailImportDevice.id == identity.id,
    ).with_for_update().execution_options(populate_existing=True))).one_or_none()
    # Recheck after waiting: another pair, sync or revoke may have committed.
    now = utc_now()
    if row is None or row.revoked_at is not None or row.owner_auth_version != owner.auth_version:
        raise error(401, "invalid_device")
    if pairing:
        valid = row.pairing_code_hash == hashed and row.paired_at is None and row.pairing_expires_at > now
    else:
        valid = row.device_secret_hash == hashed and row.paired_at is not None and row.expires_at is not None and row.expires_at > now
    if not valid:
        raise error(401, "invalid_device")
    return row, owner


async def pair_device(db: AsyncSession, code: str) -> PairRead:
    row, owner = await locked_device(db, code, pairing=True)
    value = secrets.token_urlsafe(32)
    row.pairing_code_hash = None
    row.device_secret_hash = digest(value, "device")
    row.paired_at = utc_now()
    row.expires_at = row.paired_at + DEVICE_LIFETIME
    await db.flush()
    return PairRead(
        device_id=row.id, device_secret=value, owner_name=owner.full_name,
        include_body=row.include_body,
        include_attachments=row.include_attachments,
    )


def semantic_payload(item: ImportedItemInput) -> dict:
    payload = item.model_dump(mode="json", exclude={"source_is_read", "source_modified_at", "attachments"})
    payload["attachments"] = [attachment.model_dump(exclude={"data_base64"}) for attachment in item.attachments]
    return payload


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")).hexdigest()


def semantic_hash(item: ImportedItemInput) -> str:
    return payload_hash(semantic_payload(item))


def can_enrich(row: MailImportItem, item: ImportedItemInput, *, include_body: bool, include_attachments: bool) -> bool:
    new_body = include_body and not row.body_captured
    new_attachments = include_attachments and not row.attachments_captured
    if not (new_body or new_attachments):
        return False
    baseline = semantic_payload(item)
    if new_body:
        baseline["body_text"] = row.body_text
        baseline["body_html"] = row.body_html
    if new_attachments:
        # Ungranted attachment groups are empty, not authoritative empty snapshots.
        baseline["attachments"] = []
    return payload_hash(baseline) == row.semantic_hash


def content_size(item: ImportedItemInput) -> int:
    text_bytes = sum(len((getattr(item, name) or "").encode("utf-8")) for name in (
        "body_text", "body_html", "to_recipients", "cc_recipients",
    ))
    return text_bytes + sum(len(attachment.decoded_data) for attachment in item.attachments)


def apply_item(
    row: MailImportItem, item: ImportedItemInput, hashed: str, now: datetime,
    *, include_body: bool = False, include_attachments: bool = False,
) -> str:
    if item.source_modified_at < row.source_modified_at:
        return "stale"
    changed = hashed != row.semantic_hash
    same_version = item.source_modified_at == row.source_modified_at
    if same_version and changed and not can_enrich(
        row, item, include_body=include_body, include_attachments=include_attachments,
    ):
        raise error(409, "item_version_conflict")
    capture_changed = (include_body and not row.body_captured) or (include_attachments and not row.attachments_captured)
    row.body_captured = bool(row.body_captured or include_body)
    row.attachments_captured = bool(row.attachments_captured or include_attachments)
    if changed:
        for name, value in item.model_dump(exclude={"attachments"}).items():
            setattr(row, name, value)
        row.semantic_hash = hashed
        row.content_byte_length = content_size(item)
        if not same_version:
            row.is_read = False
        row.updated_at = now
        return "updated"
    if row.source_modified_at != item.source_modified_at or row.source_is_read != item.source_is_read or capture_changed:
        row.source_modified_at = item.source_modified_at
        row.source_is_read = item.source_is_read
        row.updated_at = now
    return "unchanged"


async def sync_items(db: AsyncSession, value: str, body: SyncRequest) -> SyncRead:
    device, owner = await locked_device(db, value)
    await lock_import(db, owner.id, body.mailbox_id)
    # Expiry may have elapsed while waiting for the mailbox/quota locks.
    now = utc_now()
    if device.expires_at <= now:
        raise error(401, "invalid_device")
    if device.mailbox_id is not None and device.mailbox_id != body.mailbox_id:
        raise error(409, "mailbox_mismatch")
    # The owner/mailbox lock makes this committed history monotonic across devices.
    # Do not lock other device rows: competing syncs already hold their own row.
    history = (await db.execute(select(
        func.bool_or(MailImportDevice.include_body).label("body_seen"),
        func.bool_or(MailImportDevice.include_attachments).label("attachments_seen"),
    ).where(MailImportDevice.owner_id == owner.id, MailImportDevice.mailbox_id == body.mailbox_id))).one()
    if (history.body_seen and not device.include_body) or (history.attachments_seen and not device.include_attachments):
        raise error(409, "mailbox_scope_mismatch")
    if not device.include_body and any(item.body_text is not None or item.body_html is not None for item in body.items):
        raise error(403, "body_not_granted")
    if not device.include_attachments and any(item.attachments for item in body.items):
        raise error(403, "attachments_not_granted")

    versions = {}
    hashed_items = []
    for item in body.items:
        hashed = semantic_hash(item)
        version = (item.source_id, item.source_modified_at)
        if version in versions and versions[version] != hashed:
            raise error(409, "item_version_conflict")
        versions[version] = hashed
        hashed_items.append((item, hashed))

    source_ids = {item.source_id for item in body.items}
    rows = (await db.scalars(select(MailImportItem).where(
        MailImportItem.owner_id == owner.id, MailImportItem.mailbox_id == body.mailbox_id,
        MailImportItem.source_id.in_(source_ids),
    ).with_for_update().execution_options(populate_existing=True))).all() if source_ids else []
    existing = {row.source_id: row for row in rows}
    if any((row.body_captured and not device.include_body) or (
        row.attachments_captured and not device.include_attachments
    ) for row in rows):
        raise error(409, "mailbox_scope_mismatch")
    for item, hashed in hashed_items:
        row = existing.get(item.source_id)
        if row is not None and item.source_modified_at == row.source_modified_at and hashed != row.semantic_hash and not can_enrich(
            row, item, include_body=device.include_body, include_attachments=device.include_attachments,
        ):
            raise error(409, "item_version_conflict")
    new_count = len(source_ids - existing.keys())
    if new_count:
        count = await db.scalar(select(func.count()).select_from(MailImportItem).where(
            MailImportItem.owner_id == owner.id,
        ))
        if count + new_count > MAX_ITEMS_PER_USER:
            raise error(409, "item_count_limit")

    projected_bytes = int(await db.scalar(select(func.coalesce(func.sum(MailImportItem.content_byte_length), 0)).where(
        MailImportItem.owner_id == owner.id,
    ))) if body.items else 0
    counts = dict(created=0, updated=0, unchanged=0, stale=0)
    replacements = {}
    # Apply the newest snapshot first so batch ordering cannot change DPMS unread
    # state or temporarily replace attachments with an already superseded version.
    for item, hashed in sorted(hashed_items, key=lambda pair: (pair[0].source_id, pair[0].source_modified_at), reverse=True):
        row = existing.get(item.source_id)
        if row is None:
            row = MailImportItem(
                id=uuid4(), owner_id=owner.id, mailbox_id=body.mailbox_id, mailbox_label=body.mailbox_label,
                **item.model_dump(exclude={"attachments"}), semantic_hash=hashed, is_read=False, created_at=now, updated_at=now,
                content_byte_length=content_size(item),
                body_captured=device.include_body, attachments_captured=device.include_attachments,
            )
            db.add(row)
            existing[item.source_id] = row
            counts["created"] += 1
            replacements[row.id] = item.attachments
            projected_bytes += row.content_byte_length
        else:
            previous_bytes = row.content_byte_length
            same_version = row.source_modified_at == item.source_modified_at
            attachments_captured = row.attachments_captured
            outcome = apply_item(
                row, item, hashed, now,
                include_body=device.include_body, include_attachments=device.include_attachments,
            )
            counts[outcome] += 1
            if outcome == "updated":
                if not same_version or (device.include_attachments and not attachments_captured):
                    replacements[row.id] = item.attachments
                projected_bytes += row.content_byte_length - previous_bytes

    if (counts["created"] or counts["updated"]) and projected_bytes > MAX_CONTENT_BYTES_PER_USER:
        raise error(413, "content_storage_limit")
    if replacements:
        # Parent items must exist before inserting binary children. All writes still
        # belong to the same transaction, including replacements and heartbeat.
        await db.flush()
        await db.execute(delete(MailImportAttachment).where(MailImportAttachment.item_id.in_(replacements)))
        for item_id, attachments in replacements.items():
            for ordinal, attachment in enumerate(attachments):
                db.add(MailImportAttachment(
                    item_id=item_id, ordinal=ordinal, **attachment.model_dump(exclude={"data_base64"}),
                    size=len(attachment.decoded_data), data=attachment.decoded_data,
                ))

    device.mailbox_id = body.mailbox_id
    device.mailbox_label = body.mailbox_label
    device.source_state = body.source_state
    device.last_scan_complete = body.scan_complete
    device.last_skipped_items = body.skipped_items
    device.last_sync_at = now
    await db.flush()
    return SyncRead(accepted=len(body.items), **counts, synced_at=now)


def item_read(row: MailImportItem, manifests: list[AttachmentRead], *, include_body: bool = True) -> ImportedItemRead:
    fields = {name: getattr(row, name) for name in ImportedItemRead.model_fields if name not in {"body_text", "body_html", "attachments"}}
    fields["body_text"] = row.body_text if include_body else None
    fields["body_html"] = row.body_html if include_body else None
    fields["attachments"] = manifests
    return ImportedItemRead(**fields)


async def attachment_manifests(db: AsyncSession, item_ids: list[UUID]) -> dict[UUID, list[AttachmentRead]]:
    if not item_ids:
        return {}
    rows = (await db.scalars(select(MailImportAttachment).options(defer(MailImportAttachment.data)).where(
        MailImportAttachment.item_id.in_(item_ids),
    ).order_by(MailImportAttachment.item_id, MailImportAttachment.ordinal))).all()
    grouped = {item_id: [] for item_id in item_ids}
    for row in rows:
        grouped[row.item_id].append(AttachmentRead.model_validate(row))
    return grouped


async def list_items(
    db: AsyncSession, user: User, kind: str | None, unread_only: bool, limit: int, offset: int,
) -> ItemsRead:
    await require_owner(db, user.id, user.auth_version)
    await lock_import(db, user.id)
    filters = [MailImportItem.owner_id == user.id]
    if kind is not None:
        filters.append(MailImportItem.kind == kind)
    unread_count = await db.scalar(select(func.count()).select_from(MailImportItem).where(
        *filters, MailImportItem.is_read.is_(False),
    ))
    if unread_only:
        filters.append(MailImportItem.is_read.is_(False))
    total = await db.scalar(select(func.count()).select_from(MailImportItem).where(*filters))
    rows = (await db.scalars(select(MailImportItem).options(defer(MailImportItem.body_text), defer(MailImportItem.body_html)).where(
        *filters,
    ).order_by(MailImportItem.received_at.desc(), MailImportItem.id.desc()).limit(limit).offset(offset))).all()
    manifests = await attachment_manifests(db, [row.id for row in rows])
    return ItemsRead(items=[item_read(row, manifests[row.id], include_body=False) for row in rows], total=total, unread_count=unread_count)


async def owned_item(db: AsyncSession, user: User, item_id: UUID, *, lock: bool = False) -> MailImportItem:
    await require_owner(db, user.id, user.auth_version)
    await lock_import(db, user.id)
    query = select(MailImportItem).where(MailImportItem.id == item_id, MailImportItem.owner_id == user.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = (await db.scalars(query)).one_or_none()
    if row is None:
        raise error(404, "item_not_found")
    return row


async def read_item(db: AsyncSession, user: User, item_id: UUID) -> ImportedItemRead:
    row = await owned_item(db, user, item_id)
    manifests = await attachment_manifests(db, [row.id])
    return item_read(row, manifests[row.id])


async def mark_read(db: AsyncSession, user: User, item_id: UUID, is_read: bool) -> ImportedItemRead:
    row = await owned_item(db, user, item_id, lock=True)
    row.is_read = is_read
    await db.flush()
    manifests = await attachment_manifests(db, [row.id])
    return item_read(row, manifests[row.id])


async def download_attachment(db: AsyncSession, user: User, item_id: UUID, attachment_id: UUID) -> tuple[str, bytes]:
    await require_owner(db, user.id, user.auth_version)
    row = (await db.scalars(select(MailImportAttachment).join(
        MailImportItem, MailImportAttachment.item_id == MailImportItem.id,
    ).where(
        MailImportItem.owner_id == user.id, MailImportItem.id == item_id,
        MailImportAttachment.id == attachment_id,
    ))).one_or_none()
    if row is None:
        raise error(404, "attachment_not_found")
    return row.filename, row.data
