"""Minimal isolated launcher for an allowlisted audit-tz CLI package.

This file intentionally depends on the Python standard library only so it can
run with ``python -I -S``. Sensitive CLI values are read from a mode-0400
request file and never appear in the process argument list.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import stat
import sys


MAX_REQUEST_BYTES = 64 * 1024
ALLOWED_COMMANDS = {
    "selftest",
    "init-run",
    "add-contract",
    "preflight",
    "export-prompt",
    "validate-atoms",
}


def _guard_runtime(command: str):
    blocked_process_events = {
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.system",
        "subprocess.Popen",
    }

    def guard(event: str, _arguments: tuple[object, ...]) -> None:
        if event.startswith("socket.") and event not in {"socket.gethostname"}:
            raise RuntimeError("runtime_network_disabled")
        # The reviewed self-test legitimately invokes LibreOffice. Normal
        # preflight commands are pure Python and must not spawn another process.
        if command != "selftest" and event in blocked_process_events:
            raise RuntimeError("runtime_subprocess_disabled")

    return guard

def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--skill-root", required=True)
    parser.add_argument("--request", required=True)
    return parser.parse_args()


def _load_request(path: Path) -> tuple[str, list[str]]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > MAX_REQUEST_BYTES:
        raise RuntimeError("invalid_runtime_request")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"command", "args"}:
        raise RuntimeError("invalid_runtime_request")
    command = payload.get("command")
    args = payload.get("args")
    if command not in ALLOWED_COMMANDS or not isinstance(args, list):
        raise RuntimeError("invalid_runtime_command")
    if len(args) > 80 or any(not isinstance(item, str) or len(item) > 2000 for item in args):
        raise RuntimeError("invalid_runtime_arguments")
    return command, args


def main() -> int:
    parsed = _arguments()
    skill_root = Path(parsed.skill_root).resolve()
    script = skill_root / "scripts" / "audit_tz.py"
    request = Path(parsed.request)
    if skill_root.name != "audit-tz" or not script.is_file() or script.is_symlink():
        raise RuntimeError("invalid_skill_runtime")
    command, command_args = _load_request(request)
    os.umask(0o077)
    sys.addaudithook(_guard_runtime(command))
    scripts_dir = str(script.parent)
    sys.path[:] = [scripts_dir, *[item for item in sys.path if item != scripts_dir]]
    namespace = runpy.run_path(str(script), run_name="audit_tz_worker_runtime")
    entrypoint = namespace.get("main")
    if not callable(entrypoint):
        raise RuntimeError("missing_skill_entrypoint")
    return int(entrypoint([command, *command_args]))


if __name__ == "__main__":
    raise SystemExit(main())
