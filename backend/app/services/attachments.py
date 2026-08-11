"""Shared attachment storage and signature-based validation."""
from io import BytesIO
from pathlib import Path
import uuid
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import TaskAttachment
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note import QuickNote
from app.models.task import Task, TaskStatus
from app.models.user import User


_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_OOXML_EXTENSIONS = {
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "word/",
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xl/",
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt/",
    ),
}
_TEXT_EXTENSIONS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}
_ATTACHABLE_STATUSES = {TaskStatus.new, TaskStatus.estimated, TaskStatus.in_queue}


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _valid_ooxml_package(data: bytes, required_prefix: str) -> bool:
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
    except (BadZipFile, OSError, ValueError):
        return False
    if not entries or len(entries) > 4096:
        return False
    if any(entry.flag_bits & 0x1 for entry in entries):
        return False
    if sum(entry.file_size for entry in entries) > 256 * 1024 * 1024:
        return False
    names = [entry.filename for entry in entries]
    return "[Content_Types].xml" in names and any(
        name.startswith(required_prefix) for name in names
    )


def _detect_document_type(filename: str, data: bytes) -> tuple[str, str] | None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return ("application/pdf", suffix) if data.startswith(b"%PDF-") else None
    if suffix == ".xls":
        ole_signature = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        return ("application/vnd.ms-excel", suffix) if data.startswith(ole_signature) else None
    if suffix in _OOXML_EXTENSIONS:
        content_type, required_prefix = _OOXML_EXTENSIONS[suffix]
        return (content_type, suffix) if _valid_ooxml_package(data, required_prefix) else None
    if suffix in _TEXT_EXTENSIONS:
        if b"\x00" in data:
            return None
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        return _TEXT_EXTENSIONS[suffix], suffix
    return None


def _uploads_root() -> Path:
    return Path(settings.UPLOAD_DIR).expanduser().resolve()


def stored_attachment_path(stored_filename: str) -> Path:
    """Resolve one generated storage key and reject paths outside UPLOAD_DIR."""
    root = _uploads_root()
    candidate = (root / stored_filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Attachment file not found") from error
    return candidate


def attachment_path(attachment: TaskAttachment | QuickNoteAttachment) -> Path:
    return stored_attachment_path(attachment.stored_filename)


def write_attachment_bytes(stored_filename: str, data: bytes) -> Path:
    file_path = stored_attachment_path(stored_filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = file_path.with_name(
        f".{file_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_bytes(data)
        temporary_path.replace(file_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return file_path


async def read_attachment_upload(upload: UploadFile) -> tuple[str, str, str, bytes]:
    data = await upload.read(settings.MAX_TASK_ATTACHMENT_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(data) > settings.MAX_TASK_ATTACHMENT_BYTES:
        mb = settings.MAX_TASK_ATTACHMENT_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Файл больше {mb} МБ")

    original_filename = Path(upload.filename or "attachment").name[:255] or "attachment"
    content_type = _detect_image_type(data)
    extension = _IMAGE_EXTENSIONS.get(content_type or "")
    if content_type is None:
        document_type = _detect_document_type(original_filename, data)
        if document_type is not None:
            content_type, extension = document_type
    if content_type is None or extension is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Поддерживаются PNG, JPG, WEBP, GIF, PDF, DOCX, XLS, XLSX, "
                "PPTX, TXT, MD и CSV"
            ),
        )
    return original_filename, content_type, extension, data


def ensure_task_can_accept_attachment(task: Task) -> None:
    if task.status not in _ATTACHABLE_STATUSES or task.assignee_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Вложения можно добавлять только до взятия задачи в работу",
        )


async def save_task_attachment(
    db: AsyncSession,
    task: Task,
    uploader: User,
    upload: UploadFile,
) -> TaskAttachment:
    ensure_task_can_accept_attachment(task)

    count_result = await db.execute(
        select(func.count(TaskAttachment.id)).where(TaskAttachment.task_id == task.id)
    )
    attachments_count = count_result.scalar_one()
    if attachments_count >= settings.MAX_TASK_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"К задаче можно прикрепить не более {settings.MAX_TASK_ATTACHMENTS} файлов",
        )

    original_filename, content_type, extension, data = await read_attachment_upload(upload)

    stored_filename = f"{task.id}/{uuid.uuid4()}{extension}"
    file_path = write_attachment_bytes(stored_filename, data)

    attachment = TaskAttachment(
        task_id=task.id,
        uploaded_by_id=uploader.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(attachment)
    try:
        await db.flush()
        await db.refresh(attachment)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return attachment

async def save_quick_note_attachment(
    db: AsyncSession,
    *,
    note: QuickNote,
    uploader: User,
    upload: UploadFile,
) -> QuickNoteAttachment:
    """Validate and persist a file attached to a quick note."""
    attachments_count = await db.scalar(
        select(func.count(QuickNoteAttachment.id)).where(QuickNoteAttachment.note_id == note.id)
    )
    if attachments_count >= settings.MAX_TASK_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"К заметке можно прикрепить не более {settings.MAX_TASK_ATTACHMENTS} файлов",
        )

    original_filename, content_type, extension, data = await read_attachment_upload(upload)
    stored_filename = f"quick-notes/{note.id}/{uuid.uuid4()}{extension}"
    file_path = write_attachment_bytes(stored_filename, data)

    attachment = QuickNoteAttachment(
        note_id=note.id,
        uploaded_by_id=uploader.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(attachment)
    try:
        await db.flush()
        await db.refresh(attachment)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return attachment
