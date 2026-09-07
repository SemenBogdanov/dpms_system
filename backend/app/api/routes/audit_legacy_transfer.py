"""Administrative transfer endpoints; no source data is exposed by public case routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_audit_role
from app.models.audit_legacy_transfer import AuditLegacyTransfer
from app.models.user import User
from app.schemas.audit_legacy_transfer import (
    TransferCommit, TransferConfigUpdate, TransferCreate, TransferOptions,
    TransferPreviewPage, TransferRead, TransferRevision, TransferRollback,
)
from app.services import audit_legacy_transfer as service


require_transfer_admin = require_audit_role("admin")


def private_response(response: Response):
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


router = APIRouter(dependencies=[Depends(require_transfer_admin), Depends(private_response)])


@router.get("/options", response_model=TransferOptions)
async def transfer_options(source_id: UUID | None = None, db: AsyncSession = Depends(get_db)):
    return await service.options(db, source_id)


@router.get("", response_model=list[TransferRead])
async def list_transfers(source_id: UUID | None = None, db: AsyncSession = Depends(get_db)):
    query = select(AuditLegacyTransfer).order_by(AuditLegacyTransfer.created_at.desc())
    if source_id is not None:
        query = query.where(AuditLegacyTransfer.source_id == source_id)
    return [service.transfer_read(item) for item in (await db.execute(query)).scalars()]


@router.post("", response_model=TransferRead)
async def create_transfer(payload: TransferCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_transfer_admin)):
    async with service.atomic_write(db):
        transfer = await service.create_transfer(db, payload, admin.id)
        await db.flush()
        result = service.transfer_read(transfer)
    return result


@router.get("/{transfer_id}", response_model=TransferRead)
async def get_transfer(transfer_id: UUID, db: AsyncSession = Depends(get_db)):
    return service.transfer_read(await service.get_transfer(db, transfer_id))


@router.put("/{transfer_id}/config", response_model=TransferRead)
async def update_config(transfer_id: UUID, payload: TransferConfigUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_transfer_admin)):
    async with service.atomic_write(db):
        transfer = await service.update_config(db, transfer_id, payload, admin.id)
        await db.flush()
        result = service.transfer_read(transfer)
    return result


@router.post("/{transfer_id}/preview", response_model=TransferRead)
async def preview_transfer(transfer_id: UUID, payload: TransferRevision, db: AsyncSession = Depends(get_db), admin: User = Depends(require_transfer_admin)):
    async with service.atomic_write(db):
        transfer = await service.preview_transfer(db, transfer_id, payload.revision, admin.id)
        await db.flush()
        result = service.transfer_read(transfer)
    return result


@router.get("/{transfer_id}/preview/rows", response_model=TransferPreviewPage)
async def preview_rows(transfer_id: UUID, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    return service.preview_page(await service.get_transfer(db, transfer_id), offset, limit)


@router.post("/{transfer_id}/commit", response_model=TransferRead)
async def commit_transfer(transfer_id: UUID, payload: TransferCommit, db: AsyncSession = Depends(get_db), admin: User = Depends(require_transfer_admin)):
    async with service.atomic_write(db):
        transfer = await service.commit_transfer(db, transfer_id, payload, admin.id)
        await db.flush()
        result = service.transfer_read(transfer)
    return result


@router.post("/{transfer_id}/rollback", response_model=TransferRead)
async def rollback_transfer(transfer_id: UUID, payload: TransferRollback, db: AsyncSession = Depends(get_db), admin: User = Depends(require_transfer_admin)):
    async with service.atomic_write(db):
        transfer = await service.rollback_transfer(db, transfer_id, payload, admin.id)
        await db.flush()
        result = service.transfer_read(transfer)
    return result
