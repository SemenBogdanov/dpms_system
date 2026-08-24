"""Queue, process isolation, and safe summaries for canonical audit-tz preflight."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ai_provider import AIProviderConfig, AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import (
    AuditAIAtomDraft,
    AuditAIAtomizationAttempt,
    AuditAIModelRegistry,
    AuditAIModelRegistryItem,
    AuditAtom,
    AuditCase,
    AuditDocument,
    AuditEvent,
)
from app.models.audit_runtime import AuditTZArtifact, AuditTZRun, AuditTZRuntimeJob
from app.services.ai_provider import AIProviderError
from app.services.audit_documents import audit_document_path
from app.services.audit_runtime_crypto import AuditRuntimeCryptoError, decrypt_identifiers
from app.services.audit_skill_package import extract_trusted_skill_archive
from app.services.audit_tz_atomization import (
    CanonicalAtomizationError,
    assemble_atomization_result,
    build_source_batches,
    generate_batch_result,
    restore_batch_result,
)


MAX_CLI_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_CANONICAL_PACKET_BYTES = 16 * 1024 * 1024
CONTRACT_KEY = "contract"
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHILD_LAUNCHER = Path(__file__).resolve().parents[1] / "workers" / "audit_tz_child.py"


class AuditTZRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ClaimedRuntimeJob:
    id: UUID
    lease_token: str
    kind: str


@dataclass(frozen=True)
class CLIResult:
    exit_code: int
    payload: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _runtime_root() -> Path:
    root = Path(settings.AUDIT_TZ_RUNTIME_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    return root


async def reconcile_orphan_audit_tz_run_files(db: AsyncSession) -> int:
    """Worker-side cleanup for run directories whose database rows were deleted."""

    existing_run_ids = set(await db.scalars(select(AuditTZRun.id)))
    removed = 0
    root = _runtime_root()
    for scope in ("inputs", "runs"):
        scope_root = root / scope
        if not scope_root.is_dir():
            continue
        for candidate in scope_root.iterdir():
            try:
                run_id = UUID(candidate.name)
            except ValueError:
                continue
            if run_id in existing_run_ids:
                continue
            if candidate.is_symlink():
                candidate.unlink(missing_ok=True)
                removed += 1
                continue
            path = _within_runtime(candidate)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
    return removed


def _resolve_without_symlinks(path: Path, root: Path, *, code: str, message: str) -> Path:
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise AuditTZRuntimeError(code, message)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AuditTZRuntimeError(code, message)
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise AuditTZRuntimeError(code, message)
    return resolved


def _within_runtime(path: Path) -> Path:
    return _resolve_without_symlinks(
        path,
        _runtime_root(),
        code="runtime_path_invalid",
        message="Runtime сформировал небезопасный путь",
    )


def _safe_code(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    candidate = value.split(":", 1)[0].strip()
    return candidate if _SAFE_CODE_RE.fullmatch(candidate) else fallback


def document_binding_id(source_sha256: str) -> str:
    """Build the skill's internal key from the selected immutable document."""

    normalized = source_sha256.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise AuditTZRuntimeError("document_hash_invalid", "Контрольная сумма документа повреждена")
    return f"DPMS-DOC-1-{normalized[:32].upper()}-{normalized[32:].upper()}"


def document_binding_digest(source_sha256: str) -> str:
    binding_id = document_binding_id(source_sha256)
    return sha256(f"dpms:audit-tz:document-binding:v1:{binding_id}".encode("ascii")).hexdigest()


def _read_json_file(path: Path, *, max_bytes: int = MAX_CLI_OUTPUT_BYTES) -> dict:
    path = _within_runtime(path)
    try:
        info = path.lstat()
        if not path.is_file() or path.is_symlink() or info.st_size <= 0 or info.st_size > max_bytes:
            raise OSError
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise AuditTZRuntimeError("runtime_artifact_invalid", "Runtime вернул поврежденный артефакт")
    if not isinstance(payload, dict):
        raise AuditTZRuntimeError("runtime_artifact_invalid", "Runtime вернул поврежденный артефакт")
    return payload


