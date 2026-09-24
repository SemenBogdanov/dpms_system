"""Exercise the exact release-manager retirement function without production."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "dpms-node.sh"
FUNCTION = re.search(
    r"^stop_retired_server_boot_worker\(\) \{\n.*?^\}",
    SOURCE.read_text(), re.M | re.S,
).group(0)


class BootWorkerReleaseTests(unittest.TestCase):
    def run_retirement(self, ids="running\nstopped", fail_update=False, fail_list=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docker = root / "docker"
            docker.write_text(
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "with open(os.environ['CALL_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
                "if sys.argv[1]=='ps' and os.environ['FAIL_LIST']=='1': sys.exit(1)\n"
                "if sys.argv[1]=='ps' and os.environ['TEST_IDS']: print(os.environ['TEST_IDS'])\n"
                "if sys.argv[1]=='update' and os.environ['FAIL_UPDATE']=='1': sys.exit(1)\n"
            )
            docker.chmod(0o755)
            log = root / "calls.jsonl"
            result = subprocess.run(
                ["bash", "-c", "set -e\nDPMS_COMPOSE_PROJECT=isolated-test\n" + FUNCTION + "\nstop_retired_server_boot_worker"],
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                     "CALL_LOG": str(log), "TEST_IDS": ids,
                     "FAIL_LIST": "1" if fail_list else "0",
                     "FAIL_UPDATE": "1" if fail_update else "0"},
                capture_output=True, text=True,
            )
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls

    def test_running_and_stopped_workers_disable_restart_before_stop(self):
        result, calls = self.run_retirement()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ["ps", "-aq", "--filter", "label=com.docker.compose.project=isolated-test",
             "--filter", "label=com.docker.compose.service=server-boot-worker"],
            ["update", "--restart=no", "running", "stopped"],
            ["stop", "running", "stopped"],
        ])

    def test_restart_update_failure_blocks_retirement(self):
        result, calls = self.run_retirement(fail_update=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["ps", "update"])

    def test_existing_release_worker_is_not_retired(self):
        source = SOURCE.read_text()
        self.assertRegex(source, r"runtime_services\+=\(server-boot-worker\)\n  else\n    stop_retired_server_boot_worker\n  fi")

    def test_list_failure_is_not_reported_as_success(self):
        result, calls = self.run_retirement(fail_list=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["ps"])

    def test_no_containers_means_no_changes(self):
        result, calls = self.run_retirement(ids="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in calls], ["ps"])


if __name__ == "__main__":
    unittest.main()
