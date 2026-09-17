import unittest

from synthetic_vps_probe import REMOTE_CODE, ssh_command


class SyntheticVPSProbeTests(unittest.TestCase):
    def test_only_fixed_services_are_accepted(self):
        for service in ('other', 'backend; id', '../../backend', ''):
            with self.assertRaises(ValueError):
                ssh_command(service)

    def test_connection_and_remote_entrypoint_are_fixed(self):
        for service in ('backend', 'audit-worker'):
            command = ssh_command(service)
            self.assertEqual(command[0], '/usr/bin/ssh')
            self.assertEqual(command[-2], 'dpms-vps')
            self.assertIn('BatchMode=yes', command)
            self.assertTrue(command[-1].startswith(f'sudo -n docker exec -i deploy-{service}-1 python -c '))

    def test_remote_probe_uses_the_application_client_without_database_operations(self):
        compile(REMOTE_CODE, '<synthetic-vps-probe>', 'exec')
        self.assertIn('await generate_text(', REMOTE_CODE)
        self.assertIn('SYNTHETIC TEST, NOT A REAL DOCUMENT', REMOTE_CODE)
        for operation in ('db.commit', 'session.commit', 'create_engine', 'get_ready_ai_provider'):
            self.assertNotIn(operation, REMOTE_CODE)


if __name__ == '__main__':
    unittest.main()
