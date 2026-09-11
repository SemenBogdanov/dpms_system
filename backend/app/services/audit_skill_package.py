"""Validation for declarative and trusted audit atomization skill packages."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import os
import posixpath
import re
import shutil
import stat
from struct import Struct, error as StructError
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo
from zlib import MAX_WBITS, crc32, decompressobj, error as ZlibError

from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.schemas.audit_ai import AuditAtomizationSkillPackage

try:
    import yaml
except ImportError:
    yaml = None


MAX_DECLARATIVE_SKILL_BYTES = 256 * 1024
MAX_DECLARATIVE_INSTRUCTION_BYTES = 128 * 1024
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
_DECLARATIVE_SUFFIXES = {".md", ".txt", ".csv", ".json"}
_SENSITIVE_PATH_RE = re.compile(r"secret|key|token|auth|credential|password|session|\.env", re.I)
_REMOTE_RE = re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://|\b(?:data|javascript|file):", re.I)
# Scan destinations independently of label nesting and line breaks.
_INLINE_LINK_RE = re.compile(r"\]\(\s*(<[^>\r\n]*>|[^\s)]+)")
_REFERENCE_LINK_RE = re.compile(r"(?m)^ {0,3}\[[^\[\]]+\]:\s*(<[^>\r\n]*>|\S+)")
_ZIP_LOCAL_HEADER = Struct("<4s5H3I2H")
_ZIP_DATA_DESCRIPTOR = Struct("<3I")
_INCLUDE_RE = re.compile(
    r"^[ \t]*(?:[!@]include|include[ \t]*:|\.\.[ \t]+include::)"
    r"|\{[%{][ \t]*include\b|<!--[ \t]*#include\b"
    r"|<[ \t]*(?:script|iframe|object|embed)\b|\b(?:src|href)\s*=",
    re.I | re.M,
)


def _declarative_error(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _unsupported_executable() -> HTTPException:
    return _declarative_error(
        "Неизвестный исполняемый .skill не поддерживается: код требует проверки и точного "
        "SHA-256 в доверенном списке DPMS. Декларативный архив допускает только SKILL.md "
        "и локальные .md/.txt/.csv/.json без исполняемых файлов."
    )


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
        raise HTTPException(status_code=400, detail="Skill импортируется как JSON или .skill")
    if not data:
        raise HTTPException(status_code=400, detail="Файл skill пустой")
    if len(data) > MAX_DECLARATIVE_SKILL_BYTES:
        raise HTTPException(status_code=413, detail="JSON skill больше 256 КБ")
    try:
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


def _declarative_frontmatter(skill_text: str) -> dict[str, str]:
    lines = skill_text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise _declarative_error("SKILL.md должен начинаться с закрытого frontmatter ---")
    end = lines.index("---", 1)
    source = "\n".join(lines[1:end])
    if not "\n".join(lines[end + 1:]).strip():
        raise _declarative_error("SKILL.md не содержит инструкций после frontmatter")
    fields: dict[str, str] = {}
    if yaml is not None:
        try:
            # Parse scalars only: no object construction, aliases, tags or nested structures.
            mappings = 0
            for token in yaml.scan(source):
                if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.TagToken)):
                    raise _declarative_error("Frontmatter не допускает YAML anchors, aliases или tags")
                if isinstance(token, yaml.tokens.BlockMappingStartToken):
                    mappings += 1
                if mappings > 1 or isinstance(token, (
                    yaml.tokens.FlowMappingStartToken, yaml.tokens.FlowSequenceStartToken,
                    yaml.tokens.BlockSequenceStartToken, yaml.tokens.DirectiveToken,
                )):
                    raise _declarative_error("Frontmatter допускает только текстовые поля без вложенных объектов")
            node = yaml.compose(source, Loader=yaml.BaseLoader)
            if not isinstance(node, yaml.nodes.MappingNode):
                raise _declarative_error("Frontmatter должен содержать поля name, description и необязательный version")
            for key, value in node.value:
                if not isinstance(key, yaml.nodes.ScalarNode) or not isinstance(value, yaml.nodes.ScalarNode):
                    raise _declarative_error("Frontmatter допускает только текстовые поля без вложенных объектов")
                if key.value in fields:
                    raise _declarative_error("Frontmatter содержит повторное поле")
                fields[key.value] = value.value.strip()
        except yaml.YAMLError:
            raise _declarative_error("Некорректный YAML frontmatter в SKILL.md") from None
    else:
        # Without PyYAML support only unambiguous, single-line text scalars.
        for line in source.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([a-z][a-z-]*):[ \t]+(.+)", line)
            if not match:
                raise _declarative_error("Без YAML parser frontmatter допускает только однострочные name, description, version")
            key, value = match.groups()
            value = value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise _declarative_error("Некорректное quoted поле frontmatter") from None
            elif value.startswith("'"):
                if not re.fullmatch(r"'(?:[^']|'')*'", value):
                    raise _declarative_error("Некорректное quoted поле frontmatter")
                value = value[1:-1].replace("''", "'")
            elif value.startswith(tuple("!&*|>{[")) or " #" in value or ": " in value:
                raise _declarative_error("Для сложного YAML frontmatter требуется YAML parser")
            if key in fields:
                raise _declarative_error("Frontmatter содержит повторное поле")
            fields[key] = value.strip()

    if set(fields) - {"name", "description", "version"}:
        raise _declarative_error("Поддерживаются только поля frontmatter name, description, version; executable/include/tools запрещены")
    for value in fields.values():
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise _declarative_error("Поля frontmatter должны быть корректным Unicode без управляющих символов")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields.get("name", "")) or not 2 <= len(fields["name"]) <= 120:
        raise _declarative_error("Frontmatter name должен быть slug из 2-120 символов a-z, 0-9 и дефисов")
    if not 1 <= len(fields.get("description", "")) <= 2000:
        raise _declarative_error("Frontmatter description должен содержать 1-2000 символов")
    if "version" in fields and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}", fields["version"]):
        raise _declarative_error("Frontmatter version должен быть безопасной меткой из 1-80 символов")
    return fields


def _declarative_member_path(info: ZipInfo) -> PurePosixPath:
    raw = info.orig_filename
    parts = raw.removesuffix("/").split("/")
    if (
        not raw or len(raw) > 255 or raw != info.filename
        or any(part in {"", ".", ".."} for part in parts)
        or any(not re.fullmatch(r"[\w .-]+", part) or part.endswith((" ", ".")) for part in parts)
    ):
        raise _declarative_error("Архив skill содержит небезопасный путь")
    if any(part.startswith(".") or _SENSITIVE_PATH_RE.search(part) for part in parts):
        raise _declarative_error("Архив skill содержит скрытый или sensitive путь")
    path = _archive_member_path(info)
    if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
        raise _declarative_error("Декларативный ZIP поддерживает только STORE и DEFLATE")
    if any(part.casefold() in {"scripts", "bin", "node_modules", "venv", "__pycache__"} for part in parts):
        raise _unsupported_executable()
    mode = info.external_attr >> 16
    if info.is_dir():
        if info.file_size or stat.S_IFMT(mode) == stat.S_IFREG:
            raise _declarative_error("Некорректный каталог в архиве skill")
    elif stat.S_IFMT(mode) == stat.S_IFDIR or mode & 0o111 or path.suffix.lower() not in _DECLARATIVE_SUFFIXES:
        raise _unsupported_executable()
    return path


def _validate_declarative_text(path: str, text: str, files: set[str]) -> None:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text) or "\x7f" in text:
        raise _declarative_error("Файлы skill должны быть текстом UTF-8 без управляющих символов")
    if text.lstrip().startswith("#!"):
        raise _unsupported_executable()
    if _REMOTE_RE.search(text) or _INCLUDE_RE.search(text):
        raise _declarative_error("Remote/include и исполняемая разметка в декларативном skill запрещены")
    for fence in re.finditer(r"(?m)^ {0,3}(?:`{3,}|~{3,})[ \t]*([^\r\n]*)", text):
        if fence.group(1).strip().casefold() not in {"", "text", "txt", "md", "markdown", "csv", "json"}:
            raise _unsupported_executable()
    if re.search(r"!?\[\[|<\s*(?:https?:|file:|//)", text, re.I):
        raise _declarative_error("Неподдерживаемый include/link; используйте локальные Markdown-ссылки")
    for pattern in (_INLINE_LINK_RE, _REFERENCE_LINK_RE):
        for match in pattern.finditer(text):
            target = match.group(1).removeprefix("<").removesuffix(">")
            if target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if not target or target.startswith(("/", "~")) or any(char in target for char in "\\:%?\x00"):
                raise _declarative_error("Ссылки skill должны указывать только на локальные файлы пакета")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            if resolved not in files:
                raise _declarative_error("Локальная ссылка skill выходит из пакета или ссылается на отсутствующий файл")


def _read_declarative_archive_member(
    data: bytes, archive: ZipFile, info: ZipInfo, *, max_bytes: int,
) -> bytes:
    # Keep zipfile's local-name/overlap checks, but do not use its size-clamped reader.
    with archive.open(info, "r"):
        pass
    (
        signature, _version, flags, method, _time, _date, crc, compressed_size,
        file_size, name_size, extra_size,
    ) = _ZIP_LOCAL_HEADER.unpack_from(data, info.header_offset)
    if signature != b"PK\x03\x04" or flags != info.flag_bits or method != info.compress_type:
        raise _declarative_error("Локальный заголовок ZIP не совпадает с manifest")
    if 0xFFFFFFFF in (compressed_size, file_size) or info.extract_version >= 45:
        raise _declarative_error("ZIP64 не поддерживается для декларативного skill; используйте обычный ZIP")
    expected = (info.CRC, info.compress_size, info.file_size)
    local = (crc, compressed_size, file_size)
    if flags & 0x8:
        if any(value not in (0, wanted) for value, wanted in zip(local, expected, strict=True)):
            raise _declarative_error("Локальный размер или CRC ZIP не совпадает с manifest")
    elif local != expected:
        raise _declarative_error("Локальный размер или CRC ZIP не совпадает с manifest")
    start = info.header_offset + _ZIP_LOCAL_HEADER.size + name_size + extra_size
    end = start + info.compress_size
    if start < 0 or end > len(data):
        raise _declarative_error("Данные файла выходят за границы ZIP")
    if flags & 0x8:
        descriptor_offset = end + 4 if data[end:end + 4] == b"PK\x07\x08" else end
        if _ZIP_DATA_DESCRIPTOR.unpack_from(data, descriptor_offset) != expected:
            raise _declarative_error("Data descriptor ZIP не совпадает с manifest")
    if method == ZIP_STORED:
        if info.compress_size != info.file_size:
            raise _declarative_error("Размер STORE-файла ZIP не совпадает с manifest")
        if info.compress_size > max_bytes:
            raise HTTPException(status_code=413, detail="Полный текст skill с references превышает 128 KiB UTF-8")
        content = data[start:end]
    else:
        stream = decompressobj(-MAX_WBITS)
        content = stream.decompress(data[start:end], max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Полный текст skill с references превышает 128 KiB UTF-8")
        if not stream.eof or stream.unused_data or stream.unconsumed_tail:
            raise _declarative_error("DEFLATE-поток ZIP неполный или содержит лишние данные")
    if len(content) != info.file_size or crc32(content) != info.CRC:
        raise _declarative_error("Фактический размер или CRC файла ZIP не совпадает с manifest")
    return content


def _parse_declarative_archive(filename: str, data: bytes) -> ParsedAuditSkillUpload:
    if not data:
        raise HTTPException(status_code=400, detail="Файл skill пустой")
    if len(data) > MAX_SKILL_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Архив skill больше 2 МБ")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_SKILL_ARCHIVE_FILES:
                raise HTTPException(status_code=413, detail="Архив skill содержит недопустимое число файлов")
            paths = [_declarative_member_path(info) for info in infos]
            names = [path.as_posix().casefold() for path in paths]
            if len(set(names)) != len(names):
                raise _declarative_error("Архив skill содержит дублирующиеся пути")
            file_paths = {path for info, path in zip(infos, paths, strict=True) if not info.is_dir()}
            folded_files = {path.as_posix().casefold() for path in file_paths}
            if any(parent.as_posix().casefold() in folded_files for path in paths for parent in path.parents):
                raise _declarative_error("Путь skill одновременно является файлом и каталогом")
            if PurePosixPath("SKILL.md") in file_paths:
                root = ""
            else:
                roots = {path.parts[0] for path in paths}
                if len(roots) != 1 or PurePosixPath(next(iter(roots)), "SKILL.md") not in file_paths:
                    raise _declarative_error("Архив должен содержать SKILL.md в корне или одном корневом каталоге")
                root = next(iter(roots))
            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_DECLARATIVE_INSTRUCTION_BYTES:
                raise HTTPException(status_code=413, detail="Полный текст skill с references превышает 128 KiB UTF-8")
            content_by_path: dict[str, str] = {}
            manifest_files = []
            actual_total_size = 0
            for info, path in zip(infos, paths, strict=True):
                content = _read_declarative_archive_member(
                    data, archive, info, max_bytes=MAX_DECLARATIVE_INSTRUCTION_BYTES - actual_total_size,
                )
                actual_total_size += len(content)
                if info.is_dir():
                    continue
                relative = path.relative_to(root).as_posix() if root else path.as_posix()
                if path.name.casefold() == "skill.md" and relative != "SKILL.md":
                    raise _declarative_error("Архив должен содержать только один SKILL.md")
                content_by_path[relative] = content.decode("utf-8")
                manifest_files.append({"path": relative, "size_bytes": len(content), "sha256": sha256(content).hexdigest()})
    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise _declarative_error("Все файлы декларативного skill должны быть в UTF-8") from None
    except (BadZipFile, KeyError, OSError, ValueError, RuntimeError, EOFError, ZlibError, StructError):
        raise HTTPException(status_code=400, detail="Не удалось прочитать архив skill") from None

    fields = _declarative_frontmatter(content_by_path["SKILL.md"])
    for path, text in content_by_path.items():
        _validate_declarative_text(path, text, set(content_by_path))
    # Include every data file once, not just the first-level linked references.
    instructions = content_by_path["SKILL.md"] + "".join(
        f"\n\n## Reference: {path}\n\n{content_by_path[path]}"
        for path in sorted(content_by_path) if path != "SKILL.md"
    )
    instruction_bytes = instructions.encode("utf-8")
    if len(instruction_bytes) > MAX_DECLARATIVE_INSTRUCTION_BYTES:
        raise HTTPException(status_code=413, detail="Полный текст skill с references превышает 128 KiB UTF-8")
    digest = sha256(data).hexdigest()
    return ParsedAuditSkillUpload(
        slug=fields["name"],
        name=fields["name"],
        description=fields["description"],
        version=fields.get("version", f"sha256-{digest}"),
        schema_version="1.0",
        instructions=instructions,
        rules=[],
        content_sha256=digest,
        source_filename=Path(filename or "audit-skill.skill").name[:255],
        package_format="declarative_archive",
        package_blob=data,
        package_manifest={
            "format": "dpms-declarative-archive-v1",
            "root": root,
            "file_count": len(manifest_files),
            "uncompressed_bytes": total_size,
            "files": sorted(manifest_files, key=lambda item: item["path"]),
            "instruction_bytes": len(instruction_bytes),
            "instructions_sha256": sha256(instruction_bytes).hexdigest(),
            "version_source": "frontmatter" if "version" in fields else "archive_sha256",
        },
        runtime_status="ready",
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
        allowed = _trusted_hashes() if trusted_hashes is None else {item.lower() for item in trusted_hashes}
        if sha256(data).hexdigest() in allowed:
            # An allowlisted package must still satisfy the canonical trusted contract.
            return _parse_trusted_archive(filename, data, trusted_hashes=allowed)
        return _parse_declarative_archive(filename, data)
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
