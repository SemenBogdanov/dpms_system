"""Task attachment storage and validation."""
from pathlib import Path
import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attachment import TaskAttachment
from app.models.task import Task, TaskStatus
from app.models.user import User


_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
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


def _uploads_root() -> Path:
    return Path(settings.UPLOAD_DIR).expanduser().resolve()


def attachment_path(attachment: TaskAttachment) -> Path:
    return _uploads_root() / attachment.stored_filename


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

    data = await upload.read(settings.MAX_TASK_ATTACHMENT_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(data) > settings.MAX_TASK_ATTACHMENT_BYTES:
        mb = settings.MAX_TASK_ATTACHMENT_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Файл больше {mb} МБ")

    content_type = _detect_image_type(data)
    if content_type is None:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только PNG, JPG, WEBP и GIF",
        )

    original_filename = Path(upload.filename or "screenshot").name[:255] or "screenshot"
    stored_filename = f"{task.id}/{uuid.uuid4()}{_IMAGE_EXTENSIONS[content_type]}"
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
