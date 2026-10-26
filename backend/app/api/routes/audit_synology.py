"""Admin-only Synology File Station integration for Audit source documents."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.audit import (
    AuditCase,
    AuditDocument,
    AuditSynologyConnection,
    AuditSynologyEvent,
    AuditSynologyImport,
    AuditSynologyImportBatch,
)
from app.models.user import User
from app.schemas.audit_synology import (
    AuditSynologyBrowserRead,
    AuditSynologyBrowseRequest,
    AuditSynologyActivateRequest,
    AuditSynologyCommitRequest,
    AuditSynologyConnectionListRead,
    AuditSynologyConnectionRead,
    AuditSynologyConnectRead,
    AuditSynologyDisconnectRequest,
    AuditSynologyFileRead,
    AuditSynologyImportItemRead,
    AuditSynologyImportRead,
    AuditSynologyPreviewItem,
    AuditSynologyPreviewRead,
    AuditSynologySelectionRequest,
    AuditSynologySaveRequest,
)
from app.services.audit_documents import (
    StagedAuditDocument,
    discard_staged_audit_document,
    finalize_pending_audit_document,
    finalize_staged_audit_document,
    prepare_audit_document_bytes,
    stage_audit_document_file,
)
from app.services.audit_import import record_audit_event
from app.services.audit_synology import (
    MAX_SYNOLOGY_BATCH_BYTES,
    MAX_SYNOLOGY_FILES_PER_IMPORT,
    MAX_SYNOLOGY_FILE_BYTES,
    SYNOLOGY_PREVIEW_TTL_SECONDS,
    SynologyConnectorError,
    SynologyFileInfo,
    SynologyFileStationClient,
    build_path_token,
    build_preview_token,
    connector_request_hash,
    connector_secret_configured,
    decrypt_synology_password,
    encrypt_synology_password,
    ensure_path_within_root,
    normalize_remote_path,
    normalize_root_path,
    normalize_synology_base_url,
    remote_path_fingerprint,
    synology_allowlist_configured,
    synology_profile_mutation_lock,
    synology_session_store,
    verify_path_token,
    verify_preview_token,
)


router = APIRouter()


def _http_error(error: SynologyConnectorError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


def _profile_changed_error(message: str = "Профиль Synology изменился; обновите страницу") -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "profile_changed", "message": message},
    )


async def _connection(db: AsyncSession, connection_id: UUID) -> AuditSynologyConnection:
    connection = await db.get(AuditSynologyConnection, connection_id)
    if connection is None or connection.provider != "synology":
        raise HTTPException(status_code=404, detail="Профиль Synology не найден")
    return connection


async def _active_connection_or_none(db: AsyncSession) -> AuditSynologyConnection | None:
    return await db.scalar(
        select(AuditSynologyConnection).where(
            AuditSynologyConnection.provider == "synology",
            AuditSynologyConnection.is_active.is_(True),
        )
    )


async def _active_connection(db: AsyncSession) -> AuditSynologyConnection:
    connection = await _active_connection_or_none(db)
    if connection is None:
        raise HTTPException(status_code=409, detail="Активный профиль Synology не выбран")
    if not connection.enabled:
        raise HTTPException(status_code=409, detail="Подключение Synology отключено")
    return connection


def _connection_read(connection: AuditSynologyConnection) -> AuditSynologyConnectionRead:
    return AuditSynologyConnectionRead(
        configured=True,
        id=connection.id,
        display_name=connection.display_name,
        base_url=connection.base_url,
        account_name=connection.account_name,
        root_path=connection.root_path,
        enabled=connection.enabled,
        is_active=connection.is_active,
        credential_saved=bool(connection.password_ciphertext),
        config_version=connection.config_version,
        last_tested_at=connection.last_tested_at,
        last_test_status=connection.last_test_status,
        last_error_code=connection.last_error_code,
        allowed_origins_configured=synology_allowlist_configured(),
        encryption_key_configured=connector_secret_configured(),
        updated_at=connection.updated_at,
    )


def _record_connector_event(
    db: AsyncSession,
    *,
    connection_id,
    actor_id,
    event_type: str,
    outcome: str,
    item_count: int = 0,
    error_code: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AuditSynologyEvent(
            connection_id=connection_id,
            actor_id=actor_id,
            event_type=event_type,
            outcome=outcome,
            item_count=item_count,
            error_code=error_code[:80] if error_code else None,
            payload_json=payload,
        )
    )


async def _session(body_token: str, admin: User, connection: AuditSynologyConnection):
    try:
        return await synology_session_store.get(
            body_token,
            user_id=admin.id,
            connection_id=connection.id,
            config_version=connection.config_version,
        )
    except SynologyConnectorError as error:
        raise _http_error(error)


async def _existing_remote_versions(
    db: AsyncSession,
    connection: AuditSynologyConnection,
    files: list[SynologyFileInfo],
) -> set[tuple[str, int, int]]:
    keys = {
        (remote_path_fingerprint(connection.base_url, item.path), item.size_bytes, item.modified_at)
        for item in files
        if not item.is_dir
    }
    if not keys:
        return set()
    fingerprints = {key[0] for key in keys}
    result = await db.execute(
        select(
            AuditSynologyImport.remote_path_fingerprint,
            AuditSynologyImport.remote_size,
            AuditSynologyImport.remote_mtime,
        ).where(
            AuditSynologyImport.remote_path_fingerprint.in_(fingerprints),
        )
    )
    return {tuple(row) for row in result.all()} & keys


async def _finalize_committed_batch_files(
    db: AsyncSession,
    batch: AuditSynologyImportBatch,
) -> None:
    stored_filenames = await db.scalars(
        select(AuditDocument.stored_filename)
        .join(AuditSynologyImport, AuditSynologyImport.document_id == AuditDocument.id)
        .where(AuditSynologyImport.batch_id == batch.id)
    )
    for stored_filename in stored_filenames:
        if not finalize_pending_audit_document(stored_filename):
            raise HTTPException(
                status_code=500,
                detail="Файл импортирован в БД, но отсутствует в хранилище документов",
            )


def _disabled_reason(item: SynologyFileInfo, already_imported: bool) -> str | None:
    if item.is_dir:
        return None
    if item.extension not in {".pdf", ".docx", ".xlsx"}:
        return "Поддерживаются только PDF, DOCX и XLSX"
    if item.size_bytes <= 0:
        return "Пустой файл нельзя импортировать"
    if item.size_bytes > MAX_SYNOLOGY_FILE_BYTES:
        return "Файл больше 25 МБ"
    if item.modified_at <= 0:
        return "Synology не вернул дату изменения файла"
    if already_imported:
        return "Эта версия файла уже импортирована"
    return None


async def _verify_and_save_connection(
    body: AuditSynologySaveRequest,
    *,
    admin: User,
    db: AsyncSession,
    connection: AuditSynologyConnection | None,
) -> AuditSynologyConnectRead:
    admin_id = admin.id
    snapshot = None
    if connection is not None:
        if body.expected_config_version is None:
            raise HTTPException(status_code=422, detail="Укажите версию редактируемого профиля")
        if connection.config_version != body.expected_config_version:
            raise _profile_changed_error()
        snapshot = {
            "id": connection.id,
            "display_name": connection.display_name,
            "base_url": connection.base_url,
            "account_name": connection.account_name,
            "password_ciphertext": connection.password_ciphertext,
            "root_path": connection.root_path,
            "enabled": connection.enabled,
            "config_version": connection.config_version,
        }
    elif body.expected_config_version is not None:
        raise HTTPException(status_code=422, detail="Для нового профиля версия не указывается")

    raw_url = body.base_url.strip()
    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"
    try:
        base_url = normalize_synology_base_url(raw_url)
        root_path = normalize_root_path(body.root_path)
        if not connector_secret_configured():
            raise SynologyConnectorError(
                "encryption_key_not_configured",
                "На сервере DPMS не настроен отдельный ключ коннекторов",
                503,
            )
    except SynologyConnectorError as error:
        raise _http_error(error)
    account_name = body.account_name.strip()
    if not account_name:
        raise HTTPException(status_code=422, detail="Укажите имя пользователя Synology")
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Укажите название профиля Synology")

    profile_id = snapshot["id"] if snapshot is not None else uuid4()
    supplied_password = body.password.get_secret_value() if body.password else None
    try:
        password = supplied_password if supplied_password is not None else decrypt_synology_password(
            snapshot["password_ciphertext"] if snapshot else None,
            profile_id,
        )
        password_ciphertext = (
            encrypt_synology_password(supplied_password, profile_id)
            if supplied_password is not None
            else snapshot["password_ciphertext"] if snapshot else None
        )
    except SynologyConnectorError as error:
        raise _http_error(error)
    profile_changed = snapshot is None or (
        snapshot["display_name"] != display_name
        or snapshot["base_url"] != base_url
        or snapshot["account_name"] != account_name
        or snapshot["root_path"] != root_path
        or not snapshot["enabled"]
        or supplied_password is not None
    )
    await db.rollback()
    otp_code = body.otp_code.get_secret_value() if body.otp_code else None
    client = SynologyFileStationClient(
        base_url=base_url,
        account_name=account_name,
        password=password,
        root_path=root_path,
    )
    password = ""
    supplied_password = None
    protocol_diagnostics: dict[str, Any] | None = None
    try:
        await client.connect(otp_code=otp_code)
        otp_code = None
        await client.list_folder(root_path, limit=1)
        protocol_diagnostics = client.diagnostic_summary()
    except SynologyConnectorError as error:
        otp_code = None
        protocol_diagnostics = client.diagnostic_summary()
        await client.close()
        async with synology_profile_mutation_lock:
            event_connection_id = None
            if snapshot is not None:
                locked_connection = await db.scalar(
                    select(AuditSynologyConnection)
                    .where(AuditSynologyConnection.id == profile_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                if locked_connection is not None:
                    event_connection_id = locked_connection.id
                    if locked_connection.config_version == snapshot["config_version"]:
                        locked_connection.last_tested_at = datetime.now(timezone.utc)
                        locked_connection.last_test_status = "error"
                        locked_connection.last_error_code = error.code[:80]
            _record_connector_event(
                db,
                connection_id=event_connection_id,
                actor_id=admin_id,
                event_type="verify",
                outcome="error",
                error_code=error.code,
                payload={"profile_changed": profile_changed, "protocol": protocol_diagnostics},
            )
            await db.commit()
        raise _http_error(error)

    active = None
    async with synology_profile_mutation_lock:
        try:
            if snapshot is None:
                saved_connection = AuditSynologyConnection(
                    id=profile_id,
                    provider="synology",
                    display_name=display_name,
                    base_url=base_url,
                    account_name=account_name,
                    password_ciphertext=password_ciphertext,
                    root_path=root_path,
                    enabled=True,
                    is_active=False,
                    config_version=1,
                    created_by_id=admin_id,
                    updated_by_id=admin_id,
                )
                db.add(saved_connection)
            else:
                saved_connection = await db.scalar(
                    select(AuditSynologyConnection)
                    .where(AuditSynologyConnection.id == profile_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                if (
                    saved_connection is None
                    or saved_connection.config_version != snapshot["config_version"]
                ):
                    raise _profile_changed_error("Профиль Synology изменился; повторите проверку")
                saved_connection.display_name = display_name
                saved_connection.base_url = base_url
                saved_connection.account_name = account_name
                saved_connection.password_ciphertext = password_ciphertext
                saved_connection.root_path = root_path
                saved_connection.enabled = True
                saved_connection.updated_by_id = admin_id
                if profile_changed:
                    saved_connection.config_version += 1
            saved_connection.last_tested_at = datetime.now(timezone.utc)
            saved_connection.last_test_status = "ok"
            saved_connection.last_error_code = None
            await db.flush()
            _record_connector_event(
                db,
                connection_id=saved_connection.id,
                actor_id=admin_id,
                event_type="verify",
                outcome="success",
                payload={"protocol": protocol_diagnostics},
            )
            active = await synology_session_store.create(
                user_id=admin_id,
                connection_id=saved_connection.id,
                config_version=saved_connection.config_version,
                client=client,
                replace_user_sessions=False,
            )
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if active is not None:
                await synology_session_store.remove(active.token, user_id=admin_id)
            else:
                await client.close()
            raise HTTPException(status_code=409, detail="Профиль Synology с таким названием уже существует")
        except Exception:
            await db.rollback()
            if active is not None:
                await synology_session_store.remove(active.token, user_id=admin_id)
            else:
                await client.close()
            raise
        await db.refresh(saved_connection)
        await synology_session_store.revoke_profile(saved_connection.id, except_token=active.token)
    return AuditSynologyConnectRead(
        session_token=active.token,
        expires_at=active.expires_at,
        connection=_connection_read(saved_connection),
    )


@router.get("/connections", response_model=AuditSynologyConnectionListRead)
async def list_synology_connections(
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connections = list(
        await db.scalars(
            select(AuditSynologyConnection)
            .where(AuditSynologyConnection.provider == "synology")
            .order_by(
                AuditSynologyConnection.is_active.desc(),
                AuditSynologyConnection.display_name.asc(),
            )
        )
    )
    return AuditSynologyConnectionListRead(
        items=[_connection_read(connection) for connection in connections],
        allowed_origins_configured=synology_allowlist_configured(),
        encryption_key_configured=connector_secret_configured(),
    )


@router.get("/config", response_model=AuditSynologyConnectionRead)
async def get_active_synology_config(
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _active_connection_or_none(db)
    if connection is None:
        return AuditSynologyConnectionRead(
            configured=False,
            allowed_origins_configured=synology_allowlist_configured(),
            encryption_key_configured=connector_secret_configured(),
        )
    return _connection_read(connection)


@router.post("/connections", response_model=AuditSynologyConnectRead, status_code=status.HTTP_201_CREATED)
async def create_synology_connection(
    body: AuditSynologySaveRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if body.password is None:
        raise HTTPException(status_code=422, detail="Для нового профиля укажите пароль Synology")
    return await _verify_and_save_connection(body, admin=admin, db=db, connection=None)


@router.put("/connections/{connection_id}", response_model=AuditSynologyConnectRead)
async def update_synology_connection(
    connection_id: UUID,
    body: AuditSynologySaveRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _connection(db, connection_id)
    return await _verify_and_save_connection(body, admin=admin, db=db, connection=connection)


@router.post("/connections/{connection_id}/activate", response_model=AuditSynologyConnectRead)
async def activate_synology_connection(
    connection_id: UUID,
    body: AuditSynologyActivateRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _connection(db, connection_id)
    if not connection.enabled:
        raise HTTPException(status_code=409, detail="Профиль Synology отключен")
    if connection.config_version != body.expected_config_version:
        raise _profile_changed_error()
    admin_id = admin.id
    expected_version = body.expected_config_version
    snapshot = {
        "base_url": connection.base_url,
        "account_name": connection.account_name,
        "password_ciphertext": connection.password_ciphertext,
        "root_path": connection.root_path,
    }
    await db.rollback()
    active_session = None
    client: SynologyFileStationClient | None = None
    protocol_diagnostics: dict[str, Any] | None = None
    if body.session_token:
        try:
            active_session = await synology_session_store.get(
                body.session_token,
                user_id=admin_id,
                connection_id=connection_id,
                config_version=expected_version,
            )
        except SynologyConnectorError:
            active_session = None
    if active_session is None:
        try:
            password = decrypt_synology_password(snapshot["password_ciphertext"], connection_id)
            otp_code = body.otp_code.get_secret_value() if body.otp_code else None
            client = SynologyFileStationClient(
                base_url=snapshot["base_url"],
                account_name=snapshot["account_name"],
                password=password,
                root_path=snapshot["root_path"],
            )
            password = ""
            await client.connect(otp_code=otp_code)
            otp_code = None
            await client.list_folder(snapshot["root_path"], limit=1)
            protocol_diagnostics = client.diagnostic_summary()
        except SynologyConnectorError as error:
            if client is not None:
                protocol_diagnostics = client.diagnostic_summary()
            if client is not None:
                await client.close()
            async with synology_profile_mutation_lock:
                locked_connection = await db.scalar(
                    select(AuditSynologyConnection)
                    .where(AuditSynologyConnection.id == connection_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                if locked_connection is not None and locked_connection.config_version == expected_version:
                    locked_connection.last_tested_at = datetime.now(timezone.utc)
                    locked_connection.last_test_status = "error"
                    locked_connection.last_error_code = error.code[:80]
                _record_connector_event(
                    db,
                    connection_id=locked_connection.id if locked_connection else None,
                    actor_id=admin_id,
                    event_type="activate",
                    outcome="error",
                    error_code=error.code,
                    payload={"protocol": protocol_diagnostics},
                )
                await db.commit()
            raise _http_error(error)

    session_created = False
    session_rebound = False
    async with synology_profile_mutation_lock:
        try:
            locked_profiles = list(
                await db.scalars(
                    select(AuditSynologyConnection)
                    .where(AuditSynologyConnection.provider == "synology")
                    .order_by(AuditSynologyConnection.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            )
            locked_connection = next((item for item in locked_profiles if item.id == connection_id), None)
            if locked_connection is None or locked_connection.config_version != expected_version:
                raise _profile_changed_error("Профиль Synology изменился; повторите активацию")
            if active_session is not None:
                active_session = await synology_session_store.get(
                    active_session.token,
                    user_id=admin_id,
                    connection_id=connection_id,
                    config_version=expected_version,
                )
            previously_active_ids = [
                profile.id for profile in locked_profiles if profile.is_active and profile.id != connection_id
            ]
            for profile in locked_profiles:
                next_active = profile.id == connection_id
                if profile.is_active != next_active:
                    profile.is_active = next_active
                    profile.config_version += 1
            locked_connection.last_tested_at = datetime.now(timezone.utc)
            locked_connection.last_test_status = "ok"
            locked_connection.last_error_code = None
            locked_connection.updated_by_id = admin_id
            _record_connector_event(
                db,
                connection_id=locked_connection.id,
                actor_id=admin_id,
                event_type="activate",
                outcome="success",
                payload={"protocol": protocol_diagnostics} if protocol_diagnostics else None,
            )
            if active_session is None:
                active_session = await synology_session_store.create(
                    user_id=admin_id,
                    connection_id=locked_connection.id,
                    config_version=locked_connection.config_version,
                    client=client,
                    replace_user_sessions=False,
                )
                session_created = True
                client = None
            elif locked_connection.config_version != expected_version:
                active_session = await synology_session_store.rebind(
                    active_session.token,
                    user_id=admin_id,
                    connection_id=connection_id,
                    from_config_version=expected_version,
                    to_config_version=locked_connection.config_version,
                )
                session_rebound = True
            await db.commit()
        except Exception:
            await db.rollback()
            if session_created and active_session is not None:
                await synology_session_store.remove(active_session.token, user_id=admin_id)
            elif session_rebound and active_session is not None:
                try:
                    await synology_session_store.rebind(
                        active_session.token,
                        user_id=admin_id,
                        connection_id=connection_id,
                        from_config_version=active_session.config_version,
                        to_config_version=expected_version,
                    )
                except SynologyConnectorError:
                    await synology_session_store.remove(active_session.token, user_id=admin_id)
            if client is not None:
                await client.close()
            raise
        await db.refresh(locked_connection)
        for previous_id in previously_active_ids:
            await synology_session_store.revoke_profile(previous_id)
        await synology_session_store.revoke_profile(
            locked_connection.id,
            except_token=active_session.token,
        )
    return AuditSynologyConnectRead(
        session_token=active_session.token,
        expires_at=active_session.expires_at,
        connection=_connection_read(locked_connection),
    )


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_synology(
    body: AuditSynologyDisconnectRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _active_connection_or_none(db)
    removed = await synology_session_store.remove(body.session_token, user_id=admin.id)
    _record_connector_event(
        db,
        connection_id=connection.id if connection else None,
        actor_id=admin.id,
        event_type="disconnect",
        outcome="success",
        payload={"active_session_closed": removed},
    )
    await db.commit()
    return None


@router.post("/files/list", response_model=AuditSynologyBrowserRead)
async def list_synology_files(
    body: AuditSynologyBrowseRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _active_connection(db)
    active = await _session(body.session_token, admin, connection)
    try:
        target_path = (
            verify_path_token(
                body.folder_token,
                connection_id=connection.id,
                config_version=connection.config_version,
                user_id=admin.id,
            )
            if body.folder_token
            else connection.root_path
        )
        target_path = ensure_path_within_root(target_path, connection.root_path)
        async with active.lock:
            page = await active.client.list_folder(target_path, offset=body.offset, limit=body.limit)
    except SynologyConnectorError as error:
        raise _http_error(error)
    existing = await _existing_remote_versions(db, connection, page.items)
    items: list[AuditSynologyFileRead] = []
    for item in page.items:
        key = (
            remote_path_fingerprint(connection.base_url, item.path),
            item.size_bytes,
            item.modified_at,
        )
        already_imported = key in existing
        reason = _disabled_reason(item, already_imported)
        items.append(
            AuditSynologyFileRead(
                item_id=remote_path_fingerprint(connection.base_url, item.path),
                path_token=build_path_token(
                    connection_id=connection.id,
                    config_version=connection.config_version,
                    user_id=admin.id,
                    path=item.path,
                ),
                name=item.name,
                is_dir=item.is_dir,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
                extension=item.extension,
                selectable=item.selectable and reason is None,
                already_imported=already_imported,
                disabled_reason=reason,
            )
        )
    parent_token = None
    if page.path != connection.root_path:
        candidate = str(PurePosixPath(page.path).parent)
        parent_path = ensure_path_within_root(candidate, connection.root_path)
        parent_token = build_path_token(
            connection_id=connection.id,
            config_version=connection.config_version,
            user_id=admin.id,
            path=parent_path,
        )
    root_name = "Общие папки" if connection.root_path == "/" else PurePosixPath(connection.root_path).name
    current_name = root_name if page.path == connection.root_path else PurePosixPath(page.path).name
    return AuditSynologyBrowserRead(
        current_folder_name=current_name,
        root_folder_name=root_name,
        parent_token=parent_token,
        offset=page.offset,
        total=page.total,
        items=items,
    )


def _validate_selection(files: list[SynologyFileInfo]) -> int:
    if not files or len(files) > MAX_SYNOLOGY_FILES_PER_IMPORT:
        raise HTTPException(status_code=400, detail="Выберите от 1 до 20 документов")
    for item in files:
        reason = _disabled_reason(item, False)
        if item.is_dir or reason:
            raise HTTPException(
                status_code=400,
                detail=f"Файл «{item.name}» нельзя импортировать: {reason or 'выбрана папка'}",
            )
    total_size = sum(item.size_bytes for item in files)
    if total_size > MAX_SYNOLOGY_BATCH_BYTES:
        raise HTTPException(status_code=400, detail="Общий размер выбранных файлов превышает 100 МБ")
    return total_size


def _decode_file_tokens(
    tokens: list[str],
    *,
    connection: AuditSynologyConnection,
    admin: User,
) -> list[str]:
    return [
        ensure_path_within_root(
            verify_path_token(
                token,
                connection_id=connection.id,
                config_version=connection.config_version,
                user_id=admin.id,
            ),
            connection.root_path,
        )
        for token in tokens
    ]


@router.post("/imports/preview", response_model=AuditSynologyPreviewRead)
async def preview_synology_import(
    body: AuditSynologySelectionRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _active_connection(db)
    active = await _session(body.session_token, admin, connection)
    try:
        paths = _decode_file_tokens(body.file_tokens, connection=connection, admin=admin)
        if len(set(paths)) != len(paths):
            raise SynologyConnectorError("duplicate_selection", "Один файл выбран несколько раз", 422)
        async with active.lock:
            files = await active.client.get_files(paths)
    except SynologyConnectorError as error:
        raise _http_error(error)
    total_size = _validate_selection(files)
    existing = await _existing_remote_versions(db, connection, files)
    if existing:
        raise HTTPException(status_code=409, detail="Одна из выбранных версий уже импортирована")
    token = build_preview_token(
        connection_id=connection.id,
        config_version=connection.config_version,
        user_id=admin.id,
        files=files,
    )
    return AuditSynologyPreviewRead(
        preview_token=token,
        expires_in_seconds=SYNOLOGY_PREVIEW_TTL_SECONDS,
        file_count=len(files),
        total_size_bytes=total_size,
        items=[
            AuditSynologyPreviewItem(
                file_token=build_path_token(
                    connection_id=connection.id,
                    config_version=connection.config_version,
                    user_id=admin.id,
                    path=item.path,
                ),
                name=item.name,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
                extension=item.extension,
            )
            for item in files
        ],
    )


def _token_file_map(payload: dict) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for raw in payload.get("files", []):
        if not isinstance(raw, dict):
            raise SynologyConnectorError("invalid_preview", "Предварительная проверка повреждена", 409)
        try:
            path = normalize_remote_path(str(raw["path"]))
            size_bytes = int(raw["size_bytes"])
            modified_at = int(raw["modified_at"])
        except (KeyError, TypeError, ValueError, SynologyConnectorError):
            raise SynologyConnectorError("invalid_preview", "Предварительная проверка повреждена", 409)
        result[path] = (size_bytes, modified_at)
    return result


@router.post("/imports/commit", response_model=AuditSynologyImportRead, status_code=status.HTTP_201_CREATED)
async def commit_synology_import(
    body: AuditSynologyCommitRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    connection = await _active_connection(db)
    request_key = connector_request_hash(
        "synology-import-idempotency",
        str(connection.id),
        str(admin.id),
        str(body.request_id),
    )
    submitted_selection = connector_request_hash(
        "synology-import-selection",
        body.preview_token,
        *(sorted(body.file_tokens)),
        (body.digital_product or "").strip(),
    )
    previous = await db.scalar(
        select(AuditSynologyImportBatch).where(AuditSynologyImportBatch.request_key_hash == request_key)
    )
    if previous is not None:
        if previous.selection_hash != submitted_selection:
            raise HTTPException(status_code=409, detail="Этот идентификатор запроса уже использован для другого набора файлов")
        await _finalize_committed_batch_files(db, previous)
        return AuditSynologyImportRead.model_validate(previous.response_json)

    active = await _session(body.session_token, admin, connection)
    try:
        payload = verify_preview_token(body.preview_token, user_id=admin.id)
        paths = _decode_file_tokens(body.file_tokens, connection=connection, admin=admin)
        token_files = _token_file_map(payload)
    except SynologyConnectorError as error:
        raise _http_error(error)
    if payload.get("connection_id") != str(connection.id) or payload.get("config_version") != connection.config_version:
        raise HTTPException(status_code=409, detail="Настройки Synology изменились; проверьте выбор еще раз")
    if set(paths) != set(token_files) or len(paths) != len(token_files):
        raise HTTPException(status_code=409, detail="Набор файлов отличается от предварительной проверки")

    prepared_items = []
    try:
        async with active.lock:
            files = await active.client.get_files(paths)
            _validate_selection(files)
            for item in files:
                if token_files.get(item.path) != (item.size_bytes, item.modified_at):
                    raise HTTPException(status_code=409, detail=f"Файл «{item.name}» изменился; повторите проверку")
                data = await active.client.download_file(item.path)
                if len(data) != item.size_bytes:
                    raise HTTPException(status_code=409, detail=f"Файл «{item.name}» изменился во время скачивания")
                prepared_items.append((item, prepare_audit_document_bytes(item.name, data)))
    except SynologyConnectorError as error:
        raise _http_error(error)

    if sum(prepared.size_bytes for _, prepared in prepared_items) > MAX_SYNOLOGY_BATCH_BYTES:
        raise HTTPException(status_code=400, detail="Общий размер загруженных файлов превышает 100 МБ")
    hashes = [prepared.sha256 for _, prepared in prepared_items]
    if len(set(hashes)) != len(hashes):
        raise HTTPException(status_code=409, detail="Среди выбранных документов есть одинаковые файлы")
    existing_hash = await db.scalar(select(AuditDocument.sha256).where(AuditDocument.sha256.in_(hashes)).limit(1))
    if existing_hash is not None:
        raise HTTPException(status_code=409, detail="Один из документов уже загружен в аудит")
    existing_remote = await _existing_remote_versions(db, connection, [item for item, _ in prepared_items])
    if existing_remote:
        raise HTTPException(status_code=409, detail="Одна из выбранных версий уже импортирована")

    product = (body.digital_product or "").strip() or "Требует заполнения"
    staged_documents: list[StagedAuditDocument] = []
    response_items: list[AuditSynologyImportItemRead] = []
    batch = AuditSynologyImportBatch(
        connection_id=connection.id,
        request_key_hash=request_key,
        selection_hash=submitted_selection,
        status="committed",
        response_json={},
        imported_by_id=admin.id,
    )
    db.add(batch)
    commit_started = False
    try:
        await db.flush()
        for item, prepared in prepared_items:
            stem = PurePosixPath(item.name).stem.strip()[:220] or "Документ Synology"
            audit_case = AuditCase(
                created_by_id=admin.id,
                title=f"Аудит: {stem}",
                digital_product=product,
                status="draft",
                notes="Исходный документ импортирован администратором из Synology.",
            )
            db.add(audit_case)
            await db.flush()
            staged = stage_audit_document_file(audit_case.id, prepared)
            staged_documents.append(staged)
            document = AuditDocument(
                case_id=audit_case.id,
                uploaded_by_id=admin.id,
                kind="technical_spec",
                display_name="Техническое задание",
                original_filename=prepared.original_filename,
                stored_filename=staged.stored_filename,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
            )
            db.add(document)
            await db.flush()
            db.add(
                AuditSynologyImport(
                    connection_id=connection.id,
                    batch_id=batch.id,
                    case_id=audit_case.id,
                    document_id=document.id,
                    remote_path_fingerprint=remote_path_fingerprint(connection.base_url, item.path),
                    remote_size=item.size_bytes,
                    remote_mtime=item.modified_at,
                    content_sha256=prepared.sha256,
                    imported_by_id=admin.id,
                )
            )
            record_audit_event(
                db,
                case_id=audit_case.id,
                actor_id=admin.id,
                event_type="synology_document_imported",
                message="Техническое задание импортировано из Synology",
                payload_json={
                    "document_id": str(document.id),
                    "document_kind": document.kind,
                    "sha256": document.sha256,
                },
            )
            response_items.append(
                AuditSynologyImportItemRead(
                    case_id=audit_case.id,
                    case_number=audit_case.case_number,
                    document_id=document.id,
                    file_name=prepared.original_filename,
                    size_bytes=prepared.size_bytes,
                )
            )
        response = AuditSynologyImportRead(
            imported_count=len(response_items),
            total_size_bytes=sum(item.size_bytes for item in response_items),
            items=response_items,
        )
        batch.response_json = response.model_dump(mode="json")
        _record_connector_event(
            db,
            connection_id=connection.id,
            actor_id=admin.id,
            event_type="import",
            outcome="success",
            item_count=len(response_items),
            payload={"total_size_bytes": response.total_size_bytes},
        )
        commit_started = True
        await db.commit()
        for staged in staged_documents:
            finalize_staged_audit_document(staged)
    except IntegrityError:
        await db.rollback()
        for staged in staged_documents:
            discard_staged_audit_document(staged)
        previous = await db.scalar(
            select(AuditSynologyImportBatch).where(AuditSynologyImportBatch.request_key_hash == request_key)
        )
        if previous is not None and previous.selection_hash == submitted_selection:
            await _finalize_committed_batch_files(db, previous)
            return AuditSynologyImportRead.model_validate(previous.response_json)
        raise HTTPException(status_code=409, detail="Файл уже импортирован другим запросом")
    except Exception:
        await db.rollback()
        if not commit_started:
            for staged in staged_documents:
                discard_staged_audit_document(staged)
        raise
    return response
