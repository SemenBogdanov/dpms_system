"""Domain rules for versioned personal-task materials."""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.personal_task import PersonalTask
from app.models.personal_task_artifact import (
    PersonalTaskArtifact,
    PersonalTaskArtifactVersion,
    utc_now,
)
from app.models.user import User
from app.services.attachments import (
    read_attachment_upload,
    stored_attachment_path,
    write_attachment_bytes,
)
from app.services.storage_quota import (
    abandon_storage_reservation,
    activate_storage_file,
    reserve_storage_file,
)


ARTIFACT_TYPES = {"document", "link", "result"}


def clean_title(value: str) -> str:
    title = (value or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Укажите название материала")
    if len(title) > 200:
        raise HTTPException(status_code=422, detail="Название материала длиннее 200 символов")
    return title


def clean_optional(value: str | None, *, limit: int | None = None) -> str | None:
    cleaned = value.strip() if value else ""
    if not cleaned:
        return None
    if limit is not None and len(cleaned) > limit:
        raise HTTPException(status_code=422, detail=f"Текст длиннее {limit} символов")
    return cleaned


def normalize_artifact_url(value: str | None) -> str | None:
    cleaned = clean_optional(value, limit=2048)
    if cleaned is None:
        return None
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="Укажите корректную HTTP(S)-ссылку без логина и пароля",
        )
    return cleaned


def ensure_task_accepts_artifact_changes(task: PersonalTask) -> None:
    if task.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Архивная задача хранит материалы только для чтения. Сначала восстановите задачу.",
        )


def _source_kind(
    artifact_type: str,
    upload: UploadFile | None,
    url: str | None,
) -> tuple[str, str | None]:
    has_file = upload is not None and bool(upload.filename)
    normalized_url = normalize_artifact_url(url)
    has_url = normalized_url is not None
    if has_file == has_url:
        raise HTTPException(
            status_code=422,
            detail="Добавьте либо один файл, либо одну ссылку",
        )
    if artifact_type == "document" and not has_file:
        raise HTTPException(status_code=422, detail="Для документа требуется файл")
    if artifact_type == "link" and not has_url:
        raise HTTPException(status_code=422, detail="Для ссылки требуется URL")
    return ("file", None) if has_file else ("link", normalized_url)


async def _version_payload(
    *,
    task_id: uuid.UUID,
    artifact_id: uuid.UUID,
    owner_id: uuid.UUID,
    upload: UploadFile | None,
    url: str | None,
    artifact_type: str,
) -> tuple[dict, Path | None, uuid.UUID | None]:
    source_kind, normalized_url = _source_kind(artifact_type, upload, url)
    if source_kind == "link":
        return {
            "source_kind": source_kind,
            "url": normalized_url,
            "original_filename": None,
            "stored_filename": None,
            "content_type": None,
            "size_bytes": None,
            "sha256": None,
        }, None, None

    assert upload is not None
    original_filename, content_type, extension, data = await read_attachment_upload(upload)
    stored_filename = (
        f"personal-tasks/{task_id}/artifacts/{artifact_id}/{uuid.uuid4()}{extension}"
    )
    reservation = await reserve_storage_file(
        owner_id=owner_id,
        stored_filename=stored_filename,
        size_bytes=len(data),
        category="personal_task_artifact",
    )
    try:
        file_path = write_attachment_bytes(stored_filename, data)
    except Exception:
        await abandon_storage_reservation(reservation.id)
        raise
    return {
        "source_kind": source_kind,
        "url": None,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }, file_path, reservation.id


