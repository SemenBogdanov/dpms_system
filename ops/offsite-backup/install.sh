#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-install}"
BACKUP_USER="${DPMS_BACKUP_USER:-dpms-backup}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(id -u)" == "0" ]] || die "run through sudo"
[[ "$ACTION" == "install" || "$ACTION" == "enable" ]] \
  || die "usage: install.sh [install|enable]"

if [[ "$ACTION" == "install" ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "$ID" == "ubuntu" && "$VERSION_ID" == "24.04" ]] \
    || die "supported backup host is Ubuntu 24.04"

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y age zstd rsync openssh-client util-linux ca-certificates
  command -v docker >/dev/null 2>&1 \
    || die "Docker is required for restore drill; install Docker, then repeat"

  if ! id "$BACKUP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/dpms-backup \
      --shell /usr/sbin/nologin "$BACKUP_USER"
  fi
  install -d -m 0700 -o "$BACKUP_USER" -g "$BACKUP_USER" /var/lib/dpms-backup
  install -m 0755 "$ROOT_DIR/dpms-offsite-backup.sh" /usr/local/sbin/dpms-offsite-backup.sh
  install -m 0755 "$ROOT_DIR/dpms-offsite-restore-drill.sh" /usr/local/sbin/dpms-offsite-restore-drill.sh
  install -m 0644 "$ROOT_DIR/dpms-offsite-backup.service" /etc/systemd/system/dpms-offsite-backup.service
  install -m 0644 "$ROOT_DIR/dpms-offsite-backup.timer" /etc/systemd/system/dpms-offsite-backup.timer
  install -m 0600 "$ROOT_DIR/dpms-offsite-backup.conf.example" /etc/dpms-offsite-backup.conf.example
  systemd-analyze verify /etc/systemd/system/dpms-offsite-backup.service \
    /etc/systemd/system/dpms-offsite-backup.timer
  systemctl daemon-reload
  printf 'installed=1\n'
  printf 'next=configure /etc/dpms-offsite-backup.conf, SSH, identity, and USB; run manual backup and restore drill\n'
  exit 0
fi

[[ -f /etc/dpms-offsite-backup.conf ]] || die "backup config is missing"
[[ "$(stat -c '%a' /etc/dpms-offsite-backup.conf)" == "600" ]] \
  || die "backup config mode must be 0600"
systemd-analyze verify /etc/systemd/system/dpms-offsite-backup.service \
  /etc/systemd/system/dpms-offsite-backup.timer
systemctl enable --now dpms-offsite-backup.timer
systemctl list-timers dpms-offsite-backup.timer --no-pager
