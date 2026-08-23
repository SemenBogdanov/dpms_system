"""Admin API for one OpenAI-compatible AI provider profile."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.config import settings
from app.models.ai_provider import (
    AIProviderConfig,
    AIProviderEvent,
    AuditAtomizationSkill,
    AuditAtomizationSkillVersion,
)
from app.models.user import User
from app.schemas.ai_provider import AIProviderRead, AIProviderTestRead, AIProviderUpsert
from app.schemas.audit_ai import (
    AuditAtomizationSkillList,
    AuditAtomizationSkillVersionRead,
)
from app.services.ai_provider import (
    AIProviderError,
    ai_allowlist_configured,
    ai_provider_ready,
    ai_secret_configured,
    encrypt_ai_api_key,
    generate_text,
    normalize_ai_base_url,
)
from app.services.audit_ai_atomization import MAX_SKILL_BYTES, parse_audit_skill_package


router = APIRouter()


def _http_error(error: AIProviderError) -> HTTPException:
    return HTTPException(error.status_code, detail={"code": error.code, "message": error.message})


async def _config(db: AsyncSession) -> AIProviderConfig | None:
    return await db.scalar(
        select(AIProviderConfig).where(AIProviderConfig.provider_kind == "openai_compatible")
    )


def _read(config: AIProviderConfig | None) -> AIProviderRead:
    common = {
        "allowed_origins_configured": ai_allowlist_configured(),
        "encryption_key_configured": ai_secret_configured(),
    }
    if config is None:
        return AIProviderRead(
            configured=False,
            display_name=settings.AI_PROVIDER_DEFAULT_DISPLAY_NAME or None,
            base_url=settings.AI_PROVIDER_DEFAULT_BASE_URL or None,
            model_name=settings.AI_PROVIDER_DEFAULT_MODEL_NAME or None,
            **common,
        )
    return AIProviderRead(
        configured=True,
        id=config.id,
        provider_kind=config.provider_kind,
        display_name=config.display_name,
        base_url=config.base_url,
        model_name=config.model_name,
        enabled=config.enabled,
        api_key_configured=bool(config.api_key_ciphertext),
        config_version=config.config_version,
        last_tested_at=config.last_tested_at,
        last_test_status=config.last_test_status,
        last_verified_config_version=config.last_verified_config_version,
        ready_for_use=ai_provider_ready(config),
        last_error_code=config.last_error_code,
        updated_at=config.updated_at,
        **common,
    )


def _event(
    db: AsyncSession,
    *,
    provider_id,
    actor_id,
    event_type: str,
    outcome: str,
    error_code: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AIProviderEvent(
            provider_id=provider_id,
            actor_id=actor_id,
            event_type=event_type,
            outcome=outcome,
            error_code=error_code[:80] if error_code else None,
            payload_json=payload,
        )
    )


def _skill_read(
    skill: AuditAtomizationSkill,
    version: AuditAtomizationSkillVersion,
) -> AuditAtomizationSkillVersionRead:
    return AuditAtomizationSkillVersionRead(
        id=version.id,
        skill_id=skill.id,
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        version=version.version_label,
        schema_version=version.schema_version,
        content_sha256=version.content_sha256,
        source_filename=version.source_filename,
        is_enabled=skill.is_enabled,
        is_active=version.is_active,
        created_at=version.created_at,
        activated_at=version.activated_at,
    )


@router.get("/skills", response_model=AuditAtomizationSkillList)
async def list_audit_atomization_skills(
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .order_by(
                AuditAtomizationSkill.name.asc(),
                AuditAtomizationSkillVersion.created_at.desc(),
            )
        )
    ).all()
    return AuditAtomizationSkillList(items=[_skill_read(skill, version) for skill, version in rows])


@router.post(
    "/skills/import",
    response_model=AuditAtomizationSkillVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_audit_atomization_skill(
    file: UploadFile = File(...),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read(MAX_SKILL_BYTES + 1)
    package, content_sha256 = parse_audit_skill_package(file.filename or "audit-skill.json", data)
    admin_id = admin.id
    existing_version = await db.scalar(
        select(AuditAtomizationSkillVersion).where(
            AuditAtomizationSkillVersion.content_sha256 == content_sha256
        )
    )
    if existing_version is not None:
        skill = await db.get(AuditAtomizationSkill, existing_version.skill_id)
        if skill is None:
            raise HTTPException(status_code=500, detail="Skill поврежден в базе данных")
        return _skill_read(skill, existing_version)

    skill = await db.scalar(
        select(AuditAtomizationSkill)
        .where(AuditAtomizationSkill.slug == package.slug)
        .with_for_update()
    )
    if skill is None:
        skill = AuditAtomizationSkill(
            slug=package.slug,
            name=package.name,
            description=package.description,
            is_enabled=True,
            created_by_id=admin_id,
            updated_by_id=admin_id,
        )
        db.add(skill)
        await db.flush()
    else:
        same_label = await db.scalar(
            select(AuditAtomizationSkillVersion.id).where(
                AuditAtomizationSkillVersion.skill_id == skill.id,
                AuditAtomizationSkillVersion.version_label == package.version,
            )
        )
        if same_label is not None:
            raise HTTPException(
                status_code=409,
                detail="Версия skill уже существует с другим содержимым; укажите новый version",
            )
        skill.name = package.name
        skill.description = package.description
        skill.is_enabled = True
        skill.updated_by_id = admin_id

    await db.execute(
        update(AuditAtomizationSkillVersion)
        .where(AuditAtomizationSkillVersion.skill_id == skill.id)
        .values(is_active=False)
    )
    now = datetime.now(timezone.utc)
    version = AuditAtomizationSkillVersion(
        skill_id=skill.id,
        version_label=package.version,
        schema_version=package.schema_version,
        instructions_text=package.instructions,
        rules_json=package.rules,
        content_sha256=content_sha256,
        source_filename=Path(file.filename or "audit-skill.json").name[:255],
        is_active=True,
        created_by_id=admin_id,
        activated_at=now,
    )
    db.add(version)
    _event(
        db,
        provider_id=None,
        actor_id=admin_id,
        event_type="audit_skill_imported",
        outcome="success",
        payload={"slug": skill.slug, "version": version.version_label},
    )
    await db.flush()
    await db.refresh(skill)
    await db.refresh(version)
    return _skill_read(skill, version)


@router.post(
    "/skills/{version_id}/activate",
    response_model=AuditAtomizationSkillVersionRead,
)
async def activate_audit_atomization_skill(
    version_id: UUID,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .where(AuditAtomizationSkillVersion.id == version_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Версия skill не найдена")
    skill, version = row
    await db.execute(
        update(AuditAtomizationSkillVersion)
        .where(AuditAtomizationSkillVersion.skill_id == skill.id)
        .values(is_active=False)
    )
    version.is_active = True
    version.activated_at = datetime.now(timezone.utc)
    skill.is_enabled = True
    skill.updated_by_id = admin.id
    _event(
        db,
        provider_id=None,
        actor_id=admin.id,
        event_type="audit_skill_activated",
        outcome="success",
        payload={"slug": skill.slug, "version": version.version_label},
    )
    await db.flush()
    await db.refresh(skill)
    await db.refresh(version)
    return _skill_read(skill, version)


@router.get("", response_model=AIProviderRead)
async def get_ai_provider(
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return _read(await _config(db))


@router.put("", response_model=AIProviderRead)
async def save_ai_provider(
    body: AIProviderUpsert,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    admin_id = admin.id
    try:
        base_url = normalize_ai_base_url(body.base_url)
    except AIProviderError as error:
        raise _http_error(error)
    config = await _config(db)
    if config is None and body.api_key is None:
        raise HTTPException(status_code=422, detail="Для нового подключения нужен API key")
    if config is None and body.expected_config_version is not None:
        raise HTTPException(status_code=409, detail="Конфигурация ИИ изменилась; обновите страницу")
    if config is not None and body.expected_config_version != config.config_version:
        raise HTTPException(status_code=409, detail="Конфигурация ИИ изменилась; обновите страницу")

    snapshot = None if config is None else {
        "id": config.id,
        "config_version": config.config_version,
        "api_key_ciphertext": config.api_key_ciphertext,
    }
    supplied_key = body.api_key.get_secret_value() if body.api_key else None
    body.api_key = None
    try:
        encrypted_key = (
            encrypt_ai_api_key(supplied_key)
            if supplied_key is not None
            else snapshot["api_key_ciphertext"] if snapshot else None
        )
    except AIProviderError as error:
        supplied_key = None
        raise _http_error(error)
    supplied_key = None
    if encrypted_key is None:
        raise HTTPException(status_code=422, detail="Для нового подключения нужен API key")

    await db.rollback()
    tested_at = datetime.now(timezone.utc)
    candidate = SimpleNamespace(
        enabled=body.enabled,
        base_url=base_url,
        model_name=body.model_name,
        api_key_ciphertext=encrypted_key,
    )
    try:
        await generate_text(
            candidate,
            [{"role": "user", "content": "Ответь одним словом: OK"}],
            max_tokens=8,
            temperature=0,
            allow_disabled=True,
            allow_unverified=True,
        )
    except AIProviderError as error:
        _event(
            db,
            provider_id=None,
            actor_id=admin_id,
            event_type="candidate_verification",
            outcome="error",
            error_code=error.code,
            payload={"existing_config": snapshot is not None},
        )
        await db.commit()
        raise _http_error(error)

    locked_config = await db.scalar(
        select(AIProviderConfig)
        .where(AIProviderConfig.provider_kind == "openai_compatible")
        .with_for_update()
    )
    if snapshot is None:
        if locked_config is not None:
            raise HTTPException(status_code=409, detail="Конфигурация ИИ изменилась; повторите проверку")
        config = AIProviderConfig(
            provider_kind="openai_compatible",
            display_name=body.display_name,
            base_url=base_url,
            model_name=body.model_name,
            api_key_ciphertext=encrypted_key,
            enabled=body.enabled,
            config_version=1,
            last_tested_at=tested_at,
            last_test_status="ok",
            last_verified_config_version=1,
            created_by_id=admin_id,
            updated_by_id=admin_id,
        )
        db.add(config)
    else:
        if locked_config is None or locked_config.config_version != snapshot["config_version"]:
            raise HTTPException(status_code=409, detail="Конфигурация ИИ изменилась; повторите проверку")
        config = locked_config
        config.display_name = body.display_name
        config.base_url = base_url
        config.model_name = body.model_name
        config.enabled = body.enabled
        config.updated_by_id = admin_id
        config.config_version += 1
        config.api_key_ciphertext = encrypted_key
        config.last_tested_at = tested_at
        config.last_test_status = "ok"
        config.last_verified_config_version = config.config_version
        config.last_error_code = None
    await db.flush()
    _event(
        db,
        provider_id=config.id,
        actor_id=admin_id,
        event_type="config_verified_saved",
        outcome="success",
        payload={"model_name": config.model_name, "enabled": config.enabled, "tested": True},
    )
    await db.flush()
    await db.refresh(config)
    return _read(config)


@router.post("/test", response_model=AIProviderTestRead)
async def test_ai_provider(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    config = await _config(db)
    if config is None:
        raise HTTPException(status_code=409, detail="ИИ-провайдер еще не настроен")
    tested_at = datetime.now(timezone.utc)
    try:
        await generate_text(
            config,
            [{"role": "user", "content": "Ответь одним словом: OK"}],
            max_tokens=8,
            temperature=0,
            allow_disabled=True,
            allow_unverified=True,
        )
    except AIProviderError as error:
        config.last_tested_at = tested_at
        config.last_test_status = "error"
        config.last_verified_config_version = None
        config.last_error_code = error.code[:80]
        _event(
            db,
            provider_id=config.id,
            actor_id=admin.id,
            event_type="connection_test",
            outcome="error",
            error_code=error.code,
        )
        await db.commit()
        raise _http_error(error)
    config.last_tested_at = tested_at
    config.last_test_status = "ok"
    config.last_verified_config_version = config.config_version
    config.last_error_code = None
    _event(
        db,
        provider_id=config.id,
        actor_id=admin.id,
        event_type="connection_test",
        outcome="success",
    )
    return AIProviderTestRead(
        ok=True,
        model_name=config.model_name,
        message="Подключение к ИИ-провайдеру подтверждено",
        tested_at=tested_at,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_provider(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    config = await _config(db)
    if config is not None:
        _event(
            db,
            provider_id=None,
            actor_id=admin.id,
            event_type="config_deleted",
            outcome="success",
            payload={"model_name": config.model_name},
        )
        await db.delete(config)
    return None
