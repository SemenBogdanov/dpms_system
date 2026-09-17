"""Generate/install a user LaunchAgent without embedding a gateway credential."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess

LABEL = "ru.dpms.local-llm.gateway"
SOURCE = Path(__file__).resolve().parent


def job_pid(output: str) -> int | None:
    fields = {}
    for line in output.splitlines():
        if line.startswith("\t") and not line.startswith("\t\t"):
            name, separator, value = line.strip().partition(" = ")
            if separator:
                fields[name] = value
    pid = fields.get("pid", "")
    return int(pid) if fields.get("state") == "running" and pid.isdigit() and int(pid) > 0 else None


def service_status(output: str, listeners: set[int]) -> str:
    pid = job_pid(output)
    if listeners and (pid is None or listeners != {pid}):
        return "LISTENER_MISMATCH"
    if pid is not None:
        return "RUNNING" if listeners == {pid} else "STARTING"
    return "NOT_RUNNING"


def definition(model: str, source: Path = SOURCE, home: Path | None = None):
    home = home or Path.home()
    if not model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ValueError("Supply the exact local model identifier")
    return {
        "Label": LABEL,
        "ProgramArguments": [str(source / "bin/dpms-macos-store"), "run"],
        "EnvironmentVariables": {
            "DPMS_LOCAL_LLM_MODEL": model,
            "DPMS_LOCAL_LLM_STATE_DIRECTORY": str(home / "Library/Application Support/DPMSLocalLLM/state"),
            "PYTHONUNBUFFERED": "1",
        },
        "WorkingDirectory": str(source),
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
        "ExitTimeOut": 90,
        "AbandonProcessGroup": False,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "install", "start", "stop", "status"])
    parser.add_argument("--model")
    args = parser.parse_args()
    target = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    domain = f"gui/{os.getuid()}"
    job = domain + "/" + LABEL
    try:
        if args.action in {"plan", "install"}:
            document = definition(args.model or "")
            if args.action == "plan":
                print(json.dumps({"status": "PLAN", "label": LABEL, "credential_in_plist": False,
                                  "auto_restart": False, "loopback_only": True}))
                return
            if target.exists() or target.is_symlink():
                raise ValueError("Existing LaunchAgent preserved; stop and review it before updating")
            for name in ("bin/dpms-macos-store", ".venv/bin/python", "gateway.py"):
                if not (SOURCE / name).is_file():
                    raise ValueError("Build helper and install local dependencies first")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as output:
                plistlib.dump(document, output)
            print(json.dumps({"status": "INSTALLED", "started": False}))
        elif args.action == "start":
            result = subprocess.run(["launchctl", "bootstrap", domain, str(target)], capture_output=True, timeout=15)
            print(json.dumps({"status": "START_REQUESTED" if result.returncode == 0 else "START_FAILED"}))
            raise SystemExit(0 if result.returncode == 0 else 2)
        elif args.action == "stop":
            result = subprocess.run(["launchctl", "bootout", job], capture_output=True, timeout=100)
            print(json.dumps({"status": "STOP_REQUESTED" if result.returncode == 0 else "STOP_FAILED"}))
            raise SystemExit(0 if result.returncode == 0 else 2)
        else:
            result = subprocess.run(["launchctl", "print", job], capture_output=True, timeout=10, text=True)
            listener = subprocess.run(
                ["/usr/sbin/lsof", "-nP", "-a", "-iTCP:18080", "-sTCP:LISTEN", "-t"],
                capture_output=True, timeout=10, text=True,
            )
            if listener.returncode not in (0, 1) or listener.stderr.strip():
                raise ValueError("Cannot inspect gateway listener")
            listeners = {int(value) for value in listener.stdout.splitlines() if value.isdigit()}
            state = service_status(result.stdout if result.returncode == 0 else "", listeners)
            print(json.dumps({"status": state, "installed": target.exists()}))
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise SystemExit("Local gateway service operation failed; existing service was not replaced") from None


if __name__ == "__main__":
    main()
