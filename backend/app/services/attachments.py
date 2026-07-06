"""Task attachment storage and validation."""
from pathlib import Path
import uuid

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
_DOCUMENT_EXTENSIONS = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
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


def _detect_document_type(filename: str, data: bytes) -> tuple[str, str] | None:
    suffix = Path(filename).suffix.lower()
    if suffix not in _DOCUMENT_EXTENSIONS:
        return None
    if suffix in {".docx", ".xlsx"} and not data.startswith(b"PK\x03\x04"):
        return None
    if suffix == ".xls" and not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return None
    return _DOCUMENT_EXTENSIONS[suffix], suffix


def _uploads_root() -> Path:
    return Path(settings.UPLOAD_DIR).expanduser().resolve()


def attachment_path(attachment: TaskAttachment | QuickNoteAttachment) -> Path:
    return _uploads_root() / attachment.stored_filename

async def _read_attachment_upload(upload: UploadFile) -> tuple[str, str, str, bytes]:
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
            detail="Поддерживаются PNG, JPG, WEBP, GIF, DOCX, XLS и XLSX",
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

    original_filename, content_type, extension, data = await _read_attachment_upload(upload)

    stored_filename = f"{task.id}/{uuid.uuid4()}{extension}"
    file_path = _uploads_root() / stored_filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

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

    original_filename, content_type, extension, data = await _read_attachment_upload(upload)
    stored_filename = f"quick-notes/{note.id}/{uuid.uuid4()}{extension}"
    file_path = _uploads_root() / stored_filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(data)

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
