from pathlib import Path
import plistlib
import unittest

from launch_agent import definition, job_pid, service_status


class LaunchAgentTests(unittest.TestCase):
    def test_plist_has_no_inline_credential_and_no_restart_loop(self):
        result = definition("synthetic-model", Path("/synthetic/source"), Path("/synthetic/home"))
        encoded = plistlib.dumps(result)
        self.assertEqual(plistlib.loads(encoded), result)
        self.assertNotIn("BEARER", encoded.decode())
        self.assertFalse(result["KeepAlive"])
        self.assertTrue(result["RunAtLoad"])
        self.assertFalse(result["AbandonProcessGroup"])
        self.assertIn("DPMS_LOCAL_LLM_STATE_DIRECTORY", result["EnvironmentVariables"])
        self.assertEqual(result["ProgramArguments"], ["/synthetic/source/bin/dpms-macos-store", "run"])

    def test_invalid_model(self):
        for value in ("", "bad\nmodel", "x" * 201):
            with self.assertRaises(ValueError):
                definition(value)

    def test_running_requires_launchd_owned_listener(self):
        output = "job = {\n\tstate = running\n\tpid = 1234\n}\n"
        self.assertEqual(job_pid(output), 1234)
        self.assertEqual(service_status(output, {1234}), "RUNNING")
        self.assertEqual(service_status(output, set()), "STARTING")
        self.assertEqual(service_status(output, {5678}), "LISTENER_MISMATCH")
        self.assertEqual(service_status(output, {1234, 5678}), "LISTENER_MISMATCH")

    def test_orphaned_listener_is_not_a_running_service(self):
        output = "job = {\n\tstate = not running\n\tlast exit code = 3\n}\n"
        self.assertEqual(service_status(output, {5678}), "LISTENER_MISMATCH")
        self.assertEqual(service_status(output, set()), "NOT_RUNNING")
        self.assertEqual(service_status("", {5678}), "LISTENER_MISMATCH")

    def test_nested_state_cannot_masquerade_as_job_state(self):
        output = "job = {\n\tstate = not running\n\tresource = {\n\t\tstate = running\n\t\tpid = 1234\n\t}\n}\n"
        self.assertIsNone(job_pid(output))
        self.assertEqual(service_status(output, {1234}), "LISTENER_MISMATCH")

    def test_invalid_pid_is_not_running(self):
        for pid in ("", "0", "-1", "other"):
            self.assertIsNone(job_pid(f"job = {{\n\tstate = running\n\tpid = {pid}\n}}\n"))


if __name__ == "__main__":
    unittest.main()
