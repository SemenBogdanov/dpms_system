#!/usr/bin/env python3
"""Record one durable, non-sensitive text event per Linux host boot."""
from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from uuid import UUID


DEFAULT_DIRECTORY = Path("/var/lib/dpms-boot-events")
EVENT_NAME = re.compile(r"boot-[0-9a-f]{32}\.txt\Z")
MAX_EVENT_BYTES = 8192


@dataclass(frozen=True)
class BootEvent:
    event_id: str
    booted_at: datetime
    recorded_at: datetime
    uptime_seconds: float


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_boot(proc: Path = Path("/proc"), now: datetime | None = None) -> BootEvent:
    # These kernel counters contain no application data or credentials.
    boot_id = str(UUID((proc / "sys/kernel/random/boot_id").read_text().strip()))
    uptime = float((proc / "uptime").read_text().split()[0])
    if not math.isfinite(uptime) or uptime < 0:
        raise ValueError("Invalid uptime")
    boot_seconds = next(
        int(line.split()[1]) for line in (proc / "stat").read_text().splitlines()
        if line.startswith("btime ")
    )
    return BootEvent(
        event_id=hashlib.sha256(boot_id.encode("ascii")).hexdigest()[:32],
        booted_at=datetime.fromtimestamp(boot_seconds, timezone.utc),
        recorded_at=now or datetime.now(timezone.utc),
        uptime_seconds=uptime,
    )


def encode_event(event: BootEvent) -> str:
    data = configparser.ConfigParser(interpolation=None)
    data["server_boot"] = {
        "format_version": "1",
        "event_id": event.event_id,
        "boot_time_utc": utc_text(event.booted_at),
        "recorded_at_utc": utc_text(event.recorded_at),
        "uptime_seconds_at_record": f"{event.uptime_seconds:.3f}",
        "reason": "unknown",
        "clock": "system_clock_not_independently_verified",
    }
    output = io.StringIO()
    output.write("# DPMS: обнаружена загрузка сервера (Linux host).\n")
    output.write("# Это не перезапуск приложения или контейнера.\n")
    output.write("# Причина перезагрузки неизвестна; время в UTC по часам сервера.\n")
    data.write(output)
    return output.getvalue()


def write_event(directory: Path, event: BootEvent) -> tuple[Path, bool]:
    if not re.fullmatch(r"[0-9a-f]{32}", event.event_id):
        raise ValueError("Invalid event ID")
    directory.mkdir(exist_ok=True, mode=0o750)
    if directory.is_symlink():
        raise ValueError("Event directory must not be a symlink")
    target = directory / f"boot-{event.event_id}.txt"
    fd, temporary = tempfile.mkstemp(prefix=".boot-pending-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write(encode_event(event))
            stream.flush()
            os.fsync(stream.fileno())
        # Publish atomically without replacing a record from another invocation.
        created = True
        try:
            os.link(temporary, target)
        except FileExistsError:
            existing = decode_event(target)
            if existing.event_id != event.event_id:
                raise ValueError("Existing event identity mismatch")
            created = False
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        # Persist the directory entry itself, including after an interrupted first run.
        parent_fd = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return target, created
    finally:
        Path(temporary).unlink(missing_ok=True)


def decode_event(path: Path) -> BootEvent:
    if not EVENT_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
        raise ValueError("Invalid event file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("Event file too large")
    data = configparser.ConfigParser(interpolation=None)
    data.read_string(raw.decode("utf-8"))
    item = data["server_boot"]
    if item["format_version"] != "1" or path.name != f"boot-{item['event_id']}.txt":
        raise ValueError("Invalid event version or identity")
    boot = datetime.fromisoformat(item["boot_time_utc"].replace("Z", "+00:00"))
    recorded = datetime.fromisoformat(item["recorded_at_utc"].replace("Z", "+00:00"))
    uptime = float(item["uptime_seconds_at_record"])
    if boot.tzinfo is None or recorded.tzinfo is None or not math.isfinite(uptime) or uptime < 0:
        raise ValueError("Invalid event values")
    return BootEvent(item["event_id"], boot, recorded, uptime)


def report(directory: Path, days: int = 7, now: datetime | None = None) -> str:
    if not 1 <= days <= 366:
        raise ValueError("Days must be 1..366")
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    events: list[BootEvent] = []
    invalid = 0
    for path in directory.glob("boot-*.txt"):
        try:
            events.append(decode_event(path))
        except (OSError, ValueError, KeyError, configparser.Error):
            invalid += 1
    selected = sorted((event for event in events if start <= event.booted_at <= end), key=lambda event: event.booted_at)
    future = sum(event.booted_at > end or event.recorded_at > end for event in events)
    lines = [
        "DPMS: журнал обнаруженных загрузок сервера",
        f"Период UTC: {utc_text(start)} — {utc_text(end)}",
        f"Обнаруженных загрузок за период: {len(selected)}",
        f"Всего сохранённых событий: {len(events)}",
    ]
    if events:
        lines.append(f"Первая сохранённая запись UTC: {utc_text(min(event.recorded_at for event in events))}")
    else:
        lines.append("Нет записей. Журнал ещё не запускался или недоступен; это не доказательство отсутствия перезагрузок.")
    lines.extend([
        "Первый запуск записывает текущую загрузку, даже если сервер включён давно.",
        "История до установки и при отключённом обработчике неизвестна. Счётчик не равен числу аварий.",
        "Время по часам сервера; причина и длительность недоступности из этого журнала не определяются.",
        "",
    ])
    for event in selected:
        lines.append(
            f"{utc_text(event.booted_at)} | запись {utc_text(event.recorded_at)} | "
            f"uptime {event.uptime_seconds:.1f} с | {event.event_id} | причина неизвестна"
        )
    if invalid:
        lines.append(f"Внимание: повреждённых/неподдерживаемых файлов: {invalid}. Они не учтены.")
    if future:
        lines.append(f"Внимание: событий с будущими датами: {future}. Проверьте часы сервера.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="One text file per Linux host boot; no network or application dependency.")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--report", action="store_true", help="Read-only report; never creates a boot event")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    try:
        if args.report:
            print(report(args.directory, args.days), end="")
        else:
            path, created = write_event(args.directory, read_boot())
            print(f"{'recorded' if created else 'already_recorded'}: {path.name}")
        return 0
    except (OSError, ValueError, KeyError, IndexError, StopIteration, configparser.Error) as error:
        print(f"Boot journal failed ({type(error).__name__}); check service status, directory permissions and kernel counters.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
