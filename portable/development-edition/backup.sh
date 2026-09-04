#!/usr/bin/env sh
set -eu

DPMS_PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DPMS_PACKAGE_ROOT
. "$DPMS_PACKAGE_ROOT/scripts/common.sh"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
relative="backups/development-$stamp.sqlite3"
compose exec -T app python -m app.backup "/data/$relative" >/dev/null
printf '%s\n' "Резервная копия: $ROOT_DIR/runtime/data/$relative"