def _file_sha256(path: Path) -> str:
    path = _within_runtime(path)
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(128 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    path = _within_runtime(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = _within_runtime(path.parent / f".{path.name}.{uuid4()}.part")
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_CANONICAL_PACKET_BYTES:
        raise AuditTZRuntimeError("runtime_artifact_too_large", "Пакет атомов превышает безопасный размер")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _skill_directory(version: AuditAtomizationSkillVersion) -> Path:
    if version.package_format != "trusted_skill_archive" or version.package_blob is None:
        raise AuditTZRuntimeError("trusted_skill_required", "Выбранная версия не является доверенным skill")
    root = _runtime_root()
    skills_root = root / "skills"
    skills_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = _within_runtime(skills_root / version.content_sha256)
    try:
        return extract_trusted_skill_archive(
            bytes(version.package_blob),
            destination,
            expected_sha256=version.content_sha256,
        )
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, str) else "Проверка архива skill не пройдена"
        raise AuditTZRuntimeError("skill_integrity_failed", detail)


async def _run_cli(
    skill_root: Path,
    command: str,
    args: list[str],
    *,
    allowed_exit_codes: set[int],
) -> CLIResult:
    runtime_root = _runtime_root()
    # Command arguments only cross this short-lived request file. Keep it on
    # the worker's tmpfs, outside the persistent runtime volume.
    request_dir = Path(tempfile.mkdtemp(prefix="dpms-audit-tz-", dir="/tmp"))
    request_path = request_dir / f"{uuid4()}.json"
    request_payload = json.dumps(
        {"command": command, "args": args},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    open_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    descriptor = os.open(request_path, open_flags, 0o400)
    try:
        with os.fdopen(descriptor, "wb") as request_file:
            request_file.write(request_payload)
            request_file.flush()
            os.fsync(request_file.fileno())
    except BaseException:
        request_path.unlink(missing_ok=True)
        raise
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            str(_CHILD_LAUNCHER),
            "--skill-root",
            str(skill_root),
            "--request",
            str(request_path),
            cwd=str(runtime_root),
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(10, settings.AUDIT_TZ_CLI_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise AuditTZRuntimeError("runtime_timeout", "Runtime не завершил проверку вовремя", retryable=True)
    finally:
        request_path.unlink(missing_ok=True)
        shutil.rmtree(request_dir, ignore_errors=True)
    if len(stdout) > MAX_CLI_OUTPUT_BYTES:
        raise AuditTZRuntimeError("runtime_output_too_large", "Ответ runtime превышает безопасный размер")
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise AuditTZRuntimeError("runtime_protocol_error", "Runtime вернул некорректный ответ")
    if not isinstance(payload, dict):
        raise AuditTZRuntimeError("runtime_protocol_error", "Runtime вернул некорректный ответ")
    if process.returncode not in allowed_exit_codes:
        raise AuditTZRuntimeError(
            _safe_code(payload.get("error"), "runtime_execution_failed"),
            "Runtime не смог выполнить проверку",
        )
    return CLIResult(exit_code=int(process.returncode or 0), payload=payload)


async def ensure_pending_selftest_jobs(db: AsyncSession) -> int:
    versions = list(
        (
            await db.scalars(
                select(AuditAtomizationSkillVersion).where(
                    AuditAtomizationSkillVersion.package_format == "trusted_skill_archive",
                    AuditAtomizationSkillVersion.runtime_status == "pending_worker",
                )
            )
        ).all()
    )
    if not versions:
        return 0
    existing = set(
        await db.scalars(
            select(AuditTZRuntimeJob.skill_version_id).where(
                AuditTZRuntimeJob.kind == "skill_selftest",
                AuditTZRuntimeJob.skill_version_id.in_([item.id for item in versions]),
            )
        )
    )
    created = 0
    for version in versions:
        if version.id in existing:
            continue
        db.add(
            AuditTZRuntimeJob(
                kind="skill_selftest",
                skill_version_id=version.id,
                status="queued",
                max_attempts=2,
            )
        )
        created += 1
    return created


async def _recover_stale_jobs(db: AsyncSession, now: datetime) -> None:
    stale = list(
        (
            await db.scalars(
                select(AuditTZRuntimeJob)
                .where(
                    AuditTZRuntimeJob.status == "running",
                    AuditTZRuntimeJob.lease_expires_at.is_not(None),
                    AuditTZRuntimeJob.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for job in stale:
        job.lease_token = None
        job.lease_expires_at = None
        job.worker_id = None
        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.error_code = "worker_lease_expired"
            job.finished_at = now
            if job.kind == "skill_selftest" and job.skill_version_id is not None:
                version = await db.get(AuditAtomizationSkillVersion, job.skill_version_id)
                if version is not None:
                    version.runtime_status = "runtime_failed"
                    version.runtime_checked_at = now
                    version.runtime_error_code = job.error_code
                    version.runtime_selftest_json = {}
            elif job.run_id is not None:
                run = await db.get(AuditTZRun, job.run_id)
                if run is not None and run.status in {
                    "queued",
                    "running",
                    "atomization_queued",
                    "atomizing",
                }:
                    run.status = "failed"
                    run.current_phase = (
                        "atomization_failed" if job.kind == "atomization" else "failed"
                    )
                    run.error_code = job.error_code
                    run.finished_at = now
                    run.identifier_ciphertext = None
                    run.identifiers_purged_at = now
                    if job.kind == "atomization":
                        attempt = await db.scalar(
                            select(AuditAIAtomizationAttempt).where(
                                AuditAIAtomizationAttempt.canonical_run_id == run.id
                            )
                        )
                        if attempt is not None and attempt.status == "running":
                            attempt.status = "failed"
                            attempt.error_code = job.error_code[:80]
                            attempt.config_version += 1
        else:
            job.status = "queued"
            job.available_at = now
            if job.run_id is not None:
                run = await db.get(AuditTZRun, job.run_id)
                if run is not None and run.status in {"running", "atomizing"}:
                    if job.kind == "atomization":
                        run.status = "atomization_queued"
                        run.current_phase = "atomization_queued"
                    else:
                        run.status = "queued"
                        run.current_phase = "queued"


async def claim_runtime_job(db: AsyncSession, worker_id: str) -> ClaimedRuntimeJob | None:
    now = _now()
    await ensure_pending_selftest_jobs(db)
    await _recover_stale_jobs(db, now)
    job = await db.scalar(
        select(AuditTZRuntimeJob)
        .where(
            AuditTZRuntimeJob.status == "queued",
            AuditTZRuntimeJob.available_at <= now,
        )
        .order_by(AuditTZRuntimeJob.created_at.asc(), AuditTZRuntimeJob.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    lease_token = str(uuid4())
    job.status = "running"
    job.attempt_count += 1
    job.lease_token = lease_token
    job.lease_expires_at = now + timedelta(seconds=max(30, settings.AUDIT_TZ_WORKER_LEASE_SECONDS))
    job.worker_id = worker_id[:80]
    job.started_at = job.started_at or now
    job.error_code = None
    if job.run_id is not None:
        run = await db.get(AuditTZRun, job.run_id)
        if run is not None:
            if job.kind == "atomization":
                run.status = "atomizing"
                run.current_phase = "atomizing"
            else:
                run.status = "running"
                run.current_phase = "preflight"
            run.started_at = run.started_at or now
            run.error_code = None
    await db.flush()
    return ClaimedRuntimeJob(id=job.id, lease_token=lease_token, kind=job.kind)


def worker_identity() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"[:80]


async def _complete_job(
    db: AsyncSession,
    job_id: UUID,
    lease_token: str,
    *,
    status: str,
    error_code: str | None = None,
) -> AuditTZRuntimeJob | None:
    job = await db.scalar(
        select(AuditTZRuntimeJob)
        .where(
            AuditTZRuntimeJob.id == job_id,
            AuditTZRuntimeJob.status == "running",
            AuditTZRuntimeJob.lease_token == lease_token,
        )
        .with_for_update()
    )
    if job is None:
        return None
    job.status = status
    job.error_code = error_code[:100] if error_code else None
    job.lease_token = None
    job.lease_expires_at = None
    job.worker_id = None
    job.finished_at = _now()
    return job


async def _renew_job_lease(db_factory, job_id: UUID, lease_token: str) -> None:
    async with db_factory() as db:
        job = await db.scalar(
            select(AuditTZRuntimeJob)
            .where(
                AuditTZRuntimeJob.id == job_id,
                AuditTZRuntimeJob.status == "running",
                AuditTZRuntimeJob.lease_token == lease_token,
            )
            .with_for_update()
        )
        if job is None:
            raise AuditTZRuntimeError("worker_lease_lost", "Worker потерял право продолжать атомизацию")
        job.lease_expires_at = _now() + timedelta(
            seconds=max(30, settings.AUDIT_TZ_WORKER_LEASE_SECONDS)
        )
        await db.commit()


async def process_skill_selftest(job_id: UUID, lease_token: str, db_factory) -> None:
    async with db_factory() as db:
        job = await db.get(AuditTZRuntimeJob, job_id)
        version = await db.get(AuditAtomizationSkillVersion, job.skill_version_id) if job else None
        if job is None or version is None:
            raise AuditTZRuntimeError("runtime_job_missing", "Задание runtime не найдено")
        package_blob = bytes(version.package_blob or b"")
        version_snapshot = type(
            "SkillSnapshot",
            (),
            {
                "package_format": version.package_format,
                "package_blob": package_blob,
                "content_sha256": version.content_sha256,
            },
        )()
    try:
        skill_root = _skill_directory(version_snapshot)
        result = await _run_cli(skill_root, "selftest", [], allowed_exit_codes={0, 1})
        passed = bool(result.payload.get("passed")) and result.exit_code == 0
        summary = {
            "skill_version": str(result.payload.get("skill_version") or ""),
            "test_count": int(result.payload.get("test_count") or 0),
            "passed_count": int(result.payload.get("passed_count") or 0),
            "failed_count": int(result.payload.get("failed_count") or 0),
            "skipped_count": int(result.payload.get("skipped_count") or 0),
        }
        if not passed or summary["failed_count"]:
            raise AuditTZRuntimeError("skill_selftest_failed", "Встроенная проверка skill не пройдена")
    except AuditTZRuntimeError as error:
        async with db_factory() as db:
            job = await _complete_job(db, job_id, lease_token, status="failed", error_code=error.code)
            version = await db.get(AuditAtomizationSkillVersion, job.skill_version_id) if job else None
            if version is not None:
                version.runtime_status = "runtime_failed"
                version.runtime_checked_at = _now()
                version.runtime_error_code = error.code[:100]
                version.runtime_selftest_json = {}
            await db.commit()
        return
    async with db_factory() as db:
        job = await _complete_job(db, job_id, lease_token, status="succeeded")
        version = await db.get(AuditAtomizationSkillVersion, job.skill_version_id) if job else None
        if version is not None:
            version.runtime_status = "ready"
            version.runtime_checked_at = _now()
            version.runtime_error_code = None
            version.runtime_selftest_json = summary
        await db.commit()


def _copy_source(
    run_id: UUID,
    document: AuditDocument,
    *,
    binding_id: str | None = None,
) -> Path:
    upload_root = Path(settings.UPLOAD_DIR).expanduser().resolve()
    source = _resolve_without_symlinks(
        audit_document_path(document),
        upload_root,
        code="document_path_invalid",
        message="Путь документа вышел за пределы хранилища",
    )
    if not source.is_file() or Path(document.original_filename).suffix.lower() != ".docx":
        raise AuditTZRuntimeError("unsupported_document_type", "Canonical preflight поддерживает DOCX")
    if sha256(source.read_bytes()).hexdigest() != document.sha256:
        raise AuditTZRuntimeError("document_hash_changed", "Контрольная сумма документа изменилась")
    input_dir = _runtime_root() / "inputs" / str(run_id)
    input_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    safe_name = (
        f"{binding_id}.docx"
        if binding_id
        else (Path(document.original_filename).name[:255] or "source.docx")
    )
    destination = input_dir / safe_name
    if destination.exists():
        if destination.is_symlink() or not destination.is_file() or _file_sha256(destination) != document.sha256:
            raise AuditTZRuntimeError("runtime_source_changed", "Копия исходного документа изменилась")
        return destination
    temporary = input_dir / f".{uuid4()}.part"
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o400)
        if _file_sha256(temporary) != document.sha256:
            raise AuditTZRuntimeError("runtime_source_copy_failed", "Не удалось зафиксировать исходный документ")
        os.replace(temporary, destination)
        destination.chmod(0o400)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _safe_identity_summary(report: dict, preflight: dict) -> dict:
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "decision": "PASS" if report.get("decision") == "PASS" else "BLOCKED",
        "block_code": _safe_code(report.get("block_code"), "BLOCKED_PREFLIGHT")
        if report.get("decision") != "PASS"
        else None,
        "source_kind": str(source.get("kind") or "unknown")[:30],
        "source_unit_count": max(0, int(preflight.get("source_unit_count") or source.get("unit_count") or 0)),
        "external_relationship_count": max(0, int(source.get("external_relationship_count") or 0)),
        "formula_unit_count": max(0, int(source.get("formula_unit_count") or 0)),
        "hyperlink_unit_count": max(0, int(source.get("hyperlink_unit_count") or 0)),
        "warning_count": len(warnings),
        "comparison_eligible": bool(report.get("comparison_eligible")),
    }


async def _upsert_artifact(
    db: AsyncSession,
    run: AuditTZRun,
    *,
    kind: str,
    path: Path,
    safe_summary: dict,
    phase: str = "PREFLIGHT",
    visible_to_user: bool | None = None,
) -> None:
    root = _runtime_root()
    path = _within_runtime(path)
    relative = path.relative_to(root).as_posix()
    current = await db.scalar(
        select(AuditTZArtifact).where(
            AuditTZArtifact.run_id == run.id,
            AuditTZArtifact.kind == kind,
        )
    )
    values = {
        "phase": phase,
        "sha256": _file_sha256(path),
        "path_rel": relative,
        "safe_summary_json": safe_summary,
        "visible_to_user": kind == "identity_report" if visible_to_user is None else visible_to_user,
    }
    if current is None:
        db.add(AuditTZArtifact(run_id=run.id, kind=kind, **values))
    else:
        for field, value in values.items():
            setattr(current, field, value)


async def process_preflight(job_id: UUID, lease_token: str, db_factory) -> None:
    async with db_factory() as db:
        job = await db.get(AuditTZRuntimeJob, job_id)
        run = await db.get(AuditTZRun, job.run_id) if job and job.run_id else None
        document = await db.get(AuditDocument, run.document_id) if run else None
        version = await db.get(AuditAtomizationSkillVersion, run.skill_version_id) if run else None
        skill = await db.get(AuditAtomizationSkill, version.skill_id) if version else None
        audit_case = await db.get(AuditCase, run.case_id) if run else None
        if not all((job, run, document, version, skill, audit_case)):
            raise AuditTZRuntimeError("runtime_context_missing", "Контекст запуска runtime не найден")
        if (
            run.source_sha256 != document.sha256
            or run.skill_sha256 != version.content_sha256
            or version.runtime_status != "ready"
            or not version.is_active
            or not skill.is_enabled
            or document.case_id != run.case_id
        ):
            raise AuditTZRuntimeError("runtime_context_changed", "Документ или активный skill изменился")
        if run.source_binding == "document_hash":
            identifiers = [document_binding_id(document.sha256)]
        elif run.source_binding == "contract_identifier":
            try:
                identifiers = decrypt_identifiers(run.identifier_ciphertext)
            except AuditRuntimeCryptoError as error:
                raise AuditTZRuntimeError(error.code, error.message)
        else:
            raise AuditTZRuntimeError(
                "runtime_binding_invalid",
                "Способ привязки документа не поддерживается",
            )
        snapshots = (
            run.id,
            document,
            version,
            identifiers,
            run.source_binding,
            run.requested_by_id,
            run.case_id,
        )

    run_id, document, version, identifiers, source_binding, actor_id, case_id = snapshots
    try:
        skill_root = _skill_directory(version)
        source_path = _copy_source(
            run_id,
            document,
            binding_id=identifiers[0] if source_binding == "document_hash" else None,
        )
        run_dir = _runtime_root() / "runs" / str(run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            await _run_cli(
                skill_root,
                "init-run",
                ["--out", str(run_dir), "--batch-id", f"dpms-{run_id}"],
                allowed_exit_codes={0},
            )
        manifest = _read_json_file(manifest_path)
        contracts = manifest.get("contracts")
        if not isinstance(contracts, list):
            raise AuditTZRuntimeError("runtime_manifest_invalid", "Runtime manifest поврежден")
        if not contracts:
            add_args = [
                "--run",
                str(run_dir),
                "--contract-id",
                identifiers[0],
                "--source",
                str(source_path),
                "--mode",
                "audit-only",
                "--contract-key",
                CONTRACT_KEY,
            ]
            for alias in identifiers[1:]:
                add_args.extend(["--accepted-id", alias])
            await _run_cli(skill_root, "add-contract", add_args, allowed_exit_codes={0})
        elif len(contracts) != 1 or contracts[0].get("contract_key") != CONTRACT_KEY:
            raise AuditTZRuntimeError("runtime_manifest_conflict", "Runtime manifest не соответствует запуску")
        result = await _run_cli(
            skill_root,
            "preflight",
            ["--run", str(run_dir), "--contract", CONTRACT_KEY],
            allowed_exit_codes={0, 2},
        )
        rows = result.payload.get("results")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise AuditTZRuntimeError("runtime_protocol_error", "Runtime вернул некорректный preflight")
        preflight = rows[0]
        identity_path = run_dir / "contracts" / CONTRACT_KEY / "gate" / "identity_report.json"
        report = _read_json_file(identity_path)
        summary = _safe_identity_summary(report, preflight)
        summary["source_binding"] = (
            "document_hash" if source_binding == "document_hash" else "legacy_identifier"
        )
        passed = result.exit_code == 0 and summary["decision"] == "PASS"
    except AuditTZRuntimeError as error:
        async with db_factory() as db:
            job = await _complete_job(db, job_id, lease_token, status="failed", error_code=error.code)
            run = await db.get(AuditTZRun, job.run_id) if job and job.run_id else None
            if run is not None:
                run.status = "failed"
                run.current_phase = "failed"
                run.error_code = error.code[:100]
                run.finished_at = _now()
                run.identifier_ciphertext = None
                run.identifiers_purged_at = _now()
                db.add(
                    AuditEvent(
                        case_id=run.case_id,
                        actor_id=run.requested_by_id,
                        event_type="audit_tz_preflight_failed",
                        message="Подготовка документа завершилась технической ошибкой",
                        payload_json={"runtime_run_id": str(run.id), "error_code": error.code[:100]},
                    )
                )
            await db.commit()
        return

    async with db_factory() as db:
        job = await _complete_job(
            db,
            job_id,
            lease_token,
            status="succeeded" if passed else "blocked",
            error_code=None if passed else str(summary.get("block_code") or "BLOCKED_PREFLIGHT"),
        )
        run = await db.get(AuditTZRun, job.run_id) if job and job.run_id else None
        if run is None:
            await db.rollback()
            return
        run.status = "preflight_pass" if passed else "blocked"
        run.current_phase = "preflight_complete"
        run.source_unit_count = int(summary["source_unit_count"])
        run.warning_count = int(summary["warning_count"])
        run.safe_summary_json = summary
        run.error_code = None if passed else str(summary.get("block_code") or "BLOCKED_PREFLIGHT")[:100]
        run.finished_at = _now()
        run.identifier_ciphertext = None
        run.identifiers_purged_at = _now()
        await _upsert_artifact(db, run, kind="identity_report", path=identity_path, safe_summary=summary)
        if passed:
            bundle_path = run_dir / "contracts" / CONTRACT_KEY / "gate" / "gated_evidence_bundle.json"
            units_path = run_dir / "contracts" / CONTRACT_KEY / "source" / "source_units.json"
            await _upsert_artifact(
                db,
                run,
                kind="gated_evidence_bundle",
                path=bundle_path,
                safe_summary={"source_unit_count": run.source_unit_count},
            )
            await _upsert_artifact(
                db,
                run,
                kind="source_units",
                path=units_path,
                safe_summary={"source_unit_count": run.source_unit_count},
            )
        db.add(
            AuditEvent(
                case_id=run.case_id,
                actor_id=run.requested_by_id,
                event_type="audit_tz_preflight_pass" if passed else "audit_tz_preflight_blocked",
                message="Документ подготовлен" if passed else "Подготовка документа остановлена",
                payload_json={
                    "runtime_run_id": str(run.id),
                    "source_unit_count": run.source_unit_count,
                    "block_code": run.error_code,
                },
            )
        )
        await db.commit()


async def _generate_batch_with_retry(provider, batch, total_batches: int):
    retryable_codes = {"timeout", "rate_limited", "provider_unavailable", "connection_failed"}
    retryable_model_codes = {
        "invalid_model_json",
        "invalid_model_schema",
        "coverage_gap",
        "duplicate_coverage",
        "coverage_atom_mismatch",
        "atomized_unit_not_referenced",
    }
    last_error: AIProviderError | None = None
    for attempt_number in range(1, 4):
        try:
            return await generate_batch_result(provider, batch, total_batches)
        except AIProviderError as error:
            last_error = error
            if error.code not in retryable_codes or attempt_number == 3:
                break
            await asyncio.sleep(float(2 ** (attempt_number - 1)))
        except CanonicalAtomizationError as error:
            if error.code not in retryable_model_codes or attempt_number == 3:
                raise
            await asyncio.sleep(float(attempt_number))
    if last_error is None:
        raise AuditTZRuntimeError("provider_error", "ИИ-провайдер не сформировал ответ")
    raise AuditTZRuntimeError(last_error.code, last_error.message)


async def _fail_atomization(
    job_id: UUID,
    lease_token: str,
    db_factory,
    *,
    error_code: str,
) -> None:
    async with db_factory() as db:
        job = await _complete_job(db, job_id, lease_token, status="failed", error_code=error_code)
        run = await db.get(AuditTZRun, job.run_id) if job and job.run_id else None
        attempt = (
            await db.scalar(
                select(AuditAIAtomizationAttempt).where(
                    AuditAIAtomizationAttempt.canonical_run_id == run.id
                )
            )
            if run is not None
            else None
        )
        if attempt is not None and attempt.status == "running":
            attempt.status = "failed"
            attempt.error_code = error_code[:80]
            attempt.config_version += 1
        if run is not None:
            run.status = "failed"
            run.current_phase = "atomization_failed"
            run.error_code = error_code[:100]
            run.finished_at = _now()
            db.add(
                AuditEvent(
                    case_id=run.case_id,
                    actor_id=run.requested_by_id,
                    event_type="audit_tz_atomization_failed",
                    message="ИИ-атомизация ТЗ остановлена",
                    payload_json={
                        "runtime_run_id": str(run.id),
                        "error_code": error_code[:100],
                        "source_unit_count": run.source_unit_count,
                    },
                )
            )
        await db.commit()


async def process_atomization(job_id: UUID, lease_token: str, db_factory) -> None:
    if not settings.AUDIT_TZ_EXTERNAL_AI_ENABLED:
        raise AuditTZRuntimeError(
            "external_ai_disabled",
            "Внешняя ИИ-атомизация отключена конфигурацией DPMS",
        )
    async with db_factory() as db:
        job = await db.get(AuditTZRuntimeJob, job_id)
        run = await db.get(AuditTZRun, job.run_id) if job and job.run_id else None
        attempt = (
            await db.scalar(
                select(AuditAIAtomizationAttempt).where(
                    AuditAIAtomizationAttempt.canonical_run_id == run.id
                )
            )
            if run is not None
            else None
        )
        document = await db.get(AuditDocument, run.document_id) if run else None
        version = await db.get(AuditAtomizationSkillVersion, run.skill_version_id) if run else None
        skill = await db.get(AuditAtomizationSkill, version.skill_id) if version else None
        audit_case = await db.get(AuditCase, run.case_id) if run else None
        provider = await db.get(AIProviderConfig, attempt.provider_config_id) if attempt else None
        if not all((job, run, attempt, document, version, skill, audit_case, provider)):
            raise AuditTZRuntimeError("runtime_context_missing", "Контекст атомизации не найден")
        if (
            attempt.status != "running"
            or attempt.canonical_run_id != run.id
            or run.source_sha256 != document.sha256
            or run.skill_sha256 != version.content_sha256
            or attempt.document_sha256 != document.sha256
            or attempt.skill_sha256 != version.content_sha256
            or version.runtime_status != "ready"
            or not version.is_active
            or not skill.is_enabled
            or not provider.enabled
            or provider.last_test_status != "ok"
            or provider.last_verified_config_version != provider.config_version
            or provider.config_version != attempt.provider_config_version
            or provider.model_name != attempt.model_name
        ):
            raise AuditTZRuntimeError(
                "runtime_context_changed",
                "Документ, методика или ИИ-профиль изменились",
            )
        provider_snapshot = SimpleNamespace(
            id=provider.id,
            display_name=provider.display_name,
            enabled=provider.enabled,
            base_url=provider.base_url,
            model_name=provider.model_name,
            api_key_ciphertext=provider.api_key_ciphertext,
            config_version=provider.config_version,
            last_test_status=provider.last_test_status,
            last_verified_config_version=provider.last_verified_config_version,
        )
        version_snapshot = SimpleNamespace(
            package_format=version.package_format,
            package_blob=bytes(version.package_blob or b""),
            content_sha256=version.content_sha256,
        )
        run_id = run.id
        case_id = run.case_id
        actor_id = attempt.requested_by_id
        digital_product = audit_case.digital_product
        stored_results = list(attempt.batch_results_json or [])

    try:
        skill_root = _skill_directory(version_snapshot)
        run_dir = _runtime_root() / "runs" / str(run_id)
        await _run_cli(
            skill_root,
            "export-prompt",
            [
                "--run",
                str(run_dir),
                "--contract",
                CONTRACT_KEY,
                "--phase",
                "primary",
            ],
            allowed_exit_codes={0},
        )
        prompt_path = run_dir / "contracts" / CONTRACT_KEY / "drafts" / "primary-prompt-packet.json"
        prompt_packet = _read_json_file(prompt_path, max_bytes=MAX_CANONICAL_PACKET_BYTES)
        batches = build_source_batches(prompt_packet)
        if not batches:
            raise AuditTZRuntimeError("canonical_prompt_invalid", "В ТЗ не найдены фрагменты для атомизации")
        cached_by_index = {
            int(item.get("batch_index")): item
            for item in stored_results
            if isinstance(item, dict) and isinstance(item.get("batch_index"), int)
        }
        batch_results = []
        for batch in batches:
            cached = cached_by_index.get(batch.index)
            if cached is not None:
                batch_results.append(restore_batch_result(cached, batch))

        async with db_factory() as db:
            current_run = await db.get(AuditTZRun, run_id)
            current_attempt = await db.scalar(
                select(AuditAIAtomizationAttempt).where(
                    AuditAIAtomizationAttempt.canonical_run_id == run_id
                )
            )
            if current_run is None or current_attempt is None or current_attempt.status != "running":
                raise AuditTZRuntimeError("runtime_context_changed", "Запуск атомизации изменился")
            current_attempt.prompt_sha256 = str(prompt_packet.get("prompt_packet_hash") or "")[:64]
            current_run.total_batch_count = len(batches)
            current_run.completed_batch_count = len(batch_results)
            current_run.status = "atomizing"
            current_run.current_phase = "atomizing"
            await _upsert_artifact(
                db,
                current_run,
                kind="primary_prompt",
                path=prompt_path,
                safe_summary={
                    "source_unit_count": current_run.source_unit_count,
                    "batch_count": len(batches),
                },
                phase="PROMPT_PRIMARY",
            )
            await db.commit()

        result_by_index = {item.batch_index: item for item in batch_results}
        for batch in batches:
            if batch.index in result_by_index:
                continue
            await _renew_job_lease(db_factory, job_id, lease_token)
            async with db_factory() as db:
                active_job = await db.scalar(
                    select(AuditTZRuntimeJob).where(
                        AuditTZRuntimeJob.id == job_id,
                        AuditTZRuntimeJob.status == "running",
                        AuditTZRuntimeJob.lease_token == lease_token,
                    )
                )
                active_run = await db.get(AuditTZRun, run_id)
                if active_job is None or active_run is None:
                    raise AuditTZRuntimeError("worker_lease_lost", "Запуск атомизации больше не активен")
                # Mark before the network call: a timeout can happen after the
                # provider has already received the request.
                active_run.external_ai_called = True
                await db.commit()
            generated = await _generate_batch_with_retry(provider_snapshot, batch, len(batches))
            result_by_index[batch.index] = generated
            batch_results = [result_by_index[index] for index in sorted(result_by_index)]
            async with db_factory() as db:
                current_job = await db.scalar(
                    select(AuditTZRuntimeJob).where(
                        AuditTZRuntimeJob.id == job_id,
                        AuditTZRuntimeJob.status == "running",
                        AuditTZRuntimeJob.lease_token == lease_token,
                    )
                )
                current_run = await db.get(AuditTZRun, run_id)
                current_attempt = await db.scalar(
                    select(AuditAIAtomizationAttempt).where(
                        AuditAIAtomizationAttempt.canonical_run_id == run_id
                    )
                )
                if not all((current_job, current_run, current_attempt)) or current_attempt.status != "running":
                    raise AuditTZRuntimeError("worker_lease_lost", "Запуск атомизации больше не активен")
                current_attempt.batch_results_json = [item.as_storage() for item in batch_results]
                current_attempt.config_version += 1
                current_run.completed_batch_count = len(batch_results)
                current_run.external_ai_called = True
                current_run.safe_summary_json = {
                    **dict(current_run.safe_summary_json or {}),
                    "atomization_batch_count": len(batches),
                    "atomization_batches_completed": len(batch_results),
                    "automatic_redaction_count": sum(item.redaction_count for item in batch_results),
                }
                await db.commit()

        assembled = assemble_atomization_result(
            prompt_packet,
            [result_by_index[index] for index in sorted(result_by_index)],
            model_name=provider_snapshot.model_name,
        )
        generated_path = run_dir / "contracts" / CONTRACT_KEY / "drafts" / "primary.generated.json"
        _atomic_write_json(generated_path, assembled.package)
        await _run_cli(
            skill_root,
            "validate-atoms",
            [
                "--run",
                str(run_dir),
                "--contract",
                CONTRACT_KEY,
                "--input",
                str(generated_path),
            ],
            allowed_exit_codes={0},
        )
        validated_path = run_dir / "contracts" / CONTRACT_KEY / "drafts" / "primary.validated.json"
        validated_package = _read_json_file(validated_path, max_bytes=MAX_CANONICAL_PACKET_BYTES)
        if len(validated_package.get("atoms") or []) != len(assembled.drafts):
            raise AuditTZRuntimeError("validated_atom_count_mismatch", "Проверенный пакет атомов поврежден")
    except CanonicalAtomizationError as error:
        await _fail_atomization(job_id, lease_token, db_factory, error_code=error.code)
        return
    except AuditTZRuntimeError as error:
        await _fail_atomization(job_id, lease_token, db_factory, error_code=error.code)
        return

    async with db_factory() as db:
        job = await _complete_job(db, job_id, lease_token, status="succeeded")
        run = await db.get(AuditTZRun, run_id)
        attempt = await db.scalar(
            select(AuditAIAtomizationAttempt)
            .where(AuditAIAtomizationAttempt.canonical_run_id == run_id)
            .with_for_update()
        )
        audit_case = await db.get(AuditCase, case_id)
        current_atoms = int(
            await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
        )
        if job is None or run is None or attempt is None or audit_case is None:
            await db.rollback()
            return
        if current_atoms:
            await db.rollback()
            await _fail_atomization(
                job_id,
                lease_token,
                db_factory,
                error_code="registry_changed",
            )
            return
        await db.execute(delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == attempt.id))
        for draft in assembled.drafts:
            db.add(
                AuditAIAtomDraft(
                    attempt_id=attempt.id,
                    case_id=case_id,
                    title=draft.title,
                    digital_product=digital_product,
                    work_type=draft.work_type,
                    object_type=draft.object_type,
                    source_clause=draft.source_clause,
                    notes=draft.notes,
                    source_refs_json=draft.source_refs,
                    model_payload_json=draft.model_payload,
                    source_fingerprint=draft.source_fingerprint,
                    confidence_percent=draft.confidence_percent,
                    review_status="pending",
                    sort_order=draft.sort_order,
                )
            )
        attempt.status = "draft_ready"
        attempt.source_manifest_json = assembled.source_manifest
        attempt.coverage_json = assembled.coverage_summary
        attempt.warnings_json = assembled.warnings
        attempt.response_sha256 = assembled.response_sha256
        attempt.error_code = None
        attempt.config_version += 1
        registry = await db.scalar(
            select(AuditAIModelRegistry).where(
                AuditAIModelRegistry.canonical_run_id == run_id,
                AuditAIModelRegistry.provider_config_id == attempt.provider_config_id,
                AuditAIModelRegistry.provider_config_version == attempt.provider_config_version,
                AuditAIModelRegistry.model_name == attempt.model_name,
            )
        )
        if registry is None:
            registry = AuditAIModelRegistry(
                case_id=case_id,
                canonical_run_id=run_id,
                document_id=attempt.document_id,
                skill_version_id=attempt.skill_version_id,
                provider_config_id=attempt.provider_config_id,
                provider_config_version=attempt.provider_config_version,
                provider_name=provider_snapshot.display_name,
                model_name=attempt.model_name,
                document_sha256=attempt.document_sha256,
                skill_sha256=attempt.skill_sha256,
                response_sha256=assembled.response_sha256,
                atom_count=len(assembled.drafts),
                coverage_json=assembled.coverage_summary,
                warnings_json=assembled.warnings,
                created_by_id=actor_id,
            )
            db.add(registry)
            await db.flush()
            for draft in assembled.drafts:
                db.add(
                    AuditAIModelRegistryItem(
                        registry_id=registry.id,
                        case_id=case_id,
                        title=draft.title,
                        digital_product=digital_product,
                        work_type=draft.work_type,
                        object_type=draft.object_type,
                        source_clause=draft.source_clause,
                        notes=draft.notes,
                        source_refs_json=draft.source_refs,
                        source_fingerprint=draft.source_fingerprint,
                        confidence_percent=draft.confidence_percent,
                        sort_order=draft.sort_order,
                    )
                )
        run.status = "draft_ready"
        run.current_phase = "human_review"
        run.atom_count = len(assembled.drafts)
        run.completed_batch_count = run.total_batch_count
        run.external_ai_called = True
        run.error_code = None
        run.finished_at = _now()
        run.safe_summary_json = {
            **dict(run.safe_summary_json or {}),
            "atom_count": run.atom_count,
            "coverage_summary": assembled.coverage_summary,
            "automatic_redaction_count": assembled.redaction_count,
        }
        await _upsert_artifact(
            db,
            run,
            kind="primary_atom_package",
            path=validated_path,
            safe_summary={
                "atom_count": run.atom_count,
                "source_unit_count": run.source_unit_count,
            },
            phase="VALIDATED_ATOMS_PRIMARY",
        )
        db.add(
            AuditEvent(
                case_id=case_id,
                actor_id=actor_id,
                event_type="audit_tz_atomization_ready",
                message="Сформирован проверяемый черновик атомов",
                payload_json={
                    "runtime_run_id": str(run.id),
                    "attempt_id": str(attempt.id),
                    "atom_count": run.atom_count,
                    "source_unit_count": run.source_unit_count,
                    "model_name": attempt.model_name,
                    "model_registry_id": str(registry.id),
                },
            )
        )
        await db.commit()


async def process_runtime_job(job: ClaimedRuntimeJob, db_factory) -> None:
    if job.kind == "skill_selftest":
        await process_skill_selftest(job.id, job.lease_token, db_factory)
        return
    if job.kind == "preflight":
        await process_preflight(job.id, job.lease_token, db_factory)
        return
    if job.kind == "atomization":
        await process_atomization(job.id, job.lease_token, db_factory)
        return
    raise AuditTZRuntimeError("unsupported_runtime_job", "Неизвестный тип задания runtime")


async def fail_claimed_runtime_job(
    job: ClaimedRuntimeJob,
    db_factory,
    *,
    error_code: str,
) -> None:
    """Fail a still-leased job without persisting exception text or sensitive values."""
    code = _safe_code(error_code, "runtime_internal_error")
    async with db_factory() as db:
        current = await _complete_job(
            db,
            job.id,
            job.lease_token,
            status="failed",
            error_code=code,
        )
        if current is None:
            await db.rollback()
            return
        if current.kind == "skill_selftest":
            version = await db.get(AuditAtomizationSkillVersion, current.skill_version_id)
            if version is not None:
                version.runtime_status = "runtime_failed"
                version.runtime_checked_at = _now()
                version.runtime_error_code = code
                version.runtime_selftest_json = {}
        elif current.run_id is not None:
            run = await db.get(AuditTZRun, current.run_id)
            if run is not None:
                run.status = "failed"
                run.current_phase = (
                    "atomization_failed" if current.kind == "atomization" else "failed"
                )
                run.error_code = code
                run.finished_at = _now()
                run.identifier_ciphertext = None
                run.identifiers_purged_at = _now()
                db.add(
                    AuditEvent(
                        case_id=run.case_id,
                        actor_id=run.requested_by_id,
                        event_type=(
                            "audit_tz_atomization_failed"
                            if current.kind == "atomization"
                            else "audit_tz_preflight_failed"
                        ),
                        message=(
                            "ИИ-атомизация ТЗ завершилась технической ошибкой"
                            if current.kind == "atomization"
                            else "Подготовка документа завершилась технической ошибкой"
                        ),
                        payload_json={"runtime_run_id": str(run.id), "error_code": code},
                    )
                )
                if current.kind == "atomization":
                    attempt = await db.scalar(
                        select(AuditAIAtomizationAttempt).where(
                            AuditAIAtomizationAttempt.canonical_run_id == run.id
                        )
                    )
                    if attempt is not None and attempt.status == "running":
                        attempt.status = "failed"
                        attempt.error_code = code[:80]
                        attempt.config_version += 1
        await db.commit()
