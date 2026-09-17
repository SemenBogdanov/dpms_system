import unittest

from policy_checks import lint_policy_tests


class PolicyChecksTests(unittest.TestCase):
    def policy(self, source="192.0.2.1", target="192.0.2.2:443", decision="accept"):
        return {
            "grants": [{"src": ["*"], "dst": ["*"], "ip": ["tcp:1-442", "tcp:444-65535", "udp:*", "1:*", "58:*"]}],
            "tests": [{"src": source, "proto": "tcp", decision: [target]}],
        }

    def test_valid_ipv4(self):
        result = lint_policy_tests(self.policy())
        self.assertEqual(result, {"tests": 1, "ipv4_tests": 1, "ipv6_tests": 0, "assertions": 1})

    def test_valid_ipv6(self):
        result = lint_policy_tests(self.policy("2001:db8::1", "[2001:db8::2]:443"))
        self.assertEqual(result["ipv6_tests"], 1)

    def test_both_families_and_decisions_retained(self):
        policy = self.policy()
        policy["tests"] += self.policy("2001:db8::1", "[2001:db8::2]:22", "deny")["tests"]
        self.assertEqual(lint_policy_tests(policy)["assertions"], 2)

    def test_cross_family_accept_and_deny_are_invalid(self):
        for source, target in [("192.0.2.1", "[2001:db8::2]:443"), ("2001:db8::1", "192.0.2.2:443")]:
            for decision in ("accept", "deny"):
                with self.subTest(source_family=":" in source, decision=decision):
                    with self.assertRaisesRegex(ValueError, "cross_family_test_pair"):
                        lint_policy_tests(self.policy(source, target, decision))

    def test_invalid_port_ranges(self):
        for capability in ("tcp:0-442", "tcp:0", "tcp:65536", "tcp:444-443", "tcp:1-2-3"):
            with self.subTest(capability=capability):
                policy = self.policy()
                policy["grants"][0]["ip"] = [capability]
                with self.assertRaisesRegex(ValueError, "invalid_port_range"):
                    lint_policy_tests(policy)

    def test_invalid_test_ports(self):
        for target in ("192.0.2.2:0", "192.0.2.2:65536", "192.0.2.2"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                lint_policy_tests(self.policy(target=target))

    def test_empty_tests_rejected(self):
        policy = self.policy()
        policy["tests"] = []
        with self.assertRaisesRegex(ValueError, "missing_tests"):
            lint_policy_tests(policy)

    def test_malformed_destination_rejected(self):
        for target in ("[2001:db8::2:443", "192.0.2.2:443/path", "user@192.0.2.2:443"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                lint_policy_tests(self.policy(target=target))


if __name__ == "__main__":
    unittest.main()
