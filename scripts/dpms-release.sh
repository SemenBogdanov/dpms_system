#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/dpms-release.sh <command> [args]

Thin local wrapper around the VPS-first release manager. It does not build or
upload application code from this machine. The VPS fetches GitHub itself.

Examples:
  scripts/dpms-release.sh prepare main
  scripts/dpms-release.sh status
  scripts/dpms-release.sh promote dpms-<sha> --approval promote:dpms-<sha>:<sha>

Environment:
  DPMS_VPS_HOST             SSH target, default: dpms-vps
  DPMS_SSH_CONTROL_PATH     SSH ControlMaster path, default: ~/.ssh/controlmasters/dpms-vps
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
  usage
  exit 0
fi

vps_host="${DPMS_VPS_HOST:-dpms-vps}"
control_path="${DPMS_SSH_CONTROL_PATH:-$HOME/.ssh/controlmasters/dpms-vps}"

remote=(/opt/dpms-tools/dpms-node.sh -- "$@")
printf -v remote_cmd '%q ' "${remote[@]}"
if [[ -S "$control_path" ]]; then
  exec ssh -o "ControlPath=$control_path" "$vps_host" "$remote_cmd"
fi

exec ssh "$vps_host" "$remote_cmd"
