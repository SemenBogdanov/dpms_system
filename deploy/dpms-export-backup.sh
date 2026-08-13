#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_PROJECT="${DPMS_COMPOSE_PROJECT:-deploy}"
COMPOSE_FILE="${DPMS_COMPOSE_FILE:-/opt/dpms/deploy/docker-compose.prod.yml}"
UPLOAD_DIR="${DPMS_UPLOAD_DIR:-/opt/dpms/uploads}"
STAGE_ROOT="${DPMS_BACKUP_STAGE_ROOT:-/opt/dpms-backups}"
DB_STAGE_ROOT="${DPMS_BACKUP_DB_STAGE_ROOT:-/dev/shm}"
LOCK_FILE="${DPMS_BACKUP_EXPORT_LOCK:-/opt/dpms-tools/offsite-export.lock}"
DEPLOY_LOCK_FILE="${DPMS_DEPLOY_LOCK_FILE:-/opt/dpms-tools/deploy.lock}"
POSTGRES_IMAGE="${DPMS_BACKUP_POSTGRES_IMAGE:-postgres:16-alpine}"
DB_HELPER="${DPMS_BACKUP_DB_HELPER:-$SCRIPT_DIR/dpms-backup-db-config.py}"
TEST_MODE="${DPMS_BACKUP_TEST_MODE:-0}"

log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

if [[ "$TEST_MODE" != "1" && "$(id -u)" != "0" ]]; then
  die "production export must run as root"
fi

mkdir -p "$STAGE_ROOT"
stage="$(mktemp -d "$STAGE_ROOT/.offsite-stage.XXXXXX")"
mkdir -p "$DB_STAGE_ROOT"
db_stage="$(mktemp -d "$DB_STAGE_ROOT/.dpms-db-stage.XXXXXX")"
backend_stopped=0

cleanup() {
  local exit_code=$?
  if [[ "$backend_stopped" == "1" ]]; then
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d backend >/dev/null 2>&1 || true
  fi
  rm -rf "$stage"
  rm -rf "$db_stage"
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

copy_uploads() {
  local source_dir="$1"
  [[ -d "$source_dir" ]] || die "uploads directory does not exist"
  mkdir -p "$stage/uploads"
  rsync -a --delete --safe-links --exclude='.DS_Store' "$source_dir/" "$stage/uploads/"
  if find "$stage/uploads" -type l -print -quit | grep -q .; then
    die "uploads snapshot contains a symbolic link"
  fi
}

if [[ "$TEST_MODE" == "1" ]]; then
  [[ -n "${DPMS_BACKUP_TEST_DATABASE_DUMP:-}" ]] || die "test database dump is required"
  [[ -f "$DPMS_BACKUP_TEST_DATABASE_DUMP" ]] || die "test database dump does not exist"
  [[ -n "${DPMS_BACKUP_TEST_UPLOAD_DIR:-}" ]] || die "test uploads directory is required"
  copy_uploads "$DPMS_BACKUP_TEST_UPLOAD_DIR"
  cp "$DPMS_BACKUP_TEST_DATABASE_DUMP" "$db_stage/database.dump"
  printf 'test\n' > "$db_stage/server-version.txt"
  printf 'test\n' > "$db_stage/client-version.txt"
  printf 'test\n' > "$db_stage/alembic-revision.txt"
  printf 'test\n' > "$db_stage/app-release.txt"
else
  command -v docker >/dev/null 2>&1 || die "docker is required"
  command -v rsync >/dev/null 2>&1 || die "rsync is required"
  command -v zstd >/dev/null 2>&1 || die "zstd is required"
  command -v flock >/dev/null 2>&1 || die "flock is required"
  command -v findmnt >/dev/null 2>&1 || die "findmnt is required"
  [[ -f "$COMPOSE_FILE" ]] || die "production compose file does not exist"
  [[ -x "$DB_HELPER" ]] || die "database config helper is not executable"

  [[ "$(findmnt -n -o FSTYPE --target "$DB_STAGE_ROOT")" == "tmpfs" ]] \
    || die "database staging directory must be on tmpfs"

  mkdir -p "$(dirname "$LOCK_FILE")" "$(dirname "$DEPLOY_LOCK_FILE")"
  exec 8>"$DEPLOY_LOCK_FILE"
  flock -n 8 || die "deploy or migration operation is running"
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another offsite export is running"

  backend_container="$(docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" ps -q backend)"
  [[ -n "$backend_container" ]] || die "backend container is not available"
  [[ "$(docker inspect --format '{{.State.Running}}' "$backend_container")" == "true" ]] \
    || die "backend container is not running"

  docker image inspect "$POSTGRES_IMAGE" >/dev/null 2>&1 || docker pull "$POSTGRES_IMAGE" >&2
  docker run --rm "$POSTGRES_IMAGE" pg_dump --version > "$db_stage/client-version.txt"
  docker inspect --format '{{.Config.Image}}' "$backend_container" > "$db_stage/app-release.txt"
  log "Preparing uploads snapshot while backend remains available."
  copy_uploads "$UPLOAD_DIR"

  log "Entering short write pause for final uploads sync and database dump."
  docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" stop -t 30 backend >&2
  backend_stopped=1
  copy_uploads "$UPLOAD_DIR"

  docker inspect --format '{{json .Config.Env}}' "$backend_container" \
    | "$DB_HELPER" "$db_stage"

  mapfile -t db_fields < <(
    python3 - "$db_stage/db-connection.json" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as source:
    data = json.load(source)
for field in ("host", "port", "database", "username", "sslmode"):
    value = str(data[field])
    if "\n" in value or "\r" in value:
        raise SystemExit("invalid database connection field")
    print(value)
PY
  )
  [[ "${#db_fields[@]}" == "5" ]] || die "database connection metadata is incomplete"

  pg_client=(docker run --rm --network "${DPMS_BACKUP_DOCKER_NETWORK:-host}"
    -v "$db_stage:/db-stage"
    -e PGPASSFILE=/db-stage/.pgpass
    -e PGCONNECT_TIMEOUT=15
    -e "PGSSLMODE=${db_fields[4]}" \
    "$POSTGRES_IMAGE")

  "${pg_client[@]}" psql --tuples-only --no-align \
    --host "${db_fields[0]}" --port "${db_fields[1]}" \
    --dbname "${db_fields[2]}" --username "${db_fields[3]}" \
    --command 'SHOW server_version' > "$db_stage/server-version.txt"
  "${pg_client[@]}" psql --tuples-only --no-align \
    --host "${db_fields[0]}" --port "${db_fields[1]}" \
    --dbname "${db_fields[2]}" --username "${db_fields[3]}" \
    --command 'SELECT version_num FROM alembic_version LIMIT 1' \
    > "$db_stage/alembic-revision.txt"
  "${pg_client[@]}" pg_dump --format=custom --no-owner --no-privileges \
      --host "${db_fields[0]}" --port "${db_fields[1]}" \
      --dbname "${db_fields[2]}" --username "${db_fields[3]}" \
      --file /db-stage/database.dump >&2

  rm -f "$db_stage/.pgpass" "$db_stage/db-connection.json"
  docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d backend >&2
  backend_stopped=0

  health_ready=0
  for _attempt in $(seq 1 60); do
    if curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null 2>&1; then
      health_ready=1
      break
    fi
    sleep 1
  done
  [[ "$health_ready" == "1" ]] || die "backend did not recover after backup snapshot"
  log "Backend is healthy; packaging continues without application downtime."
