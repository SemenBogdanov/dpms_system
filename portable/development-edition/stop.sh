#!/usr/bin/env sh
set -eu

DPMS_PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DPMS_PACKAGE_ROOT
. "$DPMS_PACKAGE_ROOT/scripts/common.sh"
compose down
