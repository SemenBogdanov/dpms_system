#!/usr/bin/env bash
set -euo pipefail

DPMS_REPO_URL="${DPMS_REPO_URL:-https://github.com/SemenBogdanov/dpms_system.git}"
if [[ "$DPMS_REPO_URL" =~ ^https?://[^/@]+@ ]]; then
  printf 'ERROR: DPMS_REPO_URL must not contain credentials/userinfo\n' >&2
  exit 1
fi
DPMS_DEFAULT_REF="${DPMS_DEFAULT_REF:-main}"
DPMS_REPO_DIR="${DPMS_REPO_DIR:-/opt/dpms-git/repo}"
DPMS_RELEASES_DIR="${DPMS_RELEASES_DIR:-/opt/dpms-releases}"
DPMS_LIVE_ROOT="${DPMS_LIVE_ROOT:-/opt/dpms}"
DPMS_TOOLS_DIR="${DPMS_TOOLS_DIR:-/opt/dpms-tools}"
DPMS_BACKUPS_DIR="${DPMS_BACKUPS_DIR:-/opt/dpms-backups}"
DPMS_LOGS_DIR="${DPMS_LOGS_DIR:-/opt/dpms-tools/logs}"
DPMS_ENV_FILE="${DPMS_ENV_FILE:-/opt/dpms/deploy/.env.prod}"
DPMS_COMPOSE_FILE="${DPMS_COMPOSE_FILE:-/opt/dpms/deploy/docker-compose.prod.yml}"
DPMS_COMPOSE_PROJECT="${DPMS_COMPOSE_PROJECT:-deploy}"
DPMS_DOMAIN_PUNY="${DPMS_DOMAIN_PUNY:-xn--80ahdybnagjlbk.xn--p1ai}"
DPMS_LOCK_FILE="${DPMS_LOCK_FILE:-/opt/dpms-tools/deploy.lock}"
DPMS_NODE_IMAGE="${DPMS_NODE_IMAGE:-node:20-bookworm-slim}"
DPMS_MIN_FREE_MB="${DPMS_MIN_FREE_MB:-1024}"

usage() {
  cat <<'USAGE'
Usage: dpms-node.sh <command> [args]

Commands:
  bootstrap [ref]
      Install host dependencies, clone/update GitHub repo, prepare a release,
      and print approval sheet. It never promotes production.

  prepare [ref]
      Fetch GitHub, resolve ref to an exact commit, build release on this VPS,
      write manifest, and print approval sheet. Does not change production.

  update [ref]
      Alias for prepare.

  promote <release-id> --approval PHRASE [--allow-migrations --backup-id ID]
      Switch production to a prepared release. Migrations require both
      --allow-migrations and a non-empty --backup-id.

  rollback <backup-dir>
      Restore previous app/frontend/container state from an app backup.
      Does not rollback the external database.

  status
      Print production health and prepared release summary without secrets.

  healthcheck
      Check backend and nginx routes.
USAGE
}

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_root() {
  if [[ "$(id -u)" != 0 ]]; then
    die "run as root or through sudo"
  fi
}

with_lock() {
  mkdir -p "$(dirname "$DPMS_LOCK_FILE")"
  exec 9>"$DPMS_LOCK_FILE"
  flock -n 9 || die "another DPMS operation is running"
}

ensure_dirs() {
  mkdir -p "$DPMS_REPO_DIR" "$DPMS_RELEASES_DIR" "$DPMS_LIVE_ROOT" \
    "$DPMS_TOOLS_DIR" "$DPMS_BACKUPS_DIR" "$DPMS_LOGS_DIR"
  chmod 700 "$DPMS_BACKUPS_DIR" "$DPMS_LOGS_DIR" || true
}

install_host_dependencies() {
  require_root
  . /etc/os-release
  case "${ID}:${VERSION_ID}" in
    ubuntu:22.04|ubuntu:24.04) ;;
    *) die "supported baseline is Ubuntu Server 22.04 or 24.04 LTS; found ${PRETTY_NAME:-unknown}" ;;
  esac

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg git jq nginx rsync tar gzip lsof

  if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
      "$(dpkg --print-architecture)" "${VERSION_CODENAME}" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi

  systemctl enable --now docker >/dev/null 2>&1 || true
  systemctl enable --now nginx >/dev/null 2>&1 || true
}

