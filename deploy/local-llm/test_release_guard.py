import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'dpms-node.sh'


class ReleaseGuardTests(unittest.TestCase):
    def run_guard(self, *, enabled=True, phase='confirmed', missing=None, fail=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if enabled:
                (root / 'compose-activated').touch()
            (root / 'activation-state.json').write_text(json.dumps({'phase': phase}))
            for name in ('connector.override.json', 'tailscale-quarantine.nft'):
                if name != missing:
                    (root / name).write_text('{}')
            environment = {'PATH': os.environ['PATH'], 'HOME': str(root),
                           'DPMS_CONNECTOR_DIR': str(root),
                           'DPMS_CONNECTOR_LOCK_FILE': str(root / 'lock'),
                           'FAIL_COMMAND': fail or ''}
            shell = r'''
source "$1"
flock() { echo "lock"; [[ "$FAIL_COMMAND" != "lock" ]]; }
systemctl() {
  echo "$*"
  [[ "$FAIL_COMMAND" != "$*" ]] || return 1
  [[ "$FAIL_COMMAND" != "resume_and_quarantine" || "$*" != "start dpms-connector-guard.timer" ]]
}
nft() {
  echo "quarantine"
  NFT_CALLS=$((${NFT_CALLS:-0} + 1))
  [[ "$FAIL_COMMAND" != "quarantine" ]] || return 1
  [[ "$FAIL_COMMAND" != "resume_and_quarantine" || "$NFT_CALLS" == 1 ]]
}
tailscale() { echo "tailnet_disconnect"; }
local_model_guard_pause
echo "recreate"
local_model_guard_resume
echo "complete"
'''
            return subprocess.run(['bash', '-c', shell, 'guard-test', str(SCRIPT)],
                                  env=environment, capture_output=True, text=True, timeout=5)

    def test_route_closed_before_recreate_and_freshly_opened_after(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            'lock', 'stop dpms-connector-guard.timer', 'stop dpms-connector-guard.service',
            'quarantine', 'recreate', 'start dpms-connector-guard.service',
            'start dpms-connector-guard.timer', 'complete',
        ])

    def test_no_connector_leaves_network_untouched(self):
        result = self.run_guard(enabled=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['lock', 'recreate', 'complete'])

    def test_unconfirmed_activation_blocks_recreate(self):
        for phase in ('trial', 'rolling_back', 'rolled_back', 'rollback_failed'):
            with self.subTest(phase=phase):
                result = self.run_guard(phase=phase)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('recreate', result.stdout)

    def test_incomplete_configuration_blocks_recreate(self):
        for missing in ('connector.override.json', 'tailscale-quarantine.nft'):
            result = self.run_guard(missing=missing)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('recreate', result.stdout)

    def test_pause_failure_never_recreates(self):
        for failed in ('lock', 'stop dpms-connector-guard.timer',
                       'stop dpms-connector-guard.service', 'quarantine'):
            with self.subTest(failed=failed):
                result = self.run_guard(fail=failed)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('recreate', result.stdout)

    def test_guard_failure_never_restarts_periodic_refresh(self):
        result = self.run_guard(fail='start dpms-connector-guard.service')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('start dpms-connector-guard.timer', result.stdout)
        self.assertNotIn('complete', result.stdout)
        self.assertEqual(result.stdout.splitlines()[-1], 'quarantine')

    def test_timer_failure_recloses_route_after_successful_guard(self):
        result = self.run_guard(fail='start dpms-connector-guard.timer')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines()[-3:], [
            'stop dpms-connector-guard.timer', 'stop dpms-connector-guard.service', 'quarantine',
        ])
        self.assertNotIn('complete', result.stdout)

    def test_cleanup_firewall_failure_disconnects_tailnet(self):
        result = self.run_guard(fail='resume_and_quarantine')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines()[-2:], ['quarantine', 'tailnet_disconnect'])

    def test_promote_and_rollback_use_guard_and_overlay_without_image_pins(self):
        source = SCRIPT.read_text()
        for name in ('promote_release', 'rollback_release'):
            body = source.split(name + '() {', 1)[1].split('\n}\n', 1)[0]
            self.assertLess(body.index('local_model_guard_pause'), body.index('up -d --no-build'))
            self.assertLess(body.index('up -d --no-build'), body.index('local_model_guard_resume'))
            self.assertIn('"${connector_files[@]}" up -d', body)
            self.assertNotIn('activation.pins.json', body)


if __name__ == '__main__':
    unittest.main()
