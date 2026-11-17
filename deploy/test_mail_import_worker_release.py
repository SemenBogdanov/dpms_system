"""Synthetic release lifecycle tests; Docker, HTTP and host operations are stubbed."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


DEPLOY = Path(__file__).parent
# The production controller targets Linux Bash, not macOS's legacy /bin/bash.
BASH = shutil.which("bash") or "/bin/bash"
TEXT = (DEPLOY / "dpms-node.sh").read_text()
COMPOSE = (DEPLOY / "docker-compose.prod.yml").read_text()
WORKER = "mail-import-worker"
OLD_SERVICES = "backend\nemail-worker\naudit-worker\nweb-push-worker\ndeadline-worker\nserver-boot-worker"
NEW_SERVICES = OLD_SERVICES + "\n" + WORKER


def function(name):
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", TEXT, re.M | re.S)
    if match is None:
        raise AssertionError("Missing release function: " + name)
    return match.group(0)


FUNCTIONS = "\n".join(function(name) for name in (
    "compose_service_list", "healthcheck", "stop_mail_import_worker",
    "promote_release", "rollback_release",
))

# Only these extracted functions execute. No sourcing of release defaults or
# credentials; every command capable of contacting a host is replaced here.
STUBS = r'''
record() { printf '%s\n' "$*" >> "$EVENTS"; }
log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
require_root() { :; }
with_lock() { :; }
validate_env_file() { :; }
frontend_asset_healthcheck() { return 0; }
validate_web_push_release_mode() { printf 'disabled\n'; }
curl() { record "curl $*"; printf 200; }
nginx() { record "nginx $*"; }
systemctl() { record "systemctl $*"; }
local_model_guard_pause() { record pause; }
local_model_guard_resume() { record resume; }
release_dir_for_id() { printf '%s\n' "$CANDIDATE"; }
manifest_path() { printf '%s/manifest.json\n' "$1"; }
manifest_get() {
  case "$2" in
    approval_phrase) printf 'approved\n' ;;
    commit_sha) printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' ;;
    image_tag) printf 'synthetic-backend:candidate\n' ;;
    audit_worker_image_tag) printf 'synthetic-audit:candidate\n' ;;
    migrations_count) printf '%s\n' "$MIGRATIONS" ;;
    *) return 98 ;;
  esac
}
resolve_ref() { printf '%s\n' "$1"; }
migration_delta() { if [[ "$MIGRATIONS" == 1 ]]; then printf 'synthetic migration\n'; fi; }
docker_network_args() { :; }
backup_app_state() { record backup; printf '%s\n' "$BACKUP"; }
copy_runtime_files_from_release() { record copy_runtime; }
install_nginx_config_from_release() { record install_nginx; }
install_tool_from_release() { record install_tool; }
manifest_mark_promoted() { record promoted; }
wait_for_healthcheck() { healthcheck; }
stop_retired_server_boot_worker() { record stop_retired_boot; }
timeout() {
  record "timeout $*"
  [[ "$1" == --kill-after=5s && ( "$2" == 15s || "$2" == 45s ) ]] || return 97
  shift 2
  if [[ -n "$TIMEOUT_MATCH" && " $* " == *"$TIMEOUT_MATCH"* ]]; then return 124; fi
  "$@"
}
docker() {
  record "docker $*"
  case "$1" in
    compose)
      if [[ " $* " == *" config --services "* ]]; then
        [[ "$CONFIG_RC" == 0 ]] || return "$CONFIG_RC"
        printf '%s\n' "$SERVICES"
      elif [[ " $* " == *" ps --status running --services "* ]]; then
        printf '%s\n' "$RUNNING"
      elif [[ " $* " == *" exec -T mail-import-worker "* ]]; then
        [[ " $* " == *" python -m app.workers.mail_import_queue --healthcheck " ]] || return 97
        return "$PROBE_RC"
      elif [[ " $* " == *" exec -T "* || " $* " == *" ps " ]]; then
        return 0
      elif [[ " $* " == *" up -d --no-build --force-recreate "* ]]; then
        record "up ${*:2}"
      else
        printf 'Unexpected compose operation\n' >&2
        return 98
      fi
      ;;
    ps)
      if [[ " $* " == *"label=com.docker.compose.service=mail-import-worker"* ]]; then
        [[ " $* " == *" ps -aq "* ]] || return 97
        [[ " $* " == *"label=com.docker.compose.project=synthetic"* ]] || return 97
        printf '%s' "$CONTAINERS"
      fi
      ;;
    update) return "$UPDATE_RC" ;;
    stop) return "$STOP_RC" ;;
    image|tag|rm) return 0 ;;
    run)
      [[ " $* " == *" alembic upgrade head " ]] || return 98
      return 0
      ;;
    *) printf 'Unexpected docker operation\n' >&2; return 98 ;;
  esac
}
'''


class MailWorkerReleaseTests(unittest.TestCase):
    def run_shell(self, command, **overrides):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        live = root / "live"
        (live / "deploy").mkdir(parents=True)
        compose = live / "deploy/docker-compose.prod.yml"
        compose.write_text("services: {}\n")
        candidate = root / "candidate"
        (candidate / "deploy").mkdir(parents=True)
        (candidate / "deploy/docker-compose.prod.yml").write_text("services: {}\n")
        (candidate / "manifest.json").write_text("{}\n")
        backup = root / "backup"
        backup.mkdir()
        (backup / "previous-backend-image-id.txt").write_text("synthetic-original-image\n")
        queue = root / "synthetic-queue.bin"
        queue.write_bytes(b"pending receipt and payload")
        events = root / "events.txt"
        connector = root / "connector"
        connector.mkdir()
        environment = {
            "PATH": os.defpath, "DPMS_LIVE_ROOT": str(live),
            "DPMS_COMPOSE_FILE": str(compose), "DPMS_COMPOSE_PROJECT": "synthetic",
            "DPMS_ENV_FILE": str(root / "unused-environment"),
            "DPMS_CONNECTOR_DIR": str(connector), "DPMS_DOMAIN_PUNY": "test.invalid",
            "EVENTS": str(events), "CANDIDATE": str(candidate), "BACKUP": str(backup),
            "SERVICES": NEW_SERVICES, "RUNNING": NEW_SERVICES,
            "CONFIG_RC": "0", "PROBE_RC": "0", "UPDATE_RC": "0", "STOP_RC": "0",
            "TIMEOUT_MATCH": "", "MIGRATIONS": "1",
            "CONTAINERS": "aaaaaaaaaaaa\nbbbbbbbbbbbb\n",
        }
        environment.update(overrides)
        result = subprocess.run(
            [BASH, "-c", "set -euo pipefail\n" + FUNCTIONS + "\n" + STUBS + "\n" + command],
            capture_output=True, text=True, timeout=10, cwd=root, env=environment,
        )
        self.assertEqual(queue.read_bytes(), b"pending receipt and payload")
        return result, events.read_text().splitlines() if events.exists() else []

    def test_compose_uses_backend_image_and_read_only_worker_probe(self):
        block = re.search(r"^  mail-import-worker:\n(.*?)(?=^  \S|\Z)", COMPOSE, re.M | re.S).group(1)
        self.assertIn("image: deploy-backend:latest", block)
        self.assertIn('command: ["python", "-m", "app.workers.mail_import_queue"]', block)
        self.assertIn('test: ["CMD", "python", "-m", "app.workers.mail_import_queue", "--healthcheck"]', block)
        for setting in ("condition: service_healthy", "stop_grace_period: 30s", "timeout: 10s",
                        "start_period: 60s", "read_only: true", "cap_drop: [ALL]",
                        "PYTHONDONTWRITEBYTECODE", "/tmp/mail-import-queue.heartbeat"):
            self.assertIn(setting, block)
        self.assertNotRegex(block, r"(?m)^    (ports|volumes|build):")
        self.assertNotIn("--once", block)
        self.assertNotIn("alembic", block)

    def test_health_requires_fresh_worker_probe(self):
        result, events = self.run_shell("healthcheck")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mail_import_worker=healthy", result.stdout)
        probes = [event for event in events if event.startswith("timeout ") and "exec -T mail-import-worker" in event]
        self.assertEqual(len(probes), 1)
        self.assertTrue(probes[0].startswith("timeout --kill-after=5s 15s "))
        self.assertTrue(probes[0].endswith("app.workers.mail_import_queue --healthcheck"))

    def test_missing_stale_and_timed_out_worker_fail_health(self):
        for overrides in ({"RUNNING": OLD_SERVICES}, {"PROBE_RC": "1"},
                          {"TIMEOUT_MATCH": "exec -T mail-import-worker"},
                          {"TIMEOUT_MATCH": "ps --status running --services"}):
            with self.subTest(overrides=overrides):
                result, _ = self.run_shell("healthcheck", **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mail_import_worker=missing", result.stdout)
                self.assertNotIn("healthcheck_ok=1", result.stdout)

    def test_old_compose_can_be_healthy_without_mail_worker(self):
        result, events = self.run_shell("healthcheck", SERVICES=OLD_SERVICES, RUNNING=OLD_SERVICES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mail_import_worker=not_configured", result.stdout)
        self.assertFalse(any("exec -T mail-import-worker" in event for event in events))

    def test_config_failure_empty_and_timeout_fail_before_health_probes(self):
        for overrides in ({"CONFIG_RC": "1"}, {"SERVICES": ""},
                          {"TIMEOUT_MATCH": "config --services"}):
            with self.subTest(overrides=overrides):
                result, events = self.run_shell("healthcheck", **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("compose_services=failed", result.stdout)
                self.assertFalse(any(event.startswith("curl ") for event in events))
                self.assertNotIn("not_configured", result.stdout)

    def test_effective_compose_uses_override_and_rejects_missing_override(self):
        for available in (False, True):
            with self.subTest(available=available):
                setup = ': > "$DPMS_CONNECTOR_DIR/compose-activated"\n'
                if available:
                    setup += 'printf "{}\\n" > "$DPMS_CONNECTOR_DIR/connector.override.json"\n'
                result, events = self.run_shell(setup + 'compose_service_list "$DPMS_COMPOSE_FILE"')
                if available:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(any("connector.override.json config --services" in event for event in events))
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(events, [])

    def test_promote_starts_worker_after_migration(self):
        result, events = self.run_shell("promote_release synthetic --approval approved --allow-migrations --backup-id synthetic")
        self.assertEqual(result.returncode, 0, result.stderr)
        up = next(event for event in events if event.startswith("up "))
        self.assertIn(WORKER, up.split())
        migration = next(i for i, event in enumerate(events) if event.startswith("docker run "))
        stop = next(i for i, event in enumerate(events) if event.startswith("docker stop "))
        self.assertLess(stop, migration)
        self.assertLess(migration, events.index(up))
        self.assertEqual(events[-1], "promoted")

    def test_invalid_candidate_compose_prevents_migration_and_live_changes(self):
        result, events = self.run_shell(
            "promote_release synthetic --approval approved --allow-migrations --backup-id synthetic", CONFIG_RC="1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate compose services", result.stderr)
        for prefix in ("docker tag ", "docker run ", "docker update ", "docker stop ", "up ", "copy_runtime", "backup", "pause"):
            self.assertFalse(any(event.startswith(prefix) for event in events), prefix)

    def test_promote_health_failure_does_not_mark_release_promoted(self):
        result, events = self.run_shell(
            "promote_release synthetic --approval approved --allow-migrations --backup-id synthetic", PROBE_RC="1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("promoted", events)

    def test_rollback_to_old_release_retires_all_mail_containers_before_retag(self):
        result, events = self.run_shell('rollback_release "$BACKUP"', SERVICES=OLD_SERVICES, RUNNING=OLD_SERVICES)
        self.assertEqual(result.returncode, 0, result.stderr)
        retag = next(i for i, event in enumerate(events) if event.startswith("docker tag "))
        for container in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
            update = events.index("docker update --restart=no " + container)
            stop = events.index("docker stop --time 30 " + container)
            self.assertLess(update, stop)
            self.assertLess(stop, retag)
        up = next(event for event in events if event.startswith("up "))
        self.assertNotIn(WORKER, up.split())
        self.assertFalse(any("alembic" in event or "docker rm" in event for event in events))
        self.assertIn("rollback_ok=1", result.stdout)

    def test_rollback_to_worker_release_recreates_it_on_previous_image(self):
        result, events = self.run_shell('rollback_release "$BACKUP"')
        self.assertEqual(result.returncode, 0, result.stderr)
        up = next(event for event in events if event.startswith("up "))
        self.assertIn(WORKER, up.split())
        self.assertLess(events.index("docker tag synthetic-original-image deploy-backend:latest"), events.index(up))

    def test_invalid_restored_compose_never_starts_services_or_reports_success(self):
        result, events = self.run_shell('rollback_release "$BACKUP"', CONFIG_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restored compose services", result.stderr)
        self.assertFalse(any(event.startswith("up ") for event in events))
        self.assertNotIn("rollback_ok=1", result.stdout)

    def test_stop_failure_or_timeout_aborts_rollback_before_retag(self):
        for overrides in ({"UPDATE_RC": "1"}, {"STOP_RC": "1"},
                          {"TIMEOUT_MATCH": "docker ps -aq"}, {"TIMEOUT_MATCH": "docker stop"}):
            with self.subTest(overrides=overrides):
                result, events = self.run_shell('rollback_release "$BACKUP"', **overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(event.startswith("docker tag ") or event.startswith("up ") for event in events))
                self.assertNotIn("rollback_ok=1", result.stdout)

    def test_stop_without_existing_containers_is_noop(self):
        result, events = self.run_shell("stop_mail_import_worker", CONTAINERS="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(event.startswith("docker update ") or event.startswith("docker stop ") for event in events))


if __name__ == "__main__":
    unittest.main()
