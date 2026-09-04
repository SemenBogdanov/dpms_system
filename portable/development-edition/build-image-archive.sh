#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

ARCH=${1:-amd64}
case "$ARCH" in
  amd64|arm64) ;;
  *)
    printf '%s\n' "Поддерживаемые архитектуры: amd64, arm64" >&2
    exit 1
    ;;
esac

if ! docker info >/dev/null 2>&1; then
  printf '%s\n' "Docker недоступен" >&2
  exit 1
fi

mkdir -p images
VERSION=$(cat VERSION)
OUTPUT="$ROOT_DIR/images/dpms-development-edition-$ARCH.tar"
ARCHIVE="$OUTPUT.gz"
rm -f "$OUTPUT" "$ARCHIVE" "$ARCHIVE.sha256"

docker buildx build \
  --platform "linux/$ARCH" \
  --tag "dpms-development-edition:$VERSION" \
  --output "type=docker,dest=$OUTPUT" \
  .
gzip -9 "$OUTPUT"

python3 - "$ARCHIVE" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.with_name(path.name + ".sha256").write_text(
    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
    encoding="utf-8",
)
PY

printf '%s\n' "Готовый образ: $ARCHIVE"
