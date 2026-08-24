"""Validation for declarative and trusted audit atomization skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import os
import re
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZipInfo

from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.schemas.audit_ai import AuditAtomizationSkillPackage


MAX_DECLARATIVE_SKILL_BYTES = 256 * 1024
MAX_SKILL_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_SKILL_UPLOAD_BYTES = MAX_SKILL_ARCHIVE_BYTES
MAX_SKILL_ARCHIVE_FILES = 256
MAX_SKILL_ARCHIVE_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_SKILL_ARCHIVE_MEMBER_BYTES = 2 * 1024 * 1024
MAX_SKILL_ARCHIVE_COMPRESSION_RATIO = 200

_REQUIRED_ARCHIVE_FILES = {
    "SKILL.md",
    "scripts/audit_tz.py",
    "scripts/audit_tz_lib/__init__.py",
}
_SAFE_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")


@dataclass(frozen=True)
class ParsedAuditSkillUpload:
    slug: str
    name: str
    description: str | None
    version: str
    schema_version: str
    instructions: str
    rules: list[str]
    content_sha256: str
    source_filename: str
    package_format: str
    package_blob: bytes | None
    package_manifest: dict
    runtime_status: str


def _trusted_hashes() -> set[str]:
    configured = getattr(settings, "AUDIT_TRUSTED_SKILL_SHA256", "") or ""
    return {
        item.strip().lower()
        for item in configured.split(",")
        if re.fullmatch(r"[0-9a-fA-F]{64}", item.strip())
    }


def parse_audit_skill_package(
    filename: str,
    data: bytes,
) -> tuple[AuditAtomizationSkillPackage, str]:
    """Parse the legacy data-only JSON package without changing its contract."""
    safe_name = Path(filename or "audit-skill.json").name[:255]
    if Path(safe_name).suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="Skill импортируется как JSON или доверенный .skill")
    if not data:
        raise HTTPException(status_code=400, detail="Файл skill пустой")
    if len(data) > MAX_DECLARATIVE_SKILL_BYTES:
        raise HTTPException(status_code=413, detail="JSON skill больше 256 КБ")
    try:
        import json

        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Skill должен быть корректным UTF-8 JSON")
    try:
        package = AuditAtomizationSkillPackage.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(item) for item in first.get("loc", ())) or "skill"
        raise HTTPException(status_code=422, detail=f"Некорректное поле {field}: {first.get('msg', 'ошибка')}")
    return package, sha256(data).hexdigest()


def _archive_member_path(info: ZipInfo) -> PurePosixPath:
    raw_name = info.filename
    if not raw_name or "\\" in raw_name or raw_name.startswith("/"):
        raise HTTPException(status_code=422, detail="Архив skill содержит небезопасный путь")
    path = PurePosixPath(raw_name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=422, detail="Архив skill содержит небезопасный путь")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
        raise HTTPException(status_code=422, detail="Архив skill содержит ссылку или специальный файл")
    if info.flag_bits & 0x1:
        raise HTTPException(status_code=422, detail="Зашифрованный архив skill не поддерживается")
    if info.file_size > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
        raise HTTPException(status_code=413, detail="Один из файлов skill превышает безопасный размер")
    if not info.is_dir() and info.file_size > 0 and info.compress_size == 0:
        raise HTTPException(status_code=422, detail="Архив skill содержит некорректную запись")
    if (
        info.file_size > 0
        and info.compress_size > 0
        and info.file_size / info.compress_size > MAX_SKILL_ARCHIVE_COMPRESSION_RATIO
    ):
        raise HTTPException(status_code=413, detail="Архив skill отклонен проверкой степени сжатия")
    return path


def _read_archive_member(archive: ZipFile, info: ZipInfo) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with archive.open(info, "r") as source:
        while True:
            chunk = source.read(min(64 * 1024, MAX_SKILL_ARCHIVE_MEMBER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_SKILL_ARCHIVE_MEMBER_BYTES:
                raise HTTPException(status_code=413, detail="Один из файлов skill превышает безопасный размер")
    if total != info.file_size:
        raise HTTPException(status_code=422, detail="Размер файла внутри skill не совпадает с manifest ZIP")
    return b"".join(chunks)


def _frontmatter_value(skill_text: str, field: str) -> str | None:
    if not skill_text.startswith("---"):
        return None
    end = skill_text.find("\n---", 3)
    if end < 0:
        return None
    pattern = re.compile(rf"^{re.escape(field)}\s*:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(skill_text[3:end])
    if match is None:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip() or None


def _python_constant(source: str, name: str) -> str | None:
    match = re.search(
        rf"(?m)^\s*{re.escape(name)}\s*=\s*(['\"])([^'\"\r\n]+)\1\s*$",
        source,
    )
    return match.group(2).strip() if match else None


def _parse_trusted_archive(
    filename: str,
    data: bytes,
    *,
    trusted_hashes: set[str] | None = None,
) -> ParsedAuditSkillUpload:
    if not data:
        raise HTTPException(status_code=400, detail="Файл skill пустой")
    if len(data) > MAX_SKILL_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Архив skill больше 2 МБ")
    digest = sha256(data).hexdigest()
    allowed = _trusted_hashes() if trusted_hashes is None else {item.lower() for item in trusted_hashes}
    if digest not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Архив skill не входит в доверенный список DPMS; требуется проверка и регистрация SHA-256",
        )
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_SKILL_ARCHIVE_FILES:
                raise HTTPException(status_code=413, detail="Архив skill содержит недопустимое число файлов")
            paths: list[PurePosixPath] = []
            seen: set[str] = set()
            total_size = 0
            for info in infos:
                path = _archive_member_path(info)
                normalized = path.as_posix().rstrip("/")
                collision_key = normalized.casefold()
                if collision_key in seen:
                    raise HTTPException(status_code=422, detail="Архив skill содержит дублирующиеся пути")
                seen.add(collision_key)
                paths.append(path)
                total_size += info.file_size
            if total_size > MAX_SKILL_ARCHIVE_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Распакованный skill превышает 8 МБ")
            roots = {path.parts[0] for path in paths}
            if roots != {"audit-tz"}:
                raise HTTPException(status_code=422, detail="Архив должен содержать единственный корневой каталог audit-tz")
            file_entries = [
                (info, path)
                for info, path in zip(infos, paths, strict=True)
                if not info.is_dir()
            ]
            relative_names = {
                PurePosixPath(*path.parts[1:]).as_posix()
                for _, path in file_entries
                if len(path.parts) > 1
            }
            missing = sorted(_REQUIRED_ARCHIVE_FILES - relative_names)
            if missing:
                raise HTTPException(status_code=422, detail=f"В архиве skill отсутствует {missing[0]}")
            content_by_path: dict[str, bytes] = {}
            manifest_files = []
            actual_total_size = 0
            for info, path in file_entries:
                content = _read_archive_member(archive, info)
                actual_total_size += len(content)
                if actual_total_size > MAX_SKILL_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=413, detail="Распакованный skill превышает 8 МБ")
                relative_path = PurePosixPath(*path.parts[1:]).as_posix()
                if relative_path in _REQUIRED_ARCHIVE_FILES:
                    content_by_path[relative_path] = content
                manifest_files.append({
                    "path": relative_path,
                    "size_bytes": info.file_size,
                    "sha256": sha256(content).hexdigest(),
                })
            skill_bytes = content_by_path["SKILL.md"]
            init_bytes = content_by_path["scripts/audit_tz_lib/__init__.py"]
    except HTTPException:
        raise
    except (BadZipFile, KeyError, OSError):
        raise HTTPException(status_code=400, detail="Не удалось прочитать архив skill")

    try:
        skill_text = skill_bytes.decode("utf-8")
        init_text = init_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="Критические файлы skill должны быть в UTF-8")
    slug = _frontmatter_value(skill_text, "name")
    description = _frontmatter_value(skill_text, "description")
    version = _python_constant(init_text, "SKILL_VERSION")
    schema_version = _python_constant(init_text, "SCHEMA_VERSION")
    if slug != "audit-tz":
        raise HTTPException(status_code=422, detail="Доверенный архив должен объявлять skill audit-tz")
    if version is None or not _SAFE_VERSION_RE.fullmatch(version):
        raise HTTPException(status_code=422, detail="В архиве отсутствует корректный SKILL_VERSION")
    if schema_version != "1.0":
        raise HTTPException(status_code=422, detail="Версия schema skill не поддерживается")
    if not description or len(description) > 2000:
        raise HTTPException(status_code=422, detail="В SKILL.md отсутствует корректное описание")
    return ParsedAuditSkillUpload(
        slug=slug,
        name="Аудит ТЗ",
        description=description,
        version=version,
        schema_version=schema_version,
        instructions=skill_text,
        rules=[],
        content_sha256=digest,
        source_filename=Path(filename or "audit-tz.skill").name[:255],
        package_format="trusted_skill_archive",
        package_blob=data,
        package_manifest={
            "format": "dpms-trusted-skill-v1",
            "root": "audit-tz",
            "file_count": len(manifest_files),
            "uncompressed_bytes": total_size,
            "files": sorted(manifest_files, key=lambda item: item["path"]),
        },
        runtime_status="pending_worker",
    )


def parse_audit_skill_upload(
    filename: str,
    data: bytes,
    *,
    trusted_hashes: set[str] | None = None,
) -> ParsedAuditSkillUpload:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".json":
        package, digest = parse_audit_skill_package(filename, data)
        return ParsedAuditSkillUpload(
            slug=package.slug,
            name=package.name,
            description=package.description,
            version=package.version,
            schema_version=package.schema_version,
            instructions=package.instructions,
            rules=package.rules,
            content_sha256=digest,
            source_filename=Path(filename or "audit-skill.json").name[:255],
            package_format="declarative_json",
            package_blob=None,
            package_manifest={"format": "dpms-declarative-skill-v1"},
            runtime_status="ready",
        )
    if suffix == ".skill":
        return _parse_trusted_archive(filename, data, trusted_hashes=trusted_hashes)
    raise HTTPException(status_code=400, detail="Поддерживаются только .json и .skill")


def extract_trusted_skill_archive(
    data: bytes,
    destination: Path,
    *,
    expected_sha256: str,
) -> Path:
    """Revalidate and atomically materialize an allowlisted archive for the worker."""
    expected = expected_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(data).hexdigest() != expected:
        raise HTTPException(status_code=409, detail="SHA-256 сохраненного skill не совпадает")
    parsed = _parse_trusted_archive("audit-tz.skill", data)
    if parsed.content_sha256 != expected:
        raise HTTPException(status_code=409, detail="Версия skill изменилась после импорта")

    if destination.is_symlink():
        raise HTTPException(status_code=409, detail="Каталог runtime skill не должен быть ссылкой")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected_root = destination / "audit-tz"
    if expected_root.is_symlink():
        raise HTTPException(status_code=409, detail="Каталог runtime skill не должен быть ссылкой")
    if expected_root.is_dir():
        for item in parsed.package_manifest.get("files", []):
            relative = item.get("path")
            digest = item.get("sha256")
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise HTTPException(status_code=409, detail="Manifest skill поврежден")
            raw_candidate = expected_root / relative
            current = expected_root
            for part in PurePosixPath(relative).parts:
                current = current / part
                if current.is_symlink():
                    raise HTTPException(status_code=409, detail="Распакованный runtime skill содержит ссылку")
            candidate = raw_candidate.resolve()
            try:
                candidate.relative_to(expected_root.resolve())
            except ValueError:
                raise HTTPException(status_code=409, detail="Manifest skill содержит небезопасный путь")
            if not candidate.is_file() or sha256(candidate.read_bytes()).hexdigest() != digest:
                raise HTTPException(status_code=409, detail="Распакованный runtime skill не прошел проверку hash")
        return expected_root

    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            paths = [_archive_member_path(info) for info in infos]
            for info, path in zip(infos, paths, strict=True):
                target = staging.joinpath(*path.parts)
                resolved = target.resolve()
                try:
                    resolved.relative_to(staging.resolve())
                except ValueError:
                    raise HTTPException(status_code=422, detail="Архив skill содержит небезопасный путь")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                content = _read_archive_member(archive, info)
                with target.open("xb") as handle:
                    handle.write(content)
                target.chmod(0o400)
        root = staging / "audit-tz"
        if not root.is_dir():
            raise HTTPException(status_code=422, detail="Корень audit-tz отсутствует после распаковки")
        for directory in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            directory.chmod(0o500)
        root.chmod(0o500)
        try:
            os.replace(staging, destination)
        except FileExistsError:
            shutil.rmtree(staging, ignore_errors=True)
        return expected_root
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
