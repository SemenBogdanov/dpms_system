"""Admin-only XLSX staging. No working registry model or import service is used."""

from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import UUID

from anyio import CapacityLimiter
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db, require_audit_role
from app.models.audit_legacy import AuditLegacyImport, utc_now
from app.models.user import User
from app.schemas.audit_legacy import (
    AuditLegacyBatchRead,
    AuditLegacyInspection,
    AuditLegacyMappingUpdate,
    AuditLegacyReport,
)
from app.services.audit_legacy_workbook import (
    MAX_UPLOAD_BYTES,
    inspect_legacy_workbook,
    preview_legacy_mapping,
)
from app.services.activity import record_activity_event


MAX_STAGING_BATCHES = 20
PARSER_LIMITER = CapacityLimiter(1)
# One transaction lock covers both the global quota and same-SHA insert races.
STAGING_LOCK_ID = 0x44504D53413139
SOURCE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def _private_response(response: Response) -> None:
    response.headers.update(SOURCE_HEADERS)


require_legacy_admin = require_audit_role("admin")
router = APIRouter(dependencies=[Depends(require_legacy_admin), Depends(_private_response)])


async def _lock_staging(db: AsyncSession) -> None:
    await db.execute(select(func.pg_advisory_xact_lock(STAGING_LOCK_ID)))


async def _parse_workbook(function, *args) -> dict:
    async with PARSER_LIMITER:
        return await run_in_threadpool(function, *args)


@asynccontextmanager
async def _staging_write(db: AsyncSession):
    try:
        yield
        await db.commit()
    except SQLAlchemyError:
        # SQLAlchemy exceptions may include workbook bytes or JSON bind values.
        try:
            await db.rollback()
        finally:
            raise HTTPException(status_code=503, detail="Не удалось сохранить данные проверки. Повторите действие позже.") from None


async def _record_batch_activity(db: AsyncSession, admin: User, batch: AuditLegacyImport, event_type: str) -> None:
    metadata = {
        "batch_id": str(batch.id), "sha256": batch.sha256, "size_bytes": batch.size_bytes,
        "revision": batch.revision, "sheet_count": len(batch.inspection["sheets"]),
    }
    if batch.report is not None:
        for field in ("total_rows", "valid_rows", "error_rows", "warning_rows", "duplicate_rows", "issue_count"):
            metadata[field] = batch.report[field]
    await record_activity_event(db, admin.id, event_type, metadata=metadata)


async def _batch_or_404(db: AsyncSession, batch_id: UUID, *, for_update: bool = False) -> AuditLegacyImport:
    query = select(AuditLegacyImport).where(AuditLegacyImport.id == batch_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = (await db.execute(query)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Файл проверки не найден")
    return batch


def _check_revision(batch: AuditLegacyImport, revision: int) -> None:
    if batch.status not in ("uploaded", "checked"):
        raise HTTPException(status_code=409, detail="Операция доступна только для файлов проверки")
    if batch.revision != revision:
        raise HTTPException(status_code=409, detail="Файл проверки изменён. Обновите данные и повторите действие.")


async def _upload_bytes(file: UploadFile) -> bytes:
    try:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(status_code=415, detail="Допускаются только файлы XLSX")
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Размер файла превышает 10 МиБ")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Размер файла превышает 10 МиБ")
        if not data:
            raise HTTPException(status_code=422, detail="Файл пуст")
        return data
    finally:
        await file.close()


@router.get("", response_model=list[AuditLegacyBatchRead])
async def list_legacy_imports(db: AsyncSession = Depends(get_db)):
    batches = (await db.execute(
        select(AuditLegacyImport).order_by(AuditLegacyImport.created_at.desc(), AuditLegacyImport.id.desc())
    )).scalars().all()
    return [AuditLegacyBatchRead.model_validate(batch) for batch in batches]


@router.post("", response_model=AuditLegacyBatchRead)
async def upload_legacy_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_legacy_admin),
):
    data = await _upload_bytes(file)
    digest = sha256(data).hexdigest()
    await _lock_staging(db)
    existing = (await db.execute(
        select(AuditLegacyImport).where(AuditLegacyImport.sha256 == digest)
    )).scalar_one_or_none()
    if existing is not None:
        return AuditLegacyBatchRead.model_validate(existing)
    if await db.scalar(select(func.count()).select_from(AuditLegacyImport)) >= MAX_STAGING_BATCHES:
        raise HTTPException(status_code=409, detail="Достигнут лимит 20 файлов проверки. Удалите ненужный файл.")
    try:
        inspection = AuditLegacyInspection.model_validate(await _parse_workbook(inspect_legacy_workbook, data))
    except ValueError:
        raise HTTPException(status_code=422, detail="Не удалось проверить XLSX. Проверьте формат и содержимое книги.") from None
    batch = AuditLegacyImport(
        sha256=digest, size_bytes=len(data), source_bytes=data,
        inspection=inspection.model_dump(mode="json"), status="uploaded", revision=1,
        created_by_id=admin.id, updated_by_id=admin.id,
    )
    async with _staging_write(db):
        db.add(batch)
        await db.flush()
        await _record_batch_activity(db, admin, batch, "audit_legacy_uploaded")
        result = AuditLegacyBatchRead.model_validate(batch)
    return result


@router.get("/{batch_id}", response_model=AuditLegacyBatchRead)
async def get_legacy_import(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    return AuditLegacyBatchRead.model_validate(await _batch_or_404(db, batch_id))


@router.put("/{batch_id}/mapping", response_model=AuditLegacyBatchRead)
async def update_legacy_mapping(
    batch_id: UUID,
    payload: AuditLegacyMappingUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_legacy_admin),
):
    batch = await _batch_or_404(db, batch_id, for_update=True)
    _check_revision(batch, payload.revision)
    data = await db.scalar(select(AuditLegacyImport.source_bytes).where(AuditLegacyImport.id == batch_id))
    mapping = payload.mapping.model_dump(mode="json")
    try:
        report = AuditLegacyReport.model_validate(await _parse_workbook(preview_legacy_mapping, data, mapping))
    except ValueError:
        raise HTTPException(status_code=422, detail="Не удалось проверить сопоставление. Проверьте лист, строку заголовков и столбцы.") from None
    batch.mapping = mapping
    batch.report = report.model_dump(mode="json")
    batch.status = "checked"
    batch.revision += 1
    batch.updated_at = utc_now()
    batch.updated_by_id = admin.id
    async with _staging_write(db):
        await db.flush()
        await _record_batch_activity(db, admin, batch, "audit_legacy_mapping_checked")
        result = AuditLegacyBatchRead.model_validate(batch)
    return result


@router.get("/{batch_id}/source")
async def download_legacy_source(batch_id: UUID, db: AsyncSession = Depends(get_db)):
    data = await db.scalar(select(AuditLegacyImport.source_bytes).where(AuditLegacyImport.id == batch_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Файл проверки не найден")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={**SOURCE_HEADERS, "Content-Disposition": 'attachment; filename="audit-legacy-source.xlsx"'},
    )


@router.delete("/{batch_id}", status_code=204)
async def delete_legacy_import(
    batch_id: UUID,
    revision: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_legacy_admin),
):
    await _lock_staging(db)
    batch = await _batch_or_404(db, batch_id, for_update=True)
    _check_revision(batch, revision)
    async with _staging_write(db):
        await _record_batch_activity(db, admin, batch, "audit_legacy_deleted")
        await db.delete(batch)
    return Response(status_code=204, headers=SOURCE_HEADERS)
