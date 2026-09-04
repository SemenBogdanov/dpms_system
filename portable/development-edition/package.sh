#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

VERSION=$(cat VERSION)
PACKAGE_NAME="dpms-development-edition-$VERSION"
ARCHIVE_DIR="$ROOT_DIR/archives"
ARCHIVE_PATH="$ARCHIVE_DIR/$PACKAGE_NAME-source.tar.gz"
STAGE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/dpms-development.XXXXXX")
STAGE="$STAGE_ROOT/$PACKAGE_NAME"
trap 'rm -rf "$STAGE_ROOT"' EXIT INT TERM

./verify.sh
npm --prefix frontend run build
mkdir -p "$STAGE" "$ARCHIVE_DIR"

COPYFILE_DISABLE=1 tar \
  --exclude='**/.DS_Store' \
  --exclude='**/__pycache__' \
  --exclude='**/*.pyc' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='frontend/test-results' \
  --exclude='frontend/*.tsbuildinfo' \
  --exclude='runtime/data/*' \
  --exclude='archives/*' \
  --exclude='images/*' \
  -cf - \
  .dockerignore .gitignore Dockerfile README.md VERSION MANIFEST.json requirements.txt \
  docker-compose.yml install-ubuntu.sh start.sh stop.sh status.sh backup.sh restore.sh verify.sh package.sh build-image-archive.sh \
  scripts app data tools/validate_catalog.py tests frontend \
  | tar -xf - -C "$STAGE"

mkdir -p "$STAGE/runtime/data" "$STAGE/archives" "$STAGE/images"
: > "$STAGE/runtime/data/.gitkeep"
: > "$STAGE/archives/.gitkeep"
: > "$STAGE/images/.gitkeep"

python3 - "$STAGE" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
lines = []
for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "CHECKSUMS.sha256"):
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root)}")
(root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

rm -f "$ARCHIVE_PATH" "$ARCHIVE_PATH.sha256"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE_PATH" -C "$STAGE_ROOT" "$PACKAGE_NAME"
python3 - "$ARCHIVE_PATH" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.with_name(path.name + ".sha256").write_text(
    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
    encoding="utf-8",
)
PY

printf '%s\n' "Архив создан: $ARCHIVE_PATH"

for ARCH in amd64 arm64; do
  IMAGE_NAME="dpms-development-edition-$ARCH.tar.gz"
  if [ ! -f "$ROOT_DIR/images/$IMAGE_NAME" ]; then
    continue
  fi
  BUNDLE_STAGE="$STAGE_ROOT/$PACKAGE_NAME-$ARCH"
  BUNDLE_PATH="$ARCHIVE_DIR/$PACKAGE_NAME-ubuntu-$ARCH-usb.tar.gz"
  cp -R "$STAGE" "$BUNDLE_STAGE"
  mkdir -p "$BUNDLE_STAGE/images"
  cp "$ROOT_DIR/images/$IMAGE_NAME" "$BUNDLE_STAGE/images/$IMAGE_NAME"
  if [ -f "$ROOT_DIR/images/$IMAGE_NAME.sha256" ]; then
    cp "$ROOT_DIR/images/$IMAGE_NAME.sha256" "$BUNDLE_STAGE/images/$IMAGE_NAME.sha256"
  fi
  python3 - "$BUNDLE_STAGE" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
lines = []
for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "CHECKSUMS.sha256"):
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root)}")
(root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  rm -f "$BUNDLE_PATH" "$BUNDLE_PATH.sha256"
  COPYFILE_DISABLE=1 tar -czf "$BUNDLE_PATH" -C "$STAGE_ROOT" "$(basename "$BUNDLE_STAGE")"
  python3 - "$BUNDLE_PATH" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.with_name(path.name + ".sha256").write_text(
    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
    encoding="utf-8",
)
PY
  printf '%s\n' "USB-архив создан: $BUNDLE_PATH"
done
