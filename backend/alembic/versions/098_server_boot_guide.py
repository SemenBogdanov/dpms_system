"""Publish a portable snapshot of the host boot recorder and recovery guide.

Revision ID: 098_server_boot_guide
Revises: 097_server_boot_events
"""
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite


revision = "098_server_boot_guide"
down_revision = "097_server_boot_events"
branch_labels = None
depends_on = None

# Immutable release snapshot; future changes belong to a new migration.
ARTICLE = {
    "id": UUID("ace1a68a-8815-496b-8374-166bcaf066c1"),
    "slug": "server-boot-journal-recovery",
    "title": "Перенос DPMS: журнал загрузок VPS",
    "summary": "Как восстановить запись загрузок VPS на новом сервере: полный код, systemd-служба, перенос истории и проверка импорта в БД.",
    "section": "general",
    "status": "published",
    "sort_order": 110,
    "body": r'''Обновлено: 25.09.2026.

Журнал фиксирует загрузки Linux VPS, переносит события в PostgreSQL DPMS и показывает их в «Админ → Загрузки сервера». Эта статья содержит полные листинги для восстановления на другом сервере.

## Где сохранена реализация

Проверенная версия: Git commit 5c3f9b563ace888ba07d5ecd4ea402a947b0f15d. Исходники находятся в deploy/stability/record_boot.py и deploy/stability/dpms-boot-record.service. Импорт в БД: backend/app/workers/server_boot.py и backend/app/services/server_boot.py; запуск — deploy/docker-compose.prod.yml. Статья — снимок этой версии, не замена будущим проверенным обновлениям.

## Как это работает

1. При загрузке VPS systemd запускает одноразовый recorder на самом Linux host после подготовки локальной файловой системы, без ожидания сети или БД. Порядок относительно запуска Docker и приложения не задан.
2. Recorder записывает один UTF-8 файл boot-<event_id>.txt в /var/lib/dpms-boot-events/. Event ID получен из kernel boot ID. Повторный запуск не изменяет первую запись и не создаёт дубль.
3. Отдельный server-boot-worker читает каталог только на чтение при старте и затем примерно раз в минуту. Запись и состояние синхронизации сохраняются в БД.
4. Администратор открывает «Админ → Загрузки сервера». Период «Всё время» показывает также старую загрузку, записанную при первой установке.

Restart backend, контейнера или Docker daemon — не новая загрузка VPS. Скрипт не измеряет HTTP-доступность, CPU/RAM и длительность простоя. Причина перезагрузки неизвестна. Нулевая недельная статистика не доказывает отсутствие аварий; история до установки не восстанавливается. Время в файлах — UTC по часам ОС, в админке — МСК.

## Установка на новом VPS

Нужны Linux с systemd, Python 3.10 или новее и административный доступ. На macOS или внутри контейнера проверять загрузку production VPS нельзя.

1. Подготовьте проверенный checkout DPMS и резервные копии. При обновлении существующей установки сначала сохраните прежний скрипт и unit.
2. Из корня checkout выполните команды ниже. Пустой каталог журнала создаст systemd с правами0750; файлы создаются с правами0640.
3. Для восстановления без checkout сохраните два полных листинга ниже в указанные пути. Не удаляйте отступы Python. Сверьте контрольные суммы.
4. При обычной установке reboot не нужен. Реальную перезагрузку production согласуют отдельно.

```bash
sudo install -d -m 0755 /opt/dpms-monitor
sudo install -m 0644 deploy/stability/record_boot.py /opt/dpms-monitor/record_boot.py
sudo install -m 0644 deploy/stability/dpms-boot-record.service /etc/systemd/system/dpms-boot-record.service
sudo systemd-analyze verify /etc/systemd/system/dpms-boot-record.service
sudo systemctl daemon-reload
sudo systemctl enable --now dpms-boot-record.service
```

## Проверка без перезагрузки

```bash
sudo systemctl is-enabled dpms-boot-record.service
sudo systemctl status dpms-boot-record.service --no-pager
sudo journalctl -u dpms-boot-record.service -n 20 --no-pager
sudo python3 /opt/dpms-monitor/record_boot.py --report --days 7
sudo systemctl restart dpms-boot-record.service
sudo journalctl -u dpms-boot-record.service -n 5 --no-pager
```

Ожидается enabled и active (exited): это успешное завершение одноразовой службы. Повторный запуск сообщает already_recorded; количество записей не увеличивается. При первом запуске recorded означает сохранение текущей загрузки, даже если она произошла задолго до установки.

## Подключение импорта в БД

Установите app release со схемой не ниже097_server_boot_events через штатный release protocol с backup. Один recorder работает без Docker/БД, но не создаёт панель админки сам по себе. В production Compose уже предусмотрен server-boot-worker: отдельный сервис без внешнего порта, read-only root и read-only bind /var/lib/dpms-boot-events.

- SERVER_BOOT_EVENTS_DIR у worker: /var/lib/dpms-boot-events.
- SERVER_BOOT_POLL_SECONDS у worker: 60.
- SERVER_BOOT_SOURCE_ID у backend и worker должен совпадать. В штатном Compose это primary-vps, явное значение в environment обоих сервисов, а не только в env-файле.
- create_host_path: false блокирует запуск с отсутствующим host-каталогом. Сначала установите recorder.
- После переноса одного действующего контура source_id можно сохранить. При намеренном запуске независимого второго контура назначьте ему отдельный стабильный source_id в обоих сервисах.
- Не копируйте deploy/stability/fixtures в production: это синтетические события для тестов.

```bash
sudo docker compose -p deploy -f /opt/dpms/deploy/docker-compose.prod.yml ps server-boot-worker
sudo docker compose -p deploy -f /opt/dpms/deploy/docker-compose.prod.yml exec -T server-boot-worker python -m app.workers.server_boot --healthcheck
```

Healthcheck без вывода с exit0 означает работоспособность импортера. Повреждённый отдельный файл может давать предупреждение в админке при работающем worker: проверяйте также состояние, ошибки и время последней синхронизации на панели. «Устарело» — отсутствие свежей проверки более180секунд либо время проверки более5секунд в будущем. После восстановления БД импорт повторится; исходные файлы не удаляются.

## Что обязательно перенести

1. Резервную копию БД DPMS, включая server_boot_events, server_boot_import_status и knowledge_articles. Так сохраняются история загрузок и эта статья.
2. Каталог /var/lib/dpms-boot-events/ отдельно от БД и uploads, с правами и владельцем. Стандартный экспорт БД/uploads не включает этот host-каталог.
3. Скрипт /opt/dpms-monitor/record_boot.py и unit /etc/systemd/system/dpms-boot-record.service либо их проверенную копию из Git.
4. Код приложения, Compose и необходимые runtime-настройки — по обычному плану переноса DPMS. Пароли и другие секреты не являются частью этой статьи.

Архив host-журнала создайте отдельно в существующем защищённом каталоге резервных копий, вне репозитория. Перед восстановлением проверьте состав архива, не перезаписывайте существующий журнал без проверки конфликтов. На новом host сначала восстановите БД и старые события; затем включите recorder и worker. Новая загрузка получит новый event_id, прежние события сохранятся.

Не запускайте два активных экземпляра DPMS с одной рабочей БД без отдельного плана переключения. Перенос не выполняется автоматически этими командами.

## Отключение

```bash
sudo systemctl disable --now dpms-boot-record.service
```

Это останавливает будущую запись загрузок, но не удаляет файлы или историю БД. Уже импортированные события останутся видны. Отключение recorder не равно отключению worker. При штатном откате приложения к версии без worker release manager отключает его restart policy и останавливает контейнер.

## Контрольные суммы листингов

Команда для проверки установленных файлов:

```bash
sha256sum /opt/dpms-monitor/record_boot.py /etc/systemd/system/dpms-boot-record.service
```

Ожидаемые SHA-256 для приведённой версии:

```text
2347b2839f414bb1fb53c85554331b8e866d12ba37020087cee581bf90a863f0  record_boot.py
b248c4513b97fccb026703a55c0ee34171990db4f0c543a2f30cc590bcfa9d6c  dpms-boot-record.service
```

## Полный код /opt/dpms-monitor/record_boot.py

```python
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
```

## Полный код /etc/systemd/system/dpms-boot-record.service

```ini
[Unit]
Description=DPMS durable host boot record
After=local-fs.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/dpms-monitor/record_boot.py
RemainAfterExit=yes
Restart=on-failure
RestartSec=5s
TimeoutStartSec=10s
StateDirectory=dpms-boot-events
StateDirectoryMode=0750
UMask=0027
NoNewPrivileges=yes
PrivateTmp=yes
PrivateNetwork=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
```
''',
}


def _article_table() -> sa.TableClause:
    return sa.table(
        "knowledge_articles",
        sa.column("id", sa.Uuid()),
        sa.column("slug", sa.String(160)),
        sa.column("title", sa.String(255)),
        sa.column("summary", sa.String(500)),
        sa.column("section", sa.String(80)),
        sa.column("body", sa.Text()),
        sa.column("status", postgresql.ENUM("draft", "published", name="knowledgestatus", create_type=False)),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_by_id", sa.Uuid()),
        sa.column("updated_by_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    bind = op.get_bind()
    insert = sqlite.insert if bind.dialect.name == "sqlite" else postgresql.insert
    # A pre-existing slug or ID may belong to a user: never overwrite it.
    bind.execute(insert(_article_table()).values(
        **ARTICLE,
        created_by_id=None,
        updated_by_id=None,
        created_at=sa.func.current_timestamp(),
        updated_at=sa.func.current_timestamp(),
        published_at=sa.func.current_timestamp(),
    ).on_conflict_do_nothing())


def downgrade() -> None:
    raise RuntimeError("Use a reviewed forward migration; preserve the recovery guide and user edits.")
