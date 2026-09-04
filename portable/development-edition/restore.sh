#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  printf '%s\n' "Использование: ./restore.sh /путь/к/backup.sqlite3" >&2
  exit 1
fi

DPMS_PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DPMS_PACKAGE_ROOT
. "$DPMS_PACKAGE_ROOT/scripts/common.sh"

SOURCE=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
if [ ! -f "$SOURCE" ]; then
  printf '%s\n' "Файл резервной копии не найден: $SOURCE" >&2
  exit 1
fi

python3 - "$SOURCE" <<'PY'
import sqlite3
import sys

with sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True) as database:
    result = database.execute("PRAGMA integrity_check").fetchone()
if not result or result[0] != "ok":
    raise SystemExit("Резервная копия SQLite повреждена")
PY

compose down
stamp=$(date -u +%Y%m%dT%H%M%SZ)
if [ -f runtime/data/development.sqlite3 ]; then
  cp runtime/data/development.sqlite3 "runtime/data/development-before-restore-$stamp.sqlite3"
fi
cp "$SOURCE" runtime/data/development.sqlite3
rm -f runtime/data/development.sqlite3-wal runtime/data/development.sqlite3-shm
compose up -d

attempt=0
while [ "$attempt" -lt 60 ]; do
  if healthcheck; then
    printf '%s\n' "База восстановлена, система готова: http://localhost:${DPMS_PORT:-8787}"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

compose logs --tail=80 app
printf '%s\n' "База восстановлена, но система не прошла проверку готовности." >&2
exit 1
