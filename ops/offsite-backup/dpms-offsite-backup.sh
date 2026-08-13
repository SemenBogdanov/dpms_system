#!/usr/bin/env bash
set -euo pipefail

umask 077

CONFIG_FILE="${DPMS_BACKUP_CONFIG:-/etc/dpms-offsite-backup.conf}"
if [[ -f "$CONFIG_FILE" ]]; then
  # The config is an operator-owned shell file containing paths and a public recipient.
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

SSH_TARGET="${DPMS_BACKUP_SSH_TARGET:-}"
REMOTE_EXPORTER="${DPMS_BACKUP_REMOTE_EXPORTER:-/opt/dpms-tools/dpms-export-backup.sh}"
USB_MOUNT="${DPMS_BACKUP_USB_MOUNT:-}"
DEVICE_UUID="${DPMS_BACKUP_DEVICE_UUID:-}"
DEVICE_LABEL="${DPMS_BACKUP_DEVICE_LABEL:-}"
AGE_RECIPIENT="${DPMS_BACKUP_AGE_RECIPIENT:-}"
AGE_IDENTITY="${DPMS_BACKUP_AGE_IDENTITY:-}"
RETENTION="${DPMS_BACKUP_RETENTION:-3}"
OUTPUT_SUBDIR="${DPMS_BACKUP_OUTPUT_SUBDIR:-dpms-offsite}"
LOCK_FILE="${DPMS_BACKUP_LOCK_FILE:-/var/lib/dpms-backup/offsite.lock}"
TEST_MODE="${DPMS_BACKUP_TEST_MODE:-0}"
SOURCE_FILE="${DPMS_BACKUP_TEST_SOURCE_FILE:-}"
AGE_BIN="${DPMS_BACKUP_AGE_BIN:-age}"
SCHEDULED=0

case "${1:-}" in
  "") ;;
  --scheduled) SCHEDULED=1 ;;
  *) printf 'ERROR: usage: dpms-offsite-backup.sh [--scheduled]\n' >&2; exit 2 ;;
esac

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ -n "$USB_MOUNT" ]] || die "DPMS_BACKUP_USB_MOUNT is required"
[[ -n "$AGE_RECIPIENT" ]] || die "DPMS_BACKUP_AGE_RECIPIENT is required"
[[ -n "$AGE_IDENTITY" ]] || die "DPMS_BACKUP_AGE_IDENTITY is required for verification"
[[ -f "$AGE_IDENTITY" && ! -L "$AGE_IDENTITY" ]] || die "age identity file is unavailable"
[[ "$RETENTION" =~ ^[0-9]+$ && "$RETENTION" -ge 1 ]] || die "retention must be a positive integer"
command -v "$AGE_BIN" >/dev/null 2>&1 || die "age is required"
command -v zstd >/dev/null 2>&1 || die "zstd is required"
if command -v sha256sum >/dev/null 2>&1; then
  SHA256_MODE=sha256sum
elif command -v shasum >/dev/null 2>&1; then
  SHA256_MODE=shasum
else
  die "sha256sum or shasum is required"
fi

if [[ "$TEST_MODE" == "1" && "${DPMS_BACKUP_SKIP_MOUNT_CHECK:-0}" == "1" ]]; then
  :
else
  command -v findmnt >/dev/null 2>&1 || die "findmnt is required"
  findmnt --mountpoint "$USB_MOUNT" >/dev/null 2>&1 \
    || die "configured USB target is not a mounted filesystem"
  [[ -n "$DEVICE_UUID" || -n "$DEVICE_LABEL" ]] \
    || die "DPMS_BACKUP_DEVICE_UUID or DPMS_BACKUP_DEVICE_LABEL is required"
  mount_options="$(findmnt -n -o OPTIONS --target "$USB_MOUNT" | head -n 1)"
  [[ ",$mount_options," == *,rw,* ]] || die "USB filesystem is not writable"
  if [[ -n "$DEVICE_UUID" ]]; then
    actual_uuid="$(findmnt -n -o UUID --target "$USB_MOUNT" | head -n 1)"
    [[ "$actual_uuid" == "$DEVICE_UUID" ]] || die "USB filesystem UUID does not match"
  fi
  if [[ -n "$DEVICE_LABEL" ]]; then
    actual_label="$(findmnt -n -o LABEL --target "$USB_MOUNT" | head -n 1)"
    [[ "$actual_label" == "$DEVICE_LABEL" ]] || die "USB filesystem label does not match"
  fi
fi

mount_real="$(cd "$USB_MOUNT" 2>/dev/null && pwd -P)" || die "USB mount path is unavailable"
case "$mount_real" in
  /|/boot|/etc|/home|/mnt|/opt|/root|/srv|/usr|/var) die "unsafe USB mount path" ;;
esac

marker="$USB_MOUNT/.dpms-offsite-backup-target"
[[ -f "$marker" && ! -L "$marker" ]] || die "USB marker file is missing"
[[ "$(tr -d '\r\n' < "$marker")" == "DPMS_OFFSITE_BACKUP_V1" ]] \
  || die "USB marker file has unexpected content"

