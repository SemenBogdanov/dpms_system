#!/usr/bin/env sh
set -eu

ROOT_DIR=${DPMS_PACKAGE_ROOT:?DPMS_PACKAGE_ROOT is not set}
cd "$ROOT_DIR"

if docker info >/dev/null 2>&1; then
  DOCKER="docker"
elif command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
else
  printf '%s\n' "Docker недоступен. На Ubuntu сначала запустите: sudo ./install-ubuntu.sh" >&2
  exit 1
fi

if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  DPMS_UID=$(id -u "$SUDO_USER")
  DPMS_GID=$(id -g "$SUDO_USER")
else
  DPMS_UID=$(id -u)
  DPMS_GID=$(id -g)
fi

if [ "$DPMS_UID" -eq 0 ]; then
  DPMS_UID=10001
  DPMS_GID=10001
  mkdir -p runtime/data
  chown -R "$DPMS_UID:$DPMS_GID" runtime/data
else
  mkdir -p runtime/data
fi

export DPMS_UID DPMS_GID

compose() {
  $DOCKER compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" "$@"
}

health_host=${DPMS_BIND_ADDRESS:-127.0.0.1}
case "$health_host" in
  0.0.0.0|::) health_host=127.0.0.1 ;;
esac
HEALTH_URL="http://$health_host:${DPMS_PORT:-8787}/api/health"

healthcheck() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$HEALTH_URL" >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$HEALTH_URL" >/dev/null 2>&1
  else
    compose exec -T app python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" \
      >/dev/null 2>&1
  fi
}

print_health() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$HEALTH_URL"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$HEALTH_URL"
  else
    compose exec -T app python -c \
      "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read().decode())"
  fi
}
