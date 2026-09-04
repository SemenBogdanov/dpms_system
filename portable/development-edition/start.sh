#!/usr/bin/env sh
set -eu

DPMS_PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DPMS_PACKAGE_ROOT
. "$DPMS_PACKAGE_ROOT/scripts/common.sh"

case "$(uname -m)" in
  x86_64|amd64) IMAGE_ARCH="amd64" ;;
  arm64|aarch64) IMAGE_ARCH="arm64" ;;
  *) IMAGE_ARCH="$(uname -m)" ;;
esac

IMAGE_ARCHIVE="images/dpms-development-edition-$IMAGE_ARCH.tar.gz"
if [ -f "$IMAGE_ARCHIVE" ]; then
  printf '%s\n' "Загрузка готового Docker-образа..."
  gzip -dc "$IMAGE_ARCHIVE" | $DOCKER load >/dev/null
  compose up -d --no-build
else
  printf '%s\n' "Сборка и запуск DPMS Development Edition..."
  compose up -d --build
fi

attempt=0
while [ "$attempt" -lt 60 ]; do
  if healthcheck; then
    printf '\n%s\n' "Система готова: http://localhost:${DPMS_PORT:-8787}"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

compose ps
compose logs --tail=80 app
printf '%s\n' "Система не прошла проверку готовности." >&2
exit 1
