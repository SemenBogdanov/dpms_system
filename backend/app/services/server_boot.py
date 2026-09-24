"""Bounded, read-only host journal import and admin reporting."""
from __future__ import annotations

import asyncio
import configparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import math
import os
from pathlib import Path
import re
import stat

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server_boot import ServerBootEvent, ServerBootImportStatus
from app.schemas.server_boot import (
    ImportErrorCode, ServerBootImportRead, ServerBootListRead, ServerBootRead, as_utc,
)


DEFAULT_DIRECTORY = Path("/var/lib/dpms-boot-events")
DEFAULT_SOURCE_ID = "primary-vps"
MAX_EVENT_BYTES = 8192
MAX_SCAN_FILES = 10_000  # Bounds all directory entries, including unpublished temporary files.
INSERT_BATCH_SIZE = 500
MAX_OFFSET = 1_000_000
STALE_SECONDS = 180
FUTURE_CLOCK_TOLERANCE_SECONDS = 5
EVENT_NAME = re.compile(r"boot-([0-9a-f]{32})\.txt\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z", re.ASCII)
FIELDS = frozenset({
    "format_version", "event_id", "boot_time_utc", "recorded_at_utc",
    "uptime_seconds_at_record", "reason", "clock",
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def source_id_from_env() -> str:
    return validate_source_id(os.environ.get("SERVER_BOOT_SOURCE_ID", DEFAULT_SOURCE_ID))


def validate_source_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
        raise ValueError("Invalid boot source identifier")
    return value


@dataclass(frozen=True)
class BootEvent:
    event_id: str
    boot_time: datetime
    recorded_at: datetime
    uptime_seconds: float
    content_hash: str


@dataclass
class BootScan:
    events: list[BootEvent] = field(default_factory=list)
    checked_files: int = 0
    invalid_files: int = 0
    error_code: ImportErrorCode | None = None


def parse_event(raw: bytes, filename: str) -> BootEvent:
    """Only the recorder's v1 INI schema is accepted; errors never echo input."""
    match = EVENT_NAME.fullmatch(filename)
    if match is None or len(raw) > MAX_EVENT_BYTES:
        raise ValueError("Invalid boot event")
    try:
        data = configparser.ConfigParser(
            interpolation=None, strict=True, delimiters=("=",),
            empty_lines_in_values=False, default_section="",
        )
        data.optionxform = str
        data.read_string(raw.decode("utf-8", errors="strict"))
        if data.sections() != ["server_boot"] or data.defaults():
            raise ValueError
        item = data["server_boot"]
        if set(item) != FIELDS or any("\n" in value for value in item.values()):
            raise ValueError
        if (
            item["format_version"] != "1" or item["event_id"] != match.group(1)
            or item["reason"] != "unknown"
            or item["clock"] != "system_clock_not_independently_verified"
        ):
            raise ValueError
        timestamps = []
        for name in ("boot_time_utc", "recorded_at_utc"):
            value = item[name]
            if not TIMESTAMP.fullmatch(value):
                raise ValueError
            timestamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc))
        uptime_text = item["uptime_seconds_at_record"]
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", uptime_text):
            raise ValueError
        uptime = float(uptime_text)
        if not math.isfinite(uptime) or uptime < 0:
            raise ValueError
        return BootEvent(match.group(1), *timestamps, uptime, hashlib.sha256(raw).hexdigest())
    except (ValueError, OverflowError, KeyError, configparser.Error):
        raise ValueError("Invalid boot event") from None


