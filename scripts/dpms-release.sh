#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/dpms-release.sh [--deploy] [--allow-migrations]

Default mode builds a release artifact from committed git files, uploads it to the VPS,
stages it, and runs preflight. It does not deploy to production unless --deploy is passed.

Environment:
  DPMS_VPS_HOST             SSH target, default: dpms-vps
  DPMS_SSH_CONTROL_PATH     SSH ControlMaster path, default: ~/.ssh/controlmasters/dpms-vps
  DPMS_REMOTE_INCOMING      Remote incoming dir, default: /opt/dpms-releases/incoming
USAGE
}

deploy=0
allow_migrations=0
for arg in "$@"; do
  case "$arg" in
    --deploy) deploy=1 ;;
    --allow-migrations) allow_migrations=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg"; usage; exit 2 ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vps_host="${DPMS_VPS_HOST:-dpms-vps}"
control_path="${DPMS_SSH_CONTROL_PATH:-$HOME/.ssh/controlmasters/dpms-vps}"
remote_incoming="${DPMS_REMOTE_INCOMING:-/opt/dpms-releases/incoming}"

if [[ ! -S "$control_path" ]]; then
  echo "missing SSH ControlMaster socket: $control_path"
  echo "Create it first: ssh -M -S $control_path -o ControlPersist=4h -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -fN $vps_host"
  exit 2
fi

dirty="$(git -C "$repo_root" status --porcelain)"
if [[ -n "$dirty" ]]; then
  echo "working tree is dirty; commit or stash changes before creating a production release"
  echo "$dirty"
  exit 2
fi

git_sha="$(git -C "$repo_root" rev-parse HEAD)"
git_short="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
built_at="$(date -u +%Y%m%dT%H%M%SZ)"
release_id="dpms-${built_at}-${git_short}"
release_parent="${TMPDIR:-/tmp}/dpms-release"
release_dir="$release_parent/$release_id"
tar_path="$release_parent/$release_id.tar.gz"
sha_path="$tar_path.sha256"

mkdir -p "$release_parent"
rm -rf "$release_dir" "$tar_path" "$sha_path"

echo "== Build frontend =="
npm --prefix "$repo_root/frontend" run build

echo "== Prepare release: $release_id =="
git -C "$repo_root" archive --format=tar --prefix="$release_id/" HEAD | tar -xf - -C "$release_parent"
rm -rf "$release_dir/frontend/dist"
mkdir -p "$release_dir/frontend"
cp -a "$repo_root/frontend/dist" "$release_dir/frontend/dist"
find "$release_dir" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$release_dir" -type f -name "*.pyc" -delete

forbidden="$(find "$release_dir" \( \( -name '.env*' ! -name '.env.example' ! -name '.env.*.example' \) -o -name '.git' -o -name '.claude' -o -iname '*secret*' -o -iname '*key*' -o -iname '*token*' -o -iname '*credential*' -o -name 'node_modules' -o -name '__pycache__' -o -name 'status.json' \) -print)"
if [[ -n "$forbidden" ]]; then
  echo "release contains forbidden filenames:"
  echo "$forbidden"
  exit 2
fi

test -f "$release_dir/deploy/docker-compose.prod.yml"
test -f "$release_dir/deploy/Dockerfile.prod"
test -f "$release_dir/frontend/dist/index.html"
test ! -e "$release_dir/deploy/.env.prod"

cat > "$release_dir/VERSION" <<VERSION
release_id=$release_id
git_sha=$git_sha
git_short_sha=$git_short
built_at_utc=$built_at
source_repo=https://github.com/semenbogdanov/dpms_system.git
frontend_built=local
artifact_source=git_archive_head_plus_frontend_dist
VERSION

(
  cd "$release_parent"
  COPYFILE_DISABLE=1 tar --no-xattrs -czf "$tar_path" "$release_id"
)
sha256="$(shasum -a 256 "$tar_path" | awk '{print $1}')"
printf '%s  %s\n' "$sha256" "$(basename "$tar_path")" > "$sha_path"

echo "release_tar=$tar_path"
echo "release_sha256=$sha256"

echo "== Upload =="
ssh -o "ControlPath=$control_path" "$vps_host" "mkdir -p '$remote_incoming'"
scp -o "ControlPath=$control_path" "$tar_path" "$sha_path" "$vps_host:$remote_incoming/"

remote_tar="$remote_incoming/$(basename "$tar_path")"
remote_release="/opt/dpms-releases/$release_id"

echo "== Stage =="
ssh -o "ControlPath=$control_path" "$vps_host" "/opt/dpms-tools/dpms-stage-release.sh '$remote_tar' '$sha256'"

echo "== Preflight =="
ssh -o "ControlPath=$control_path" "$vps_host" "/opt/dpms-tools/dpms-preflight.sh '$remote_release'"

if [[ "$deploy" == 1 ]]; then
  extra=""
  if [[ "$allow_migrations" == 1 ]]; then
    extra="--allow-migrations"
  fi
  echo "== Deploy =="
  ssh -o "ControlPath=$control_path" "$vps_host" "/opt/dpms-tools/dpms-deploy-release.sh '$remote_release' $extra"
else
  echo "staged_release=$remote_release"
  echo "deploy_not_run=1"
  echo "To deploy after approval: /opt/dpms-tools/dpms-deploy-release.sh '$remote_release' [--allow-migrations]"
fi