async def create_artifact(
    db: AsyncSession,
    *,
    task: PersonalTask,
    user: User,
    artifact_type: str,
    title: str,
    description: str | None,
    change_note: str | None,
    upload: UploadFile | None,
    url: str | None,
) -> tuple[PersonalTaskArtifact, PersonalTaskArtifactVersion]:
    ensure_task_accepts_artifact_changes(task)
    if artifact_type not in ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Некорректный тип материала")
    artifacts_count = int(
        await db.scalar(
            select(func.count(PersonalTaskArtifact.id)).where(
                PersonalTaskArtifact.task_id == task.id
            )
        )
        or 0
    )
    if artifacts_count >= settings.MAX_PERSONAL_TASK_ARTIFACTS:
        raise HTTPException(
            status_code=409,
            detail=(
                "К личной задаче можно добавить не более "
                f"{settings.MAX_PERSONAL_TASK_ARTIFACTS} материалов"
            ),
        )

    artifact = PersonalTaskArtifact(
        id=uuid.uuid4(),
        task_id=task.id,
        artifact_type=artifact_type,
        title=clean_title(title),
        description=clean_optional(description),
        status="active",
        current_version=1,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    payload, file_path, storage_file_id = await _version_payload(
        task_id=task.id,
        artifact_id=artifact.id,
        owner_id=task.owner_id,
        upload=upload,
        url=url,
        artifact_type=artifact_type,
    )
    version = PersonalTaskArtifactVersion(
        artifact=artifact,
        version_number=1,
        change_note=clean_optional(change_note, limit=500),
        created_by_id=user.id,
        **payload,
    )
    db.add_all([artifact, version])
    activation_started = False
    try:
        await db.flush()
        if storage_file_id is not None:
            activation_started = True
            await activate_storage_file(db, storage_file_id)
            await db.flush()
    except Exception:
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        if storage_file_id is not None and not activation_started:
            await abandon_storage_reservation(storage_file_id)
        raise
    return artifact, version


async def add_artifact_version(
    db: AsyncSession,
    *,
    task: PersonalTask,
    artifact: PersonalTaskArtifact,
    user: User,
    change_note: str | None,
    upload: UploadFile | None,
    url: str | None,
) -> PersonalTaskArtifactVersion:
    ensure_task_accepts_artifact_changes(task)
    if artifact.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Сначала восстановите материал из архива",
        )
    versions_count = int(
        await db.scalar(
            select(func.count(PersonalTaskArtifactVersion.id)).where(
                PersonalTaskArtifactVersion.artifact_id == artifact.id
            )
        )
        or 0
    )
    if versions_count >= settings.MAX_PERSONAL_TASK_ARTIFACT_VERSIONS:
        raise HTTPException(
            status_code=409,
            detail=(
                "У материала может быть не более "
                f"{settings.MAX_PERSONAL_TASK_ARTIFACT_VERSIONS} версий"
            ),
        )

    payload, file_path, storage_file_id = await _version_payload(
        task_id=task.id,
        artifact_id=artifact.id,
        owner_id=task.owner_id,
        upload=upload,
        url=url,
        artifact_type=artifact.artifact_type,
    )
    next_version = artifact.current_version + 1
    version = PersonalTaskArtifactVersion(
        artifact=artifact,
        version_number=next_version,
        change_note=clean_optional(change_note, limit=500),
        created_by_id=user.id,
        **payload,
    )
    artifact.current_version = next_version
    artifact.updated_by_id = user.id
    artifact.updated_at = utc_now()
    db.add(version)
    activation_started = False
    try:
        await db.flush()
        if storage_file_id is not None:
            activation_started = True
            await activate_storage_file(db, storage_file_id)
            await db.flush()
    except Exception:
        if file_path is not None:
            file_path.unlink(missing_ok=True)
        if storage_file_id is not None and not activation_started:
            await abandon_storage_reservation(storage_file_id)
        raise
    return version


def remove_version_file(version: PersonalTaskArtifactVersion) -> None:
    """Best-effort cleanup after an explicitly committed permanent deletion."""
    if version.source_kind != "file" or not version.stored_filename:
        return
    try:
        stored_attachment_path(version.stored_filename).unlink(missing_ok=True)
    except (HTTPException, OSError):
        return
