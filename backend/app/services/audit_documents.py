"""Validation and immutable storage for audit source documents."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import shutil
import uuid
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile

from app.config import settings
from app.models.audit import AuditDocument
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


MAX_AUDIT_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_AUDIT_DOCUMENTS_PER_BATCH = 20
MAX_AUDIT_BATCH_BYTES = 100 * 1024 * 1024
MAX_OFFICE_PACKAGE_MEMBERS = 5_000
MAX_OFFICE_PACKAGE_UNCOMPRESSED_BYTES = 150 * 1024 * 1024

_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class PreparedAuditDocument:
    original_filename: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str
    data: bytes


@dataclass(frozen=True)
class StagedAuditDocument:
    stored_filename: str
    pending_path: Path
    final_path: Path


def _validate_office_package(data: bytes, extension: str) -> None:
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_OFFICE_PACKAGE_MEMBERS:
                raise HTTPException(status_code=400, detail="Файл Office содержит слишком много элементов")
            total_uncompressed = 0
            names: set[str] = set()
            for member in members:
                normalized_name = member.filename.replace("\\", "/")
                comparable_name = normalized_name[:-1] if normalized_name.endswith("/") else normalized_name
                parts = comparable_name.split("/")
                if (
                    not comparable_name
                    or normalized_name.startswith("/")
                    or any(part in {"", ".", ".."} for part in parts)
                ):
                    raise HTTPException(status_code=400, detail="Файл Office содержит небезопасный путь")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_OFFICE_PACKAGE_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=400, detail="Распакованный файл Office слишком большой")
                names.add(normalized_name)
    except (BadZipFile, OSError):
        raise HTTPException(status_code=400, detail="Файл Office поврежден или имеет неверный формат")
    if "[Content_Types].xml" not in names:
        raise HTTPException(status_code=400, detail="Файл Office поврежден или имеет неверный формат")
    required_prefix = "word/" if extension == ".docx" else "xl/"
    if not any(name.startswith(required_prefix) for name in names):
        raise HTTPException(status_code=400, detail="Расширение файла не соответствует его содержимому")


async def prepare_audit_document(upload: UploadFile) -> PreparedAuditDocument:
    original_filename = Path(upload.filename or "document").name[:255] or "document"
    data = await upload.read(MAX_AUDIT_DOCUMENT_BYTES + 1)
    return prepare_audit_document_bytes(original_filename, data)


def prepare_audit_document_bytes(original_filename: str, data: bytes) -> PreparedAuditDocument:
    """Validate a bounded in-memory document received from any trusted transport."""

    original_filename = Path(original_filename or "document").name[:255] or "document"
    extension = Path(original_filename).suffix.lower()
    content_type = _MIME_BY_EXTENSION.get(extension)
    if content_type is None:
        raise HTTPException(status_code=400, detail="Для ТЗ поддерживаются PDF, DOCX и XLSX")
    if not data:
        raise HTTPException(status_code=400, detail=f"Файл {original_filename} пустой")
    if len(data) > MAX_AUDIT_DOCUMENT_BYTES:
        raise HTTPException(status_code=400, detail=f"Файл {original_filename} больше 25 МБ")

    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail=f"Файл {original_filename} не является PDF")
    if extension in {".docx", ".xlsx"}:
        _validate_office_package(data, extension)

    return PreparedAuditDocument(
        original_filename=original_filename,
        extension=extension,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        data=data,
    )


def audit_document_path(document: AuditDocument) -> Path:
    return Path(settings.UPLOAD_DIR).expanduser().resolve() / document.stored_filename


def persist_audit_document_file(case_id: uuid.UUID, prepared: PreparedAuditDocument) -> tuple[str, Path]:
    stored_filename = f"audit/{case_id}/{uuid.uuid4()}{prepared.extension}"
    file_path = Path(settings.UPLOAD_DIR).expanduser().resolve() / stored_filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(prepared.data)
    return stored_filename, file_path


def stage_audit_document_file(case_id: uuid.UUID, prepared: PreparedAuditDocument) -> StagedAuditDocument:
    """Durably stage a file before DB commit without exposing a partial final file."""

    stored_filename = f"audit/{case_id}/{uuid.uuid4()}{prepared.extension}"
    final_path = Path(settings.UPLOAD_DIR).expanduser().resolve() / stored_filename
    final_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = final_path.with_name(f"{final_path.name}.pending")
    partial_path = final_path.with_name(f".{final_path.name}.{uuid.uuid4()}.part")
    try:
        with partial_path.open("xb") as handle:
            handle.write(prepared.data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial_path, pending_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        pending_path.unlink(missing_ok=True)
        raise
    return StagedAuditDocument(stored_filename, pending_path, final_path)


def finalize_staged_audit_document(staged: StagedAuditDocument) -> None:
    staged.final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged.pending_path, staged.final_path)


def finalize_pending_audit_document(stored_filename: str) -> bool:
    """Finalize one committed document after an interrupted API response."""

    root = Path(settings.UPLOAD_DIR).expanduser().resolve()
    final_path = (root / stored_filename).resolve()
    try:
        final_path.relative_to(root)
    except ValueError:
        raise RuntimeError("Audit document path is outside the upload directory")
    pending_path = final_path.with_name(f"{final_path.name}.pending")
    if final_path.exists():
        pending_path.unlink(missing_ok=True)
        return True
    if not pending_path.exists():
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(pending_path, final_path)
    return True


def discard_staged_audit_document(staged: StagedAuditDocument) -> None:
    staged.pending_path.unlink(missing_ok=True)


def remove_audit_case_files(case_id: uuid.UUID, stored_filenames: list[str]) -> None:
    """Best-effort removal after the audit case transaction has committed."""

    root = Path(settings.UPLOAD_DIR).expanduser().resolve()
    audit_root = (root / "audit").resolve()
    for stored_filename in stored_filenames:
        candidate = (root / stored_filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        candidate.unlink(missing_ok=True)
        candidate.with_name(f"{candidate.name}.pending").unlink(missing_ok=True)

    case_directory = audit_root / str(case_id)
    try:
        case_directory.relative_to(audit_root)
    except ValueError:
        return
    if case_directory.is_symlink():
        case_directory.unlink(missing_ok=True)
    elif case_directory.is_dir():
        shutil.rmtree(case_directory, ignore_errors=True)


async def reconcile_staged_audit_documents(db: AsyncSession) -> tuple[int, int]:
    """Finalize committed files and remove staging files with no DB owner."""

    root = Path(settings.UPLOAD_DIR).expanduser().resolve()
    audit_root = root / "audit"
    if not audit_root.exists():
        return 0, 0
    pending_paths = [path for path in audit_root.rglob("*.pending") if path.is_file()]
    if not pending_paths:
        return 0, 0
    stored_by_path: dict[Path, str] = {}
    for pending in pending_paths:
        final_path = pending.with_name(pending.name.removesuffix(".pending"))
        try:
            stored_by_path[pending] = final_path.relative_to(root).as_posix()
        except ValueError:
            continue
    existing = set(
        await db.scalars(
            select(AuditDocument.stored_filename).where(
                AuditDocument.stored_filename.in_(list(stored_by_path.values()))
            )
        )
    )
    finalized = 0
    removed = 0
    for pending, stored_filename in stored_by_path.items():
        final_path = root / stored_filename
        if stored_filename in existing:
            if final_path.exists():
                pending.unlink(missing_ok=True)
            else:
                os.replace(pending, final_path)
            finalized += 1
        else:
            pending.unlink(missing_ok=True)
            removed += 1
    return finalized, removed