def read_event(directory_fd: int, filename: str) -> BootEvent:
    """Open relative to the pinned directory, without following file symlinks."""
    if not EVENT_NAME.fullmatch(filename):
        raise ValueError("Invalid boot event filename")
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EVENT_BYTES:
            raise ValueError("Invalid boot event file")
        raw = bytearray()
        while len(raw) <= MAX_EVENT_BYTES:
            chunk = os.read(fd, MAX_EVENT_BYTES + 1 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        if (
            len(raw) > MAX_EVENT_BYTES or len(raw) != after.st_size
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        ):
            raise ValueError("Boot event changed while reading")
        return parse_event(bytes(raw), filename)
    finally:
        os.close(fd)


def scan_directory(directory: Path) -> BootScan:
    result = BootScan()
    if ".." in directory.parts:
        result.error_code = "directory_unreadable"
        return result
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        if error.errno == errno.ENOENT:
            result.error_code = "directory_missing"
        elif error.errno in (errno.EACCES, errno.EPERM, errno.ELOOP, errno.ENOTDIR):
            result.error_code = "directory_unreadable"
        else:
            result.error_code = "scan_failed"
        return result
    try:
        with os.scandir(directory_fd) as entries:
            for scanned, entry in enumerate(entries):
                if scanned >= MAX_SCAN_FILES:
                    result.error_code = "too_many_files"
                    break
                if entry.name.startswith(".boot-pending-"):
                    continue
                result.checked_files += 1
                try:
                    result.events.append(read_event(directory_fd, entry.name))
                except (OSError, ValueError):
                    result.invalid_files += 1
    except OSError:
        result.error_code = "scan_failed"
    finally:
        os.close(directory_fd)
    return result


def import_status_read(row: ServerBootImportStatus | None, now: datetime) -> ServerBootImportRead:
    if row is None:
        return ServerBootImportRead()
    state = "degraded" if row.error_code else "ok"
    age = (as_utc(now) - as_utc(row.last_attempt_at)).total_seconds()
    if age > STALE_SECONDS or age < -FUTURE_CLOCK_TOLERANCE_SECONDS:
        state = "stale"
    return ServerBootImportRead(
        state=state, last_attempt_at=row.last_attempt_at, last_success_at=row.last_success_at,
        invalid_files=row.invalid_files, conflicting_files=row.conflicting_files,
        checked_files=row.checked_files, error_code=row.error_code,
    )


async def import_boot_events(
    db: AsyncSession, directory: Path, source_id: str, *, now: datetime | None = None,
) -> ServerBootImportRead:
    """Caller owns the single transaction; last_success means a fully clean scan."""
    source_id = validate_source_id(source_id)
    now = as_utc(now or utc_now())
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    # Serialize imports for this source, including the first concurrent startup.
    await db.execute(insert(ServerBootImportStatus).values(
        source_id=source_id, last_attempt_at=now, invalid_files=0, conflicting_files=0, checked_files=0,
    ).on_conflict_do_nothing(index_elements=["source_id"]))
    row = (await db.execute(select(ServerBootImportStatus).where(
        ServerBootImportStatus.source_id == source_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    scan = await asyncio.to_thread(scan_directory, Path(directory))
    existing = {}
    if scan.events:
        existing = dict((await db.execute(select(
            ServerBootEvent.event_id, ServerBootEvent.content_hash,
        ).where(
            ServerBootEvent.source_id == source_id,
            ServerBootEvent.event_id.in_([event.event_id for event in scan.events]),
        ))).all())
    conflicts = 0
    new_events = []
    for event in scan.events:
        if event.event_id in existing:
            conflicts += int(existing[event.event_id] != event.content_hash)
        else:
            new_events.append(dict(
                source_id=source_id, event_id=event.event_id, boot_time=event.boot_time,
                recorded_at=event.recorded_at, uptime_seconds=event.uptime_seconds,
                content_hash=event.content_hash, imported_at=now,
            ))
    for start in range(0, len(new_events), INSERT_BATCH_SIZE):
        await db.execute(insert(ServerBootEvent).values(
            new_events[start:start + INSERT_BATCH_SIZE],
        ).on_conflict_do_nothing(index_elements=["source_id", "event_id"]))
    row.last_attempt_at = now
    row.checked_files = scan.checked_files
    row.invalid_files = scan.invalid_files
    row.conflicting_files = conflicts
    row.error_code = scan.error_code or (
        "conflicting_files" if conflicts else "invalid_files" if scan.invalid_files else None
    )
    if row.error_code is None:
        row.last_success_at = now
    await db.flush()
    return import_status_read(row, now)


async def list_server_boots(
    db: AsyncSession, *, days: int = 0, limit: int = 25, offset: int = 0,
    source_id: str | None = None, now: datetime | None = None,
) -> ServerBootListRead:
    """List all recorded sources; heartbeat describes the configured local source."""
    if not 0 <= days <= 366 or not 1 <= limit <= 100 or not 0 <= offset <= MAX_OFFSET:
        raise ValueError("Invalid boot journal pagination")
    now = as_utc(now or utc_now())
    source_id = source_id_from_env() if source_id is None else validate_source_id(source_id)
    not_future = ServerBootEvent.boot_time <= now
    period = []
    if days:
        period.extend([not_future, ServerBootEvent.boot_time >= now - timedelta(days=days)])
    count = func.count()
    totals = (await db.execute(select(
        count.filter(*period), count,
        count.filter(not_future, ServerBootEvent.boot_time >= now - timedelta(days=7)),
        func.min(ServerBootEvent.imported_at),
    ).select_from(ServerBootEvent))).one()
    items = (await db.execute(select(ServerBootEvent).where(*period).order_by(
        ServerBootEvent.boot_time.desc(), ServerBootEvent.event_id, ServerBootEvent.source_id,
    ).limit(limit).offset(offset))).scalars().all()
    status = await db.get(ServerBootImportStatus, source_id)
    return ServerBootListRead(
        period_days=days, total=totals[0], all_time_count=totals[1], last_7_days_count=totals[2],
        first_imported_at=totals[3], items=[ServerBootRead.model_validate(item) for item in items],
        import_status=import_status_read(status, now),
    )