fi

[[ -s "$db_stage/database.dump" ]] || die "database dump is empty"

python3 - "$stage" "$db_stage" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

stage = Path(sys.argv[1])
db_stage = Path(sys.argv[2])
database_dump = db_stage / "database.dump"
uploads = stage / "uploads"

def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

upload_entries = []
for path in sorted(uploads.rglob("*")):
    if path.is_symlink():
        raise SystemExit("uploads snapshot contains a symbolic link")
    if path.is_file():
        upload_entries.append(
            {
                "path": path.relative_to(uploads).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_digest(path),
            }
        )

uploads_manifest = stage / "uploads-manifest.jsonl"
with uploads_manifest.open("w", encoding="utf-8") as target:
    for entry in upload_entries:
        target.write(json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n")

manifest = {
    "schema_version": 2,
    "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "app_release": (db_stage / "app-release.txt").read_text(encoding="utf-8").strip(),
    "database": {
        "format": "postgresql_custom",
        "file": "database.dump",
        "sha256": file_digest(database_dump),
        "size_bytes": database_dump.stat().st_size,
        "server_version": (db_stage / "server-version.txt").read_text(encoding="utf-8").strip(),
        "client_version": (db_stage / "client-version.txt").read_text(encoding="utf-8").strip(),
        "alembic_revision": (db_stage / "alembic-revision.txt").read_text(encoding="utf-8").strip(),
    },
    "uploads": {
        "directory": "uploads",
        "manifest_file": uploads_manifest.name,
        "manifest_sha256": file_digest(uploads_manifest),
        "file_count": len(upload_entries),
        "size_bytes": sum(entry["size_bytes"] for entry in upload_entries),
    },
}
(stage / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

log "Streaming compressed backup archive."
tar -C "$stage" -cf - manifest.json uploads-manifest.jsonl uploads \
  -C "$db_stage" database.dump \
  | zstd --quiet --threads=0 --long=27 -10
