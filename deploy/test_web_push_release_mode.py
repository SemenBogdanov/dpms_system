"""Exercise release Web Push gates with synthetic inputs and mocked Docker only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parent / "dpms-node.sh"
TEXT = SOURCE.read_text()


def function(name):
    return re.search(r"^" + name + r"\(\) \{\n.*?^\}", TEXT, re.M | re.S).group(0)


CHECK = function("validate_web_push_release_mode")
HEALTHCHECK = function("healthcheck")
PROMOTE_CHECK = re.search(
    r"^  validate_env_file\n(.*?)^  runtime_migration_delta=",
    function("promote_release"), re.M | re.S,
).group(1)
SYNTHETIC_VALUE = "public-synthetic-fixture-not-a-vapid-value"
DOCKER_STUB = r'''
import json
import os
import sys
import types

args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
if args[0] == "run":
    if "-i" not in args:
        sys.exit("mock Docker requires stdin attachment")
elif args[0] == "compose":
    if args[-2:] == ["config", "--services"]:
        print("email-worker\nweb-push-worker")
        sys.exit(0)
    if "ps" in args:
        if "--services" in args:
            print("email-worker")
            if os.environ["WORKER_RUNNING"] == "1":
                print("web-push-worker")
        sys.exit(0)
    if args[-5:] != ["exec", "-T", "web-push-worker", "python", "-"]:
        sys.exit("unexpected mock Docker compose command")
else:
    sys.exit("unexpected mock Docker command")
if args[-2:] != ["python", "-"]:
    sys.exit("expected Python on stdin")
if os.environ["DOCKER_FAILURE"] == "1":
    sys.exit(1)

def validate_vapid_configuration():
    with open(os.environ["VALIDATION_LOG"], "a") as stream:
        stream.write("called\n")
    raw = os.getenv("DPMS_WEB_PUSH_PRIVATE_KEY", "")
    if not raw or os.environ["VAPID_VALID"] != "1":
        raise ValueError("synthetic validation error: " + raw)

for name in ("app", "app.services", "app.services.web_push"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["app.services.web_push"].validate_vapid_configuration = validate_vapid_configuration
exec(compile(sys.stdin.read(), "<synthetic-web-push-check>", "exec"))
'''


class WebPushReleaseModeTests(unittest.TestCase):
    def run_check(self, mode=None, private_key=SYNTHETIC_VALUE, *, health=False,
                  vapid_valid=True, worker_running=True, docker_failure=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docker = root / "docker"
            docker.write_text("#!" + sys.executable + "\n" + DOCKER_STUB)
            docker.chmod(0o755)
            compose = root / "compose.yml"
            compose.write_text("synthetic fixture; existence check only\n")
            calls = root / "calls.jsonl"
            validations = root / "validations.log"
            # Never inherit the caller's runtime configuration or credentials.
            env = {
                "PATH": str(root) + os.pathsep + os.defpath,
                "DPMS_ENV_FILE": str(root / "synthetic-runtime-input"),
                "DPMS_COMPOSE_FILE": str(compose),
                "DPMS_COMPOSE_PROJECT": "isolated-test",
                "DPMS_DOMAIN_PUNY": "example.invalid",
                "CALL_LOG": str(calls),
                "VALIDATION_LOG": str(validations),
                "VAPID_VALID": "1" if vapid_valid else "0",
                "WORKER_RUNNING": "1" if worker_running else "0",
                "DOCKER_FAILURE": "1" if docker_failure else "0",
            }
            if mode is not None:
                env["DPMS_WEB_PUSH_MODE"] = mode
            if private_key is not None:
                env["DPMS_WEB_PUSH_PRIVATE_KEY"] = private_key
            script = '''set -euo pipefail
log() { printf '%s\\n' "$*"; }
die() { printf 'ERROR: %s\\n' "$*" >&2; exit 1; }
curl() { printf '200'; }
frontend_asset_healthcheck() { return 0; }
image_tag=synthetic-image
''' + CHECK + "\n" + (HEALTHCHECK + "\nhealthcheck\n" if health else PROMOTE_CHECK)
            result = subprocess.run(
                ["bash", "-c", script], env=env, capture_output=True, text=True,
                timeout=10,
            )
            docker_calls = [json.loads(line) for line in calls.read_text().splitlines()]
            validation_calls = validations.read_text().splitlines() if validations.exists() else []
            self.assertNotIn(SYNTHETIC_VALUE, result.stdout + result.stderr)
            return result, docker_calls, validation_calls

    def test_default_and_explicit_enabled_validate_vapid(self):
        for mode in (None, "enabled"):
            with self.subTest(mode=mode):
                result, calls, validations = self.run_check(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "web_push_mode=enabled\n")
                self.assertEqual(result.stderr, "")
                self.assertEqual(validations, ["called"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][:3], ["run", "-i", "--rm"])
                self.assertIn("--env-file", calls[0])
                self.assertEqual(calls[0][-3:], ["synthetic-image", "python", "-"])

    def test_enabled_rejects_absent_or_empty_private_key(self):
        for mode in (None, "enabled"):
            for private_key in (None, ""):
                with self.subTest(mode=mode, private_key=private_key):
                    result, _, validations = self.run_check(mode, private_key)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(validations, ["called"])
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "ERROR: Web Push release mode or VAPID configuration is invalid\n")

    def test_enabled_rejects_invalid_vapid_without_exception_details(self):
        result, _, validations = self.run_check("enabled", vapid_valid=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(validations, ["called"])
        self.assertNotIn("synthetic validation error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_disabled_accepts_only_absent_or_empty_private_key(self):
        for private_key in (None, ""):
            with self.subTest(private_key=private_key):
                result, _, validations = self.run_check("disabled", private_key)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "web_push_mode=disabled\n")
                self.assertEqual(result.stderr, "")
                self.assertEqual(validations, [])

    def test_disabled_rejects_any_nonempty_private_key(self):
        for private_key in (SYNTHETIC_VALUE, " ", "\n"):
            with self.subTest(private_key=private_key):
                result, _, validations = self.run_check("disabled", private_key)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(validations, [])

    def test_unknown_modes_are_rejected_not_reflected(self):
        for mode in ("", "ENABLED", "DISABLED", " enabled", "disabled ", SYNTHETIC_VALUE):
            with self.subTest(mode=mode):
                result, _, validations = self.run_check(mode, None)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(validations, [])

    def test_healthcheck_enabled_and_disabled_status(self):
        for mode, private_key, status, expected_calls in (
            (None, SYNTHETIC_VALUE, "healthy", ["called"]),
            ("enabled", SYNTHETIC_VALUE, "healthy", ["called"]),
            ("disabled", None, "disabled", []),
            ("disabled", "", "disabled", []),
        ):
            with self.subTest(mode=mode, private_key=private_key):
                result, calls, validations = self.run_check(mode, private_key, health=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("web_push_worker=" + status + "\n", result.stdout)
                self.assertIn("healthcheck_ok=1\n", result.stdout)
                self.assertEqual(validations, expected_calls)
                self.assertTrue(any(call[-5:] == ["exec", "-T", "web-push-worker", "python", "-"] for call in calls))

    def test_healthcheck_rejects_invalid_configuration(self):
        for mode, private_key, vapid_valid in (
            (None, None, True),
            ("enabled", SYNTHETIC_VALUE, False),
            ("disabled", SYNTHETIC_VALUE, True),
            (SYNTHETIC_VALUE, None, True),
        ):
            with self.subTest(mode=mode, private_key=private_key):
                result, _, _ = self.run_check(mode, private_key, health=True, vapid_valid=vapid_valid)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("web_push_worker=missing\n", result.stdout)
                self.assertIn("healthcheck_failed=1\n", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_disabled_healthcheck_still_requires_running_worker(self):
        result, calls, validations = self.run_check("disabled", None, health=True, worker_running=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("web_push_worker=missing\n", result.stdout)
        self.assertFalse(any("exec" in call for call in calls))
        self.assertEqual(validations, [])

    def test_docker_failure_is_fail_closed_for_both_gates(self):
        for health in (False, True):
            with self.subTest(health=health):
                result, _, validations = self.run_check("disabled", None, health=health, docker_failure=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(validations, [])


if __name__ == "__main__":
    unittest.main()
