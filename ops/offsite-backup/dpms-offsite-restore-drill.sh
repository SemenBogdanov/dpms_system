#!/usr/bin/env bash
set -euo pipefail

umask 077

CONFIG_FILE="${DPMS_BACKUP_CONFIG:-/etc/dpms-offsite-backup.conf}"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

AGE_IDENTITY="${DPMS_BACKUP_AGE_IDENTITY:-}"
AGE_BIN="${DPMS_BACKUP_AGE_BIN:-age}"
POSTGRES_IMAGE="${DPMS_RESTORE_POSTGRES_IMAGE:-postgres:16-alpine}"
backup_file="${1:-}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ -n "$backup_file" && -f "$backup_file" && ! -L "$backup_file" ]] \
  || die "usage: dpms-offsite-restore-drill.sh BACKUP_FILE"
[[ -f "$backup_file.sha256" ]] || die "backup checksum sidecar is missing"
[[ -n "$AGE_IDENTITY" && -f "$AGE_IDENTITY" && ! -L "$AGE_IDENTITY" ]] \
  || die "age identity file is unavailable"
command -v "$AGE_BIN" >/dev/null 2>&1 || die "age is required"
command -v zstd >/dev/null 2>&1 || die "zstd is required"
command -v docker >/dev/null 2>&1 || die "docker is required"

(
  cd "$(dirname "$backup_file")"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$(basename "$backup_file.sha256")" >/dev/null
  else
    shasum -a 256 -c "$(basename "$backup_file.sha256")" >/dev/null
  fi
)

workdir="$(mktemp -d)"
container="dpms-restore-drill-$(date -u +%Y%m%d%H%M%S)-$$"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT INT TERM

"$AGE_BIN" --decrypt --identity "$AGE_IDENTITY" "$backup_file" \
  | zstd --quiet --decompress --stdout \
  | tar -xf - -C "$workdir"

python3 - "$workdir" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("schema_version") != 2:
    raise SystemExit("unsupported backup manifest")

dump = root / manifest["database"]["file"]
digest = hashlib.sha256()
with dump.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != manifest["database"]["sha256"]:
    raise SystemExit("database dump checksum mismatch")

uploads_meta = manifest["uploads"]
uploads = root / uploads_meta["directory"]
uploads_manifest = root / uploads_meta["manifest_file"]
if digest_file := hashlib.sha256(uploads_manifest.read_bytes()).hexdigest():
    if digest_file != uploads_meta["manifest_sha256"]:
        raise SystemExit("uploads manifest checksum mismatch")

expected = {}
for raw_line in uploads_manifest.read_text(encoding="utf-8").splitlines():
    entry = json.loads(raw_line)
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in entry["path"]:
        raise SystemExit("unsafe path in uploads manifest")
    if entry["path"] in expected:
        raise SystemExit("duplicate path in uploads manifest")
    expected[entry["path"]] = entry

actual = {}
for path in uploads.rglob("*"):
    if path.is_symlink():
        raise SystemExit("restored uploads contain a symbolic link")
    if path.is_file():
        relative = path.relative_to(uploads).as_posix()
        actual[relative] = {
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
if set(actual) != set(expected):
    raise SystemExit("uploads inventory mismatch")
for relative, entry in expected.items():
    if actual[relative] != {"size_bytes": entry["size_bytes"], "sha256": entry["sha256"]}:
        raise SystemExit(f"upload checksum mismatch: {relative}")
if len(actual) != uploads_meta["file_count"]:
    raise SystemExit("uploads file count mismatch")
if sum(item["size_bytes"] for item in actual.values()) != uploads_meta["size_bytes"]:
    raise SystemExit("uploads size mismatch")
PY

docker run -d --name "$container" \
  -e POSTGRES_DB=dpms_restore \
  -e POSTGRES_USER=dpms_restore \
  -e POSTGRES_PASSWORD=restore-drill-only \
  "$POSTGRES_IMAGE" >/dev/null

ready=0
for _attempt in $(seq 1 60); do
  if docker exec "$container" pg_isready -U dpms_restore -d dpms_restore >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" == "1" ]] || die "disposable PostgreSQL did not become ready"

docker cp "$workdir/database.dump" "$container:/tmp/database.dump"
docker exec "$container" pg_restore --list /tmp/database.dump >/dev/null
docker exec "$container" pg_restore --exit-on-error --no-owner --no-privileges \
  -U dpms_restore -d dpms_restore /tmp/database.dump >/dev/null

revision="$(docker exec "$container" psql -At -U dpms_restore -d dpms_restore \
  -c 'SELECT version_num FROM alembic_version LIMIT 1')"
table_count="$(docker exec "$container" psql -At -U dpms_restore -d dpms_restore \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
[[ -n "$revision" ]] || die "restored database has no Alembic revision"
[[ "$table_count" =~ ^[0-9]+$ && "$table_count" -gt 0 ]] || die "restored database has no tables"

docker exec "$container" psql -At -U dpms_restore -d dpms_restore -c "
  SELECT stored_filename FROM task_attachments
  UNION
  SELECT stored_filename FROM quick_note_attachments
  UNION
  SELECT stored_filename FROM personal_task_artifact_versions WHERE source_kind = 'file'
  ORDER BY 1
" > "$workdir/db-file-references.txt"

upload_reference_count="$(python3 - "$workdir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
file_paths = {
    json.loads(line)["path"]
    for line in (root / manifest["uploads"]["manifest_file"]).read_text(encoding="utf-8").splitlines()
    if line
}
references = {
    line
    for line in (root / "db-file-references.txt").read_text(encoding="utf-8").splitlines()
    if line
}
missing = sorted(references - file_paths)
orphans = sorted(file_paths - references)
if missing:
    raise SystemExit(f"database references missing uploads: {len(missing)}")
if orphans:
    raise SystemExit(f"uploads without database references: {len(orphans)}")
print(len(references))
PY
)"

manifest_revision="$(python3 - "$workdir/manifest.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["database"]["alembic_revision"])
PY
)"
if [[ "$manifest_revision" != "test" && "$revision" != "$manifest_revision" ]]; then
  die "restored Alembic revision differs from the backup manifest"
fi

printf 'restore_drill=ok\n'
printf 'alembic_revision=%s\n' "$revision"
printf 'public_tables=%s\n' "$table_count"
printf 'upload_references=%s\n' "$upload_reference_count"