output_dir="$USB_MOUNT/$OUTPUT_SUBDIR"
mkdir -p "$output_dir" "$(dirname "$LOCK_FILE")"
[[ ! -L "$output_dir" ]] || die "backup output directory must not be a symbolic link"
output_real="$(cd "$output_dir" && pwd -P)"
[[ "$output_real" == "$mount_real/"* ]] || die "backup output escapes the USB mount"
[[ -w "$output_real" ]] || die "backup output directory is not writable"

now_epoch="$(date -u +%s)"
if [[ "$TEST_MODE" == "1" && -n "${DPMS_BACKUP_NOW_EPOCH:-}" ]]; then
  now_epoch="$DPMS_BACKUP_NOW_EPOCH"
fi
[[ "$now_epoch" =~ ^[0-9]+$ ]] || die "invalid backup epoch"
success_state="$output_dir/.last-success-utc"
if [[ "$SCHEDULED" == "1" && -f "$success_state" ]]; then
  last_success="$(tr -d '\r\n' < "$success_state")"
  [[ "$last_success" =~ ^[0-9]+$ ]] || die "last-success state is invalid"
  if (( now_epoch - last_success < 14 * 24 * 60 * 60 )); then
    log "backup_skipped=interval_not_elapsed"
    exit 0
  fi
fi

test_lock_dir=""
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another offsite backup is running"
elif [[ "$TEST_MODE" == "1" ]]; then
  test_lock_dir="$LOCK_FILE.d"
  mkdir "$test_lock_dir" 2>/dev/null || die "another offsite backup is running"
else
  die "flock is required"
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ "$TEST_MODE" == "1" && -n "${DPMS_BACKUP_NOW:-}" ]]; then
  timestamp="$DPMS_BACKUP_NOW"
fi
[[ "$timestamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || die "invalid backup timestamp"

final="$output_dir/dpms-$timestamp.tar.zst.age"
partial="$output_dir/.dpms-$timestamp.partial"
checksum="$final.sha256"
[[ ! -e "$final" && ! -e "$partial" ]] || die "backup id already exists"

cleanup() {
  rm -f "$partial"
  [[ -z "$test_lock_dir" ]] || rmdir "$test_lock_dir" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
find "$output_dir" -maxdepth 1 -type f -name '.dpms-*.partial' -mtime +7 -delete

emit_backup_stream() {
  if [[ "$TEST_MODE" == "1" ]]; then
    [[ -f "$SOURCE_FILE" ]] || die "test source archive is unavailable"
    cat "$SOURCE_FILE"
    return
  fi
  [[ -n "$SSH_TARGET" ]] || die "DPMS_BACKUP_SSH_TARGET is required"
  [[ "$REMOTE_EXPORTER" =~ ^/[A-Za-z0-9_./-]+$ ]] || die "remote exporter path is invalid"
  ssh -o BatchMode=yes "$SSH_TARGET" -- "sudo -n $REMOTE_EXPORTER"
}

set +e
emit_backup_stream | "$AGE_BIN" --recipient "$AGE_RECIPIENT" --output "$partial"
pipeline_status=("${PIPESTATUS[@]}")
set -e
if [[ "${pipeline_status[0]}" != "0" || "${pipeline_status[1]}" != "0" ]]; then
  die "source export or encryption failed"
fi
[[ -s "$partial" ]] || die "encrypted backup is empty"

entries="$($AGE_BIN --decrypt --identity "$AGE_IDENTITY" "$partial" \
  | zstd --quiet --decompress --stdout \
  | tar -tf -)"
grep -qx 'manifest.json' <<<"$entries" || die "archive manifest is missing"
grep -qx 'database.dump' <<<"$entries" || die "database dump is missing"
grep -qx 'uploads-manifest.jsonl' <<<"$entries" || die "uploads manifest is missing"
grep -q '^uploads/' <<<"$entries" || die "uploads directory is missing"

mv "$partial" "$final"
(
  cd "$output_dir"
  if [[ "$SHA256_MODE" == "sha256sum" ]]; then
    sha256sum "$(basename "$final")" > ".checksum.tmp.$$"
  else
    shasum -a 256 "$(basename "$final")" > ".checksum.tmp.$$"
  fi
  mv ".checksum.tmp.$$" "$(basename "$checksum")"
)
sync -f "$final" 2>/dev/null || sync
sync -f "$output_dir" 2>/dev/null || sync

backup_count="$(find "$output_dir" -maxdepth 1 -type f -name 'dpms-*.tar.zst.age' | wc -l | tr -d ' ')"
while [[ "$backup_count" -gt "$RETENTION" ]]; do
  oldest="$(find "$output_dir" -maxdepth 1 -type f -name 'dpms-*.tar.zst.age' | sort | head -n 1)"
  [[ -n "$oldest" ]] || die "retention inventory is inconsistent"
  rm -f "$oldest" "$oldest.sha256"
  backup_count=$((backup_count - 1))
done

state_tmp="$success_state.tmp.$$"
printf '%s\n' "$now_epoch" > "$state_tmp"
mv "$state_tmp" "$success_state"
sync -f "$success_state" 2>/dev/null || sync

[[ -z "$test_lock_dir" ]] || rmdir "$test_lock_dir"
trap - EXIT INT TERM
log "backup_id=dpms-$timestamp"
log "backup_file=$final"
log "retained_versions=$backup_count"