ensure_repo() {
  require_root
  ensure_dirs
  if [[ -d "$DPMS_REPO_DIR/.git" ]]; then
    git -C "$DPMS_REPO_DIR" remote set-url origin "$DPMS_REPO_URL"
  elif [[ -e "$DPMS_REPO_DIR" ]]; then
    if [[ -n "$(find "$DPMS_REPO_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      die "repo dir exists but is not a git checkout: $DPMS_REPO_DIR"
    fi
    git clone "$DPMS_REPO_URL" "$DPMS_REPO_DIR"
  else
    mkdir -p "$(dirname "$DPMS_REPO_DIR")"
    git clone "$DPMS_REPO_URL" "$DPMS_REPO_DIR"
  fi
}

fetch_repo() {
  ensure_repo
  git -C "$DPMS_REPO_DIR" fetch --prune origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'
}

resolve_ref() {
  local ref="${1:-$DPMS_DEFAULT_REF}"
  case "$ref" in
    refs/pull/*|pull/*|refs/merge-requests/*) die "ref is not allowed for production prepare: $ref" ;;
  esac

  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]] && git -C "$DPMS_REPO_DIR" cat-file -e "$ref^{commit}" 2>/dev/null; then
    git -C "$DPMS_REPO_DIR" rev-parse "$ref^{commit}"
    return
  fi
  if git -C "$DPMS_REPO_DIR" rev-parse --verify --quiet "origin/$ref^{commit}" >/dev/null; then
    git -C "$DPMS_REPO_DIR" rev-parse "origin/$ref^{commit}"
    return
  fi
  if git -C "$DPMS_REPO_DIR" rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
    git -C "$DPMS_REPO_DIR" rev-parse "$ref^{commit}"
    return
  fi
  die "cannot resolve ref from GitHub checkout: $ref"
}

release_id_for_sha() {
  local sha="$1"
  printf 'dpms-%s\n' "${sha:0:12}"
}

release_dir_for_id() {
  printf '%s/%s\n' "$DPMS_RELEASES_DIR" "$1"
}

manifest_path() {
  printf '%s/manifest.json\n' "$1"
}

approval_phrase() {
  local release_id="$1"
  local sha="$2"
  printf 'promote:%s:%s\n' "$release_id" "${sha:0:12}"
}

docker_network_args() {
  local net="${DPMS_COMPOSE_PROJECT}_default"
  if docker network inspect "$net" >/dev/null 2>&1; then
    printf -- '--network %s' "$net"
  fi
}

forbidden_scan() {
  local dir="$1"
  find "$dir" \( \( -name '.env*' ! -name '.env.example' ! -name '.env.*.example' \) \
    -o -name '.git' -o -name '.claude' -o -iname '*secret*' -o -iname '*key*' \
    -o -iname '*token*' -o -iname '*credential*' -o -name 'node_modules' \
    -o -name '__pycache__' -o -name 'status.json' \) -print
}

validate_env_file() {
  [[ -f "$DPMS_ENV_FILE" ]] || die "production env file is missing: $DPMS_ENV_FILE"
  [[ -s "$DPMS_ENV_FILE" ]] || die "production env file is empty: $DPMS_ENV_FILE"
}

healthcheck() {
  local backend https_health https_root
  log "== DPMS healthcheck =="
  log "time_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ -f "$DPMS_COMPOSE_FILE" ]]; then
    docker compose -p "$DPMS_COMPOSE_PROJECT" -f "$DPMS_COMPOSE_FILE" ps || true
  fi
  backend=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || true)
  https_health=$(curl -k -sS -o /dev/null -w '%{http_code}' -H "Host: ${DPMS_DOMAIN_PUNY}" https://127.0.0.1/health || true)
  https_root=$(curl -k -sS -o /dev/null -w '%{http_code}' -H "Host: ${DPMS_DOMAIN_PUNY}" https://127.0.0.1/ || true)
  log "backend_health=$backend"
  log "https_health=$https_health"
  log "https_root=$https_root"
  if [[ "$backend" == 200 && "$https_health" == 200 && "$https_root" == 200 ]]; then
    log "healthcheck_ok=1"
    return 0
  fi
  log "healthcheck_failed=1"
  return 1
}

current_release_id() {
  if [[ -f "$DPMS_LIVE_ROOT/current-release" ]]; then
    sed -n '1p' "$DPMS_LIVE_ROOT/current-release"
  else
    echo unknown
  fi
}

free_mb_on_opt() {
  df -Pm /opt | awk 'NR==2 {print $4}'
}

build_frontend() {
  local release_dir="$1"
  docker run --rm \
    -v "$release_dir/frontend:/work" \
    -w /work \
    "$DPMS_NODE_IMAGE" \
    sh -lc 'npm ci && npm run build'
  rm -rf "$release_dir/frontend/node_modules"
}

build_backend_image() {
  local release_dir="$1"
  local image_tag="$2"
  docker build -f "$release_dir/deploy/Dockerfile.prod" -t "$image_tag" "$release_dir"
}

run_runtime_env_checks() {
  local image_tag="$1"
  docker run -i --rm --env-file "$DPMS_ENV_FILE" "$image_tag" python - <<'PY'
import os
import sys

database_url = os.getenv("DATABASE_URL", "")
secret = os.getenv("DPMS_SECRET_KEY", "")
cors = os.getenv("CORS_ORIGINS", "")
errors = []
if not database_url:
    errors.append("DATABASE_URL is missing")
if any(marker in database_url for marker in ("localhost", "127.0.0.1", "dpms_pass", "dpms_user")):
    errors.append("DATABASE_URL appears to use a development/default target")
if not secret or secret in {"dev-secret-key-change-me", "change-me", "changeme"}:
    errors.append("DPMS_SECRET_KEY appears to be default/empty")
if not cors:
    errors.append("CORS_ORIGINS is missing")
if cors.strip().startswith("*"):
    errors.append("CORS_ORIGINS must not be wildcard")
if errors:
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
PY
}

run_db_checks() {
  local image_tag="$1"
  local network_args=()
  local net_args
  net_args="$(docker_network_args)"
  if [[ -n "$net_args" ]]; then
    # shellcheck disable=SC2206
    network_args=($net_args)
  fi
  docker run -i --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" \
    python - <<'PY'
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
    await engine.dispose()

asyncio.run(main())
PY
  docker run --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" alembic current >/dev/null
  docker run --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" alembic heads >/dev/null
}

migration_delta() {
  local image_tag="$1"
  local current heads net_args
  local network_args=()
  net_args="$(docker_network_args)"
  if [[ -n "$net_args" ]]; then
    # shellcheck disable=SC2206
    network_args=($net_args)
  fi
  current=$(docker run --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" alembic current 2>/dev/null | awk '{print $1}' | sed '/^$/d' | sort -u | paste -sd, -)
  heads=$(docker run --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" alembic heads 2>/dev/null | awk '{print $1}' | sed '/^$/d' | sort -u | paste -sd, -)
  if [[ -z "$current" ]]; then
    echo "db_revision_unknown"
  elif [[ "$current" != "$heads" ]]; then
    echo "db_current=$current"
    echo "release_heads=$heads"
  fi
}

write_manifest() {
  local release_dir="$1" release_id="$2" sha="$3" ref="$4" image_tag="$5" migrations_file="$6"
  local migrations_json
  migrations_json=$(jq -R -s 'split("\n") | map(select(length > 0))' "$migrations_file")
  local frontend_hash npm_lock_hash image_id phrase current_release free_mb now
  frontend_hash=$(find "$release_dir/frontend/dist" -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
  npm_lock_hash=$(sha256sum "$release_dir/frontend/package-lock.json" | awk '{print $1}')
  image_id=$(docker image inspect "$image_tag" --format '{{.Id}}')
  phrase=$(approval_phrase "$release_id" "$sha")
  current_release=$(current_release_id)
  free_mb=$(free_mb_on_opt)
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  jq -n \
    --arg release_id "$release_id" \
    --arg repo_url "$DPMS_REPO_URL" \
    --arg ref "$ref" \
    --arg sha "$sha" \
    --arg short_sha "${sha:0:12}" \
    --arg prepared_at_utc "$now" \
    --arg release_dir "$release_dir" \
    --arg image_tag "$image_tag" \
    --arg image_id "$image_id" \
    --arg frontend_hash "$frontend_hash" \
    --arg npm_lock_hash "$npm_lock_hash" \
    --arg env_file_path "$DPMS_ENV_FILE" \
    --arg current_release "$current_release" \
    --arg approval_phrase "$phrase" \
    --argjson migrations "$migrations_json" \
    --arg free_mb "$free_mb" \
    '{release_id:$release_id, repo_url:$repo_url, ref:$ref, commit_sha:$sha,
      short_sha:$short_sha, prepared_at_utc:$prepared_at_utc, release_dir:$release_dir,
      image_tag:$image_tag, image_id:$image_id, frontend_hash:$frontend_hash,
      npm_lock_hash:$npm_lock_hash, env_file_path:$env_file_path,
      current_release_before_prepare:$current_release, approval_phrase:$approval_phrase,
      migrations:$migrations, migrations_count:($migrations|length), free_mb_on_opt:($free_mb|tonumber),
      status:"prepared"}' > "$(manifest_path "$release_dir")"
}

print_approval_sheet() {
  local release_dir="$1"
  local manifest
  manifest="$(manifest_path "$release_dir")"
  log "== DPMS approval sheet =="
  jq -r '
    "release_id=" + .release_id,
    "commit_sha=" + .commit_sha,
    "ref=" + .ref,
    "current_release_before_prepare=" + .current_release_before_prepare,
    "release_dir=" + .release_dir,
    "image_tag=" + .image_tag,
    "image_id=" + .image_id,
    "frontend_hash=" + .frontend_hash,
    "npm_lock_hash=" + .npm_lock_hash,
    "env_file_path=" + .env_file_path,
    "migrations_count=" + (.migrations_count|tostring),
    "migrations=" + ((.migrations // []) | join(",")),
    "db_backup_required=" + (if .migrations_count > 0 then "yes" else "no" end),
    "approval_phrase=" + .approval_phrase,
    "promote_command=/opt/dpms-tools/dpms-node.sh promote " + .release_id + " --approval " + .approval_phrase + (if .migrations_count > 0 then " --allow-migrations --backup-id <external-db-backup-id>" else "" end)
  ' "$manifest"
}

prepare_release() {
  require_root
  with_lock
  local ref="${1:-$DPMS_DEFAULT_REF}"
  ensure_dirs
  fetch_repo
  validate_env_file
  [[ "$(free_mb_on_opt)" -ge "$DPMS_MIN_FREE_MB" ]] || die "not enough free space on /opt"
  local sha release_id release_dir image_tag forbidden migrations_file
  sha="$(resolve_ref "$ref")"
  release_id="$(release_id_for_sha "$sha")"
  release_dir="$(release_dir_for_id "$release_id")"
  image_tag="dpms-backend:${sha:0:12}"
  if [[ -d "$release_dir" ]]; then
    if [[ -f "$(manifest_path "$release_dir")" && "$(jq -r '.commit_sha' "$(manifest_path "$release_dir")")" == "$sha" ]]; then
      local existing_image
      existing_image="$(jq -r '.image_tag' "$(manifest_path "$release_dir")")"
      [[ -f "$release_dir/frontend/dist/index.html" ]] || die "existing release is missing frontend/dist"
      docker image inspect "$existing_image" >/dev/null || die "existing release image is missing: $existing_image"
      print_approval_sheet "$release_dir"
      return 0
    fi
    if [[ ! -f "$(manifest_path "$release_dir")" ]]; then
      local failed_dir
      failed_dir="$release_dir.failed.$(date -u +%Y%m%dT%H%M%SZ)"
      mv "$release_dir" "$failed_dir"
      log "moved_incomplete_release=$failed_dir"
    else
      die "release dir already exists with a different manifest: $release_dir"
    fi
  fi
  rm -rf "$release_dir.tmp"
  mkdir -p "$release_dir.tmp"
  git -C "$DPMS_REPO_DIR" archive --format=tar --prefix="$release_id/" "$sha" | tar -xf - -C "$release_dir.tmp"
  mv "$release_dir.tmp/$release_id" "$release_dir"
  rmdir "$release_dir.tmp"
  find "$release_dir" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$release_dir" -type f -name '*.pyc' -delete
  forbidden="$(forbidden_scan "$release_dir")"
  [[ -z "$forbidden" ]] || { log "$forbidden"; die "release contains forbidden filenames"; }
  [[ -f "$release_dir/deploy/Dockerfile.prod" ]] || die "release missing deploy/Dockerfile.prod"
  [[ -f "$release_dir/deploy/docker-compose.prod.yml" ]] || die "release missing deploy/docker-compose.prod.yml"
  if grep -R -nE 'alembic[[:space:]]+upgrade|app\.seed|python[[:space:]]+-m[[:space:]]+app\.seed' "$release_dir/deploy/Dockerfile.prod" "$release_dir/deploy/docker-compose.prod.yml"; then
    die "production image/compose must not run migrations or seed at startup"
  fi
  build_frontend "$release_dir"
  build_backend_image "$release_dir" "$image_tag"
  run_runtime_env_checks "$image_tag"
  run_db_checks "$image_tag"
  nginx -t >/dev/null
  migrations_file="$release_dir/migrations.delta"
  migration_delta "$image_tag" > "$migrations_file"
  write_manifest "$release_dir" "$release_id" "$sha" "$ref" "$image_tag" "$migrations_file"
  print_approval_sheet "$release_dir"
}

copy_runtime_files_from_release() {
  local release_dir="$1"
  mkdir -p "$DPMS_LIVE_ROOT/backend" "$DPMS_LIVE_ROOT/deploy" "$DPMS_LIVE_ROOT/frontend/releases"
  rsync -a --delete "$release_dir/backend/" "$DPMS_LIVE_ROOT/backend/" --exclude='__pycache__/' --exclude='*.pyc'
  rsync -a "$release_dir/deploy/" "$DPMS_LIVE_ROOT/deploy/" --exclude='.env*'
  mkdir -p "$DPMS_LIVE_ROOT/frontend/releases/$(basename "$release_dir")"
  rm -rf "$DPMS_LIVE_ROOT/frontend/releases/$(basename "$release_dir")/dist"
  cp -a "$release_dir/frontend/dist" "$DPMS_LIVE_ROOT/frontend/releases/$(basename "$release_dir")/dist"
  ln -sfn "$DPMS_LIVE_ROOT/frontend/releases/$(basename "$release_dir")/dist" "$DPMS_LIVE_ROOT/frontend/dist"
}

install_nginx_config_from_release() {
  local release_dir="$1"
  [[ -f "$release_dir/deploy/nginx.conf" ]] || die "release missing deploy/nginx.conf"
  install -m 0644 "$release_dir/deploy/nginx.conf" /etc/nginx/sites-available/dpms
  ln -sfn /etc/nginx/sites-available/dpms /etc/nginx/sites-enabled/dpms
}

install_tool_from_release() {
  local release_dir="$1"
  [[ -f "$release_dir/deploy/dpms-node.sh" ]] || die "release missing deploy/dpms-node.sh"
  install -m 0755 "$release_dir/deploy/dpms-node.sh" "$DPMS_TOOLS_DIR/dpms-node.sh"
}

backup_app_state() {
  local release_id="$1"
  local backup_dir="$DPMS_BACKUPS_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$release_id"
  mkdir -p "$backup_dir"
  [[ -f "$DPMS_COMPOSE_FILE" ]] && cp "$DPMS_COMPOSE_FILE" "$backup_dir/docker-compose.prod.yml"
  cp /etc/nginx/sites-enabled/dpms "$backup_dir/nginx-dpms.conf" 2>/dev/null || true
  [[ -d "$DPMS_LIVE_ROOT/frontend/dist" || -L "$DPMS_LIVE_ROOT/frontend/dist" ]] && tar -czf "$backup_dir/frontend-dist.tar.gz" -C "$DPMS_LIVE_ROOT/frontend" dist
  [[ -d "$DPMS_LIVE_ROOT/backend" ]] && tar -czf "$backup_dir/backend-source.tar.gz" -C "$DPMS_LIVE_ROOT" backend --exclude='__pycache__' --exclude='*.pyc' --exclude='.env*' --exclude='*secret*' --exclude='*key*' --exclude='*token*' --exclude='*credential*'
  [[ -d "$DPMS_LIVE_ROOT/deploy" ]] && tar -czf "$backup_dir/deploy-source.tar.gz" -C "$DPMS_LIVE_ROOT" deploy --exclude='.env*' --exclude='*secret*' --exclude='*key*' --exclude='*token*' --exclude='*credential*'
  docker inspect deploy-backend-1 --format '{{.Image}}' > "$backup_dir/previous-backend-image-id.txt" 2>/dev/null || true
  current_release_id > "$backup_dir/current-release-before.txt"
  log "$backup_dir"
}

promote_release() {
  require_root
  with_lock
  local release_id="${1:-}"
  shift || true
  [[ -n "$release_id" ]] || die "usage: promote <release-id> --approval PHRASE [--allow-migrations --backup-id ID]"
  local allow_migrations=0 backup_id="" approval=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --allow-migrations) allow_migrations=1; shift ;;
      --backup-id) backup_id="${2:-}"; shift 2 ;;
      --approval) approval="${2:-}"; shift 2 ;;
      *) die "unknown promote arg: $1" ;;
    esac
  done
  local release_dir manifest expected_approval sha image_tag migrations_count backup_dir network_args=() net_args runtime_migration_delta
  release_dir="$(release_dir_for_id "$release_id")"
  manifest="$(manifest_path "$release_dir")"
  [[ -f "$manifest" ]] || die "manifest missing for release: $release_id"
  expected_approval="$(jq -r '.approval_phrase' "$manifest")"
  [[ "$approval" == "$expected_approval" ]] || die "approval phrase mismatch; run prepare and copy exact approval_phrase"
  sha="$(jq -r '.commit_sha' "$manifest")"
  image_tag="$(jq -r '.image_tag' "$manifest")"
  migrations_count="$(jq -r '.migrations_count' "$manifest")"
  [[ -d "$release_dir" ]] || die "release dir missing: $release_dir"
  [[ "$(resolve_ref "$sha")" == "$sha" ]] || die "repo cannot verify prepared commit sha"
  docker image inspect "$image_tag" >/dev/null || die "prepared image is missing: $image_tag"
  validate_env_file
  runtime_migration_delta="$(migration_delta "$image_tag")"
  if [[ -n "$runtime_migration_delta" ]]; then
    migrations_count=1
  fi
  if [[ "$migrations_count" -gt 0 ]]; then
    [[ "$allow_migrations" == 1 ]] || die "migrations detected; rerun with --allow-migrations and --backup-id after external DB backup"
    [[ -n "$backup_id" && "$backup_id" != "<external-db-backup-id>" ]] || die "--backup-id is required for migration releases"
  fi
  backup_dir="$(backup_app_state "$release_id")"
  log "app_backup_dir=$backup_dir"
  if [[ "$migrations_count" -gt 0 ]]; then
    log "external_db_backup_id=$backup_id"
    log "running approved Alembic migrations"
    net_args="$(docker_network_args)"
    if [[ -n "$net_args" ]]; then
      # shellcheck disable=SC2206
      network_args=($net_args)
    fi
    docker run --rm --env-file "$DPMS_ENV_FILE" "${network_args[@]}" "$image_tag" alembic upgrade head
  fi
  docker tag "$image_tag" deploy-backend:latest
  copy_runtime_files_from_release "$release_dir"
  install_nginx_config_from_release "$release_dir"
  install_tool_from_release "$release_dir"
  cd "$DPMS_LIVE_ROOT/deploy"
  DPMS_ENV_FILE="$DPMS_ENV_FILE" docker compose -p "$DPMS_COMPOSE_PROJECT" -f docker-compose.prod.yml up -d --no-build --force-recreate backend
  nginx -t
  systemctl reload nginx
  healthcheck
  printf '%s\n' "$release_id" > "$DPMS_LIVE_ROOT/current-release"
  jq --arg status promoted --arg promoted_at_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg backup_dir "$backup_dir" --arg backup_id "$backup_id" \
    '.status=$status | .promoted_at_utc=$promoted_at_utc | .app_backup_dir=$backup_dir | .external_db_backup_id=$backup_id' \
    "$manifest" > "$manifest.tmp" && mv "$manifest.tmp" "$manifest"
  log "promote_ok=1"
  log "release_id=$release_id"
  log "rollback_command=/opt/dpms-tools/dpms-node.sh rollback $backup_dir"
}

rollback_release() {
  require_root
  with_lock
  local backup_dir="${1:-}"
  [[ -n "$backup_dir" && -d "$backup_dir" ]] || die "usage: rollback <backup-dir>"
  if [[ -f "$backup_dir/previous-backend-image-id.txt" ]]; then
    local previous_image
    previous_image="$(tr -d '[:space:]' < "$backup_dir/previous-backend-image-id.txt")"
    if [[ -n "$previous_image" ]]; then
      docker image inspect "$previous_image" >/dev/null
      docker tag "$previous_image" deploy-backend:latest
    fi
  fi
  if [[ -f "$backup_dir/backend-source.tar.gz" ]]; then
    rm -rf "$DPMS_LIVE_ROOT/backend.rollback"
    mkdir -p "$DPMS_LIVE_ROOT/backend.rollback"
    tar -xzf "$backup_dir/backend-source.tar.gz" -C "$DPMS_LIVE_ROOT/backend.rollback"
    rm -rf "$DPMS_LIVE_ROOT/backend"
    mv "$DPMS_LIVE_ROOT/backend.rollback/backend" "$DPMS_LIVE_ROOT/backend"
    rm -rf "$DPMS_LIVE_ROOT/backend.rollback"
  fi
  if [[ -f "$backup_dir/deploy-source.tar.gz" ]]; then
    rm -rf "$DPMS_LIVE_ROOT/deploy.rollback"
    mkdir -p "$DPMS_LIVE_ROOT/deploy.rollback"
    tar -xzf "$backup_dir/deploy-source.tar.gz" -C "$DPMS_LIVE_ROOT/deploy.rollback"
    find "$DPMS_LIVE_ROOT/deploy.rollback/deploy" -maxdepth 1 -type f ! -name '.env*' -exec cp {} "$DPMS_LIVE_ROOT/deploy/" \;
    rm -rf "$DPMS_LIVE_ROOT/deploy.rollback"
  fi
  if [[ -f "$backup_dir/frontend-dist.tar.gz" ]]; then
    rm -rf "$DPMS_LIVE_ROOT/frontend/dist.rollback"
    mkdir -p "$DPMS_LIVE_ROOT/frontend/dist.rollback"
    tar -xzf "$backup_dir/frontend-dist.tar.gz" -C "$DPMS_LIVE_ROOT/frontend/dist.rollback"
    rm -rf "$DPMS_LIVE_ROOT/frontend/dist"
    mv "$DPMS_LIVE_ROOT/frontend/dist.rollback/dist" "$DPMS_LIVE_ROOT/frontend/dist"
    rm -rf "$DPMS_LIVE_ROOT/frontend/dist.rollback"
  fi
  if [[ -f "$backup_dir/nginx-dpms.conf" ]]; then
    cp "$backup_dir/nginx-dpms.conf" /etc/nginx/sites-available/dpms
    ln -sfn /etc/nginx/sites-available/dpms /etc/nginx/sites-enabled/dpms
  fi
  if [[ -f "$backup_dir/current-release-before.txt" ]]; then
    cp "$backup_dir/current-release-before.txt" "$DPMS_LIVE_ROOT/current-release"
  fi
  cd "$DPMS_LIVE_ROOT/deploy"
  DPMS_ENV_FILE="$DPMS_ENV_FILE" docker compose -p "$DPMS_COMPOSE_PROJECT" -f docker-compose.prod.yml up -d --no-build --force-recreate backend
  nginx -t
  systemctl reload nginx
  healthcheck
  log "rollback_ok=1"
  log "db_rollback_notice=external database was not changed by this rollback"
}

status_report() {
  log "== DPMS status =="
  log "time_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "repo_url=$DPMS_REPO_URL"
  if [[ -d "$DPMS_REPO_DIR/.git" ]]; then
    log "repo_head=$(git -C "$DPMS_REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
  else
    log "repo_head=missing"
  fi
  log "current_release=$(current_release_id)"
  log "env_file_present=$([[ -f "$DPMS_ENV_FILE" ]] && echo yes || echo no)"
  log "prepared_releases:"
  find "$DPMS_RELEASES_DIR" -maxdepth 2 -name manifest.json -print 2>/dev/null | sort | while read -r m; do
    jq -r '"- " + .release_id + " " + .status + " " + .short_sha + " migrations=" + (.migrations_count|tostring)' "$m"
  done
  healthcheck || true
}

bootstrap() {
  require_root
  local ref="$DPMS_DEFAULT_REF"
  if [[ $# -gt 0 && "$1" != --* ]]; then
    ref="$1"
    shift
  fi
  if [[ $# -gt 0 ]]; then
    die "bootstrap only prepares a release; use promote separately after approval"
  fi
  install_host_dependencies
  ensure_repo
  fetch_repo
  local sha release_id release_dir
  sha="$(resolve_ref "$ref")"
  release_id="$(release_id_for_sha "$sha")"
  release_dir="$(release_dir_for_id "$release_id")"
  if [[ ! -d "$release_dir" ]]; then
    rm -rf "$release_dir.bootstrap.tmp"
    mkdir -p "$release_dir.bootstrap.tmp"
    git -C "$DPMS_REPO_DIR" archive --format=tar --prefix="$release_id/" "$sha" | tar -xf - -C "$release_dir.bootstrap.tmp"
    mkdir -p "$release_dir"
    cp -a "$release_dir.bootstrap.tmp/$release_id/deploy/dpms-node.sh" "$DPMS_TOOLS_DIR/dpms-node.sh"
    rm -rf "$release_dir.bootstrap.tmp"
  fi
  prepare_release "$sha"
}

main() {
  if [[ "${1:-}" == "--" ]]; then
    shift
  fi
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    bootstrap) bootstrap "$@" ;;
    prepare) prepare_release "${1:-$DPMS_DEFAULT_REF}" ;;
    update) prepare_release "${1:-$DPMS_DEFAULT_REF}" ;;
    promote) promote_release "$@" ;;
    rollback) rollback_release "$@" ;;
    status) status_report ;;
    healthcheck) healthcheck ;;
    -h|--help|help|'') usage ;;
    *) die "unknown command: $cmd" ;;
  esac
}

main "$@"
