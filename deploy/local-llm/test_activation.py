import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_activation as activation


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)
        self.patcher = patch.object(activation, 'CONFIG', self.config)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        inventory = {'services': {service: {'image_id': 'sha256:' + ('a' if service == 'backend' else 'b') * 64}
                                  for service in activation.SERVICES}}
        (self.config / 'inventory.json').write_text(json.dumps(inventory))
        (self.config / 'activation.pins.json').write_text(json.dumps({'services': {
            service: {'image': data['image_id']} for service, data in inventory['services'].items()
        }}))

    def test_trial_boot_and_deadline(self):
        state = {'phase': 'trial', 'boot_id': 'old', 'expires_at': 101}
        self.assertTrue(activation.activation_allows_network(state, 'old', 100))
        self.assertFalse(activation.activation_allows_network(state, 'new', 100))
        self.assertFalse(activation.activation_allows_network(state, 'old', 101))
        self.assertFalse(activation.activation_allows_network({}, 'old', 100))
        self.assertTrue(activation.activation_allows_network({'phase': 'confirmed'}, 'new', 500))

    def test_only_pinned_images_for_activation_and_rollback(self):
        for enabled in (True, False):
            command = activation.pinned_compose(enabled)
            self.assertEqual(command[-2:], ['-f', str(self.config / 'activation.pins.json')])
            self.assertEqual(str(self.config / 'connector.override.json') in command, enabled)
        (self.config / 'activation.pins.json').write_text('{"services":{}}')
        with self.assertRaises(ValueError):
            activation.pinned_compose(True)

    def test_stale_timer_cannot_rollback_confirmed_or_new_trial(self):
        for state in ({'phase': 'confirmed', 'trial_id': 'old'},
                      {'phase': 'trial', 'trial_id': 'new'}):
            activation.save_state(state)
            with patch.object(activation, 'run') as command:
                self.assertEqual(activation.rollback('old')['status'], 'ROLLBACK_NOT_NEEDED')
                command.assert_not_called()

    def test_firewall_failure_still_restores_containers(self):
        activation.save_state({'phase': 'trial', 'trial_id': 'current'})
        (self.config / 'compose-activated').touch()

        def command(args, **kwargs):
            if args[0] == 'nft':
                raise RuntimeError('synthetic failure')
            return ''

        with patch.object(activation, 'run', side_effect=command) as run, \
                patch.object(activation, 'verify_images'), \
                patch.object(activation, 'recreate') as recreate:
            result = activation.rollback('current')
            recreate.assert_called_once_with(False)
            run.assert_any_call(['tailscale', 'down'])
        self.assertEqual(result['status'], 'ROLLBACK_FAILED')
        self.assertFalse((self.config / 'compose-activated').exists())
        self.assertFalse(activation.activation_allows_network(activation.load_state(), 'new', 0))

    def test_container_failure_keeps_restore_marker(self):
        (self.config / 'compose-activated').touch()
        with patch.object(activation, 'run'), patch.object(activation, 'verify_images'), \
                patch.object(activation, 'recreate', side_effect=RuntimeError):
            result = activation.rollback()
        self.assertIn('container_restore_failed', result['errors'])
        self.assertTrue((self.config / 'compose-activated').exists())

    def test_later_app_release_is_never_downgraded_by_connector_rollback(self):
        (self.config / 'compose-activated').touch()
        with patch.object(activation, 'run'), patch.object(activation, 'verify_images', side_effect=ValueError), \
                patch.object(activation, 'recreate') as recreate:
            result = activation.rollback()
            recreate.assert_not_called()
        self.assertIn('container_restore_failed', result['errors'])

    def test_missing_trial_container_is_restored_from_pinned_image(self):
        activation.save_state({'phase': 'trial', 'trial_id': 'current'})
        (self.config / 'compose-activated').touch()

        def command(args, **kwargs):
            if args[:2] == ['docker', 'ps']:
                return '' if 'backend' in args[-1] else 'worker-id'
            if args[:2] == ['docker', 'inspect']:
                return 'sha256:' + 'b' * 64
            return ''

        with patch.object(activation, 'run', side_effect=command), patch.object(activation, 'recreate') as recreate:
            result = activation.rollback('current')
            recreate.assert_called_once_with(False)
        self.assertEqual(result['status'], 'ROLLED_BACK')

    def test_missing_container_does_not_allow_mismatched_existing_image(self):
        def command(args, **kwargs):
            if args[:2] == ['docker', 'ps']:
                return '' if 'backend' in args[-1] else 'worker-id'
            return 'sha256:' + 'c' * 64

        with patch.object(activation, 'run', side_effect=command), self.assertRaises(ValueError):
            activation.verify_images(allow_missing=True)

    def test_expired_trial_cannot_recreate_or_confirm(self):
        activation.save_state({'phase': 'trial', 'boot_id': 'old', 'expires_at': 1})
        with patch.object(activation, 'boot_id', return_value='old'), patch.object(activation, 'recreate') as recreate:
            for action in (activation.activate_containers, activation.confirm):
                with self.assertRaises(ValueError):
                    action()
            recreate.assert_not_called()

    def test_state_persisted_restrictively(self):
        activation.save_state({'phase': 'trial'})
        self.assertEqual((self.config / 'activation-state.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(activation.load_state()['phase'], 'trial')


if __name__ == '__main__':
    unittest.main()
