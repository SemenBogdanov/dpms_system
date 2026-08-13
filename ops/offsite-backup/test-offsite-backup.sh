#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v age >/dev/null 2>&1 || { echo "age is required" >&2; exit 1; }
command -v age-keygen >/dev/null 2>&1 || { echo "age-keygen is required" >&2; exit 1; }
command -v zstd >/dev/null 2>&1 || { echo "zstd is required" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker is required" >&2; exit 1; }

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT INT TERM
mkdir -p "$workdir/uploads" "$workdir/usb"
printf 'DPMS_OFFSITE_BACKUP_V1\n' > "$workdir/usb/.dpms-offsite-backup-target"

docker compose -p dpms-local exec -T db \
  pg_dump -U dpms_user -d dpms -Fc > "$workdir/database.dump"

DPMS_BACKUP_TEST_MODE=1 \
DPMS_BACKUP_TEST_DATABASE_DUMP="$workdir/database.dump" \
DPMS_BACKUP_TEST_UPLOAD_DIR="$workdir/uploads" \
DPMS_BACKUP_STAGE_ROOT="$workdir" \
DPMS_BACKUP_DB_STAGE_ROOT="$workdir" \
  "$ROOT_DIR/deploy/dpms-export-backup.sh" > "$workdir/source.tar.zst"

age-keygen -o "$workdir/identity.txt" >/dev/null 2>&1
recipient="$(age-keygen -y "$workdir/identity.txt")"

mv "$workdir/usb/.dpms-offsite-backup-target" "$workdir/marker.saved"
if DPMS_BACKUP_TEST_MODE=1 \
  DPMS_BACKUP_SKIP_MOUNT_CHECK=1 \
  DPMS_BACKUP_TEST_SOURCE_FILE="$workdir/source.tar.zst" \
  DPMS_BACKUP_USB_MOUNT="$workdir/usb" \
  DPMS_BACKUP_AGE_RECIPIENT="$recipient" \
  DPMS_BACKUP_AGE_IDENTITY="$workdir/identity.txt" \
  DPMS_BACKUP_LOCK_FILE="$workdir/backup.lock" \
    "$ROOT_DIR/ops/offsite-backup/dpms-offsite-backup.sh" >/dev/null 2>&1; then
  echo "missing marker was not rejected" >&2
  exit 1
fi
mv "$workdir/marker.saved" "$workdir/usb/.dpms-offsite-backup-target"

epoch=1000000
for timestamp in 20260801T030000Z 20260815T030000Z 20260829T030000Z 20260912T030000Z; do
  DPMS_BACKUP_TEST_MODE=1 \
  DPMS_BACKUP_SKIP_MOUNT_CHECK=1 \
  DPMS_BACKUP_TEST_SOURCE_FILE="$workdir/source.tar.zst" \
  DPMS_BACKUP_USB_MOUNT="$workdir/usb" \
  DPMS_BACKUP_AGE_RECIPIENT="$recipient" \
  DPMS_BACKUP_AGE_IDENTITY="$workdir/identity.txt" \
  DPMS_BACKUP_LOCK_FILE="$workdir/backup.lock" \
  DPMS_BACKUP_NOW="$timestamp" \
  DPMS_BACKUP_NOW_EPOCH="$epoch" \
    "$ROOT_DIR/ops/offsite-backup/dpms-offsite-backup.sh" >/dev/null
  epoch=$((epoch + 14 * 24 * 60 * 60))
done

backup_count="$(find "$workdir/usb/dpms-offsite" -type f -name 'dpms-*.tar.zst.age' | wc -l | tr -d ' ')"
[[ "$backup_count" == "3" ]] || { echo "retention test failed" >&2; exit 1; }
[[ ! -e "$workdir/usb/dpms-offsite/dpms-20260801T030000Z.tar.zst.age" ]] \
  || { echo "oldest backup was not rotated" >&2; exit 1; }

latest="$workdir/usb/dpms-offsite/dpms-20260912T030000Z.tar.zst.age"
DPMS_BACKUP_AGE_IDENTITY="$workdir/identity.txt" \
  "$ROOT_DIR/ops/offsite-backup/dpms-offsite-restore-drill.sh" "$latest"

DPMS_BACKUP_TEST_MODE=1 \
DPMS_BACKUP_SKIP_MOUNT_CHECK=1 \
DPMS_BACKUP_TEST_SOURCE_FILE="$workdir/source.tar.zst" \
DPMS_BACKUP_USB_MOUNT="$workdir/usb" \
DPMS_BACKUP_AGE_RECIPIENT="$recipient" \
DPMS_BACKUP_AGE_IDENTITY="$workdir/identity.txt" \
DPMS_BACKUP_LOCK_FILE="$workdir/backup.lock" \
DPMS_BACKUP_NOW=20260913T030000Z \
DPMS_BACKUP_NOW_EPOCH="$((epoch - 14 * 24 * 60 * 60 + 60))" \
  "$ROOT_DIR/ops/offsite-backup/dpms-offsite-backup.sh" --scheduled >/dev/null
after_scheduled="$(find "$workdir/usb/dpms-offsite" -type f -name 'dpms-*.tar.zst.age' | wc -l | tr -d ' ')"
[[ "$backup_count" == "$after_scheduled" ]] || { echo "schedule interval gate failed" >&2; exit 1; }

printf 'corruption\n' >> "$latest"
if DPMS_BACKUP_AGE_IDENTITY="$workdir/identity.txt" \
  "$ROOT_DIR/ops/offsite-backup/dpms-offsite-restore-drill.sh" "$latest" >/dev/null 2>&1; then
  echo "corrupted backup was not rejected" >&2
  exit 1
fi

echo "Offsite backup smoke OK: marker, encryption, schedule, checksum, retention=3, restore, corruption guard"
