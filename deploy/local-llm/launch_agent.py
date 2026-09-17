"""Generate/install a user LaunchAgent without embedding a gateway credential."""

import argparse
import http.client
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time

from recovery_state import RecoveryState

LABEL = "ru.dpms.local-llm.gateway"
SOURCE = Path(__file__).resolve().parent
STATE_DIRECTORY = Path.home() / "Library/Application Support/DPMSLocalLLM/state"


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


def llama_slots_idle() -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
    try:
        connection.request("GET", "/slots", headers={"Accept-Encoding": "identity", "Connection": "close"})
        response = connection.getresponse()
        body = response.read(64 * 1024 + 1)
    finally:
        connection.close()
    if response.status != 200 or len(body) > 64 * 1024:
        raise ValueError("Cannot verify local model slots")
    try:
        slots = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Cannot verify local model slots") from None
    if not isinstance(slots, list) or not 1 <= len(slots) <= 32:
        raise ValueError("Cannot verify local model slots")
    for slot in slots:
        if not isinstance(slot, dict) or type(slot.get("is_processing")) is not bool:
            raise ValueError("Cannot verify local model slots")
    return all(not slot["is_processing"] for slot in slots)


def recover_pending(
    service_state: str,
    *,
    state_directory: Path = STATE_DIRECTORY,
    idle_check=llama_slots_idle,
    pause=time.sleep,
) -> dict:
    if service_state != "NOT_RUNNING":
        raise ValueError("Stop the gateway before confirming recovery")
    recovery = RecoveryState(str(state_directory))
    if not recovery.pending:
        return {"status": "RECOVERY_NOT_REQUIRED"}
    if not idle_check():
        raise ValueError("Local model is still processing")
    pause(1.0)
    if not idle_check():
        raise ValueError("Local model is still processing")
    archived = recovery.archive_pending()
    return {"status": "RECOVERED", "archived_marker": archived.name}


def inspect_service(job: str) -> tuple[str, bool]:
    result = subprocess.run(["launchctl", "print", job], capture_output=True, timeout=10, text=True)
    if result.returncode not in (0, 113):
        raise ValueError("Cannot inspect gateway service")
    listener = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-a", "-iTCP:18080", "-sTCP:LISTEN", "-t"],
        capture_output=True, timeout=10, text=True,
    )
    if listener.returncode not in (0, 1) or listener.stderr.strip():
        raise ValueError("Cannot inspect gateway listener")
    listeners = {int(value) for value in listener.stdout.splitlines() if value.isdigit()}
    return service_status(result.stdout if result.returncode == 0 else "", listeners), result.returncode == 0


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
    parser.add_argument("action", choices=["plan", "install", "start", "stop", "status", "recover"])
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
        elif args.action == "status":
            state, _ = inspect_service(job)
            print(json.dumps({"status": state, "installed": target.exists()}))
        else:
            state, _ = inspect_service(job)
            print(json.dumps(recover_pending(state)))
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise SystemExit("Local gateway service operation failed; existing service was not replaced") from None


if __name__ == "__main__":
    main()
