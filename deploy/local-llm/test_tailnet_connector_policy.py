"""Offline renderer regressions; the parent validates the batch with nft --check."""

from copy import deepcopy
import unittest

from tailnet_connector_policy import render_policy


TABLE = "inet dpms_llm_tailnet_guard"
MAC4 = "100.100.0.10"
HOST4 = "100.100.0.20"
MAC6 = "fd7a:115c:a1e0::10"
HOST6 = "fd7a:115c:a1e0::20"
CLIENTS = [
    {"interface": "br-dpms", "ipv4": "172.20.0.2"},
    {"interface": "docker0", "ipv4": "10.20.0.3"},
]
NEW_SYN = "ct state new tcp flags & (fin | syn | rst | ack) == syn accept"
DROP = 'iifname "tailscale0" drop'
REJECT = 'oifname "tailscale0" reject with icmpx type admin-prohibited'


def rules_for(policy, chain):
    prefix = f"add rule {TABLE} {chain} "
    return [line[len(prefix):] for line in policy.splitlines() if line.startswith(prefix)]


class PolicyRenderingTests(unittest.TestCase):
    def setUp(self):
        self.policy = render_policy([MAC4, MAC6], [HOST4, HOST6], CLIENTS)

    def test_atomic_replacement_scoped_to_owned_table(self):
        lines = self.policy.splitlines()
        self.assertEqual(lines[:2], [f"delete table {TABLE}", f"add table {TABLE}"])
        self.assertEqual(sum(line.startswith("delete ") for line in lines), 1)
        self.assertNotIn("flush", self.policy)
        for line in lines:
            parts = line.split()
            self.assertIn(parts[0], ("delete", "add"))
            self.assertIn(parts[1], ("table", "set", "element", "chain", "rule"))
            self.assertEqual(parts[2:4], ["inet", "dpms_llm_tailnet_guard"])
        self.assertTrue(self.policy.isascii())
        self.assertTrue(self.policy.endswith("\n"))

    def test_hooks_preserve_unrelated_interfaces(self):
        declarations = [line for line in self.policy.splitlines() if line.startswith("add chain ")]
        self.assertEqual(declarations, [
            f"add chain {TABLE} {chain} "
            f"{{ type filter hook {chain} priority -10; policy accept; }}"
            for chain in ("input", "output", "forward")
        ])
        for chain in ("input", "output", "forward"):
            for rule in rules_for(self.policy, chain):
                self.assertIn('"tailscale0"', rule)

    def test_host_output_exact_original_new_syn_or_established_both_families(self):
        self.assertEqual(rules_for(self.policy, "output"), [
            f'oifname "tailscale0" ip saddr {HOST4} ip daddr {MAC4} '
            f"tcp dport 443 ct direction original {NEW_SYN}",
            f'oifname "tailscale0" ip saddr {HOST4} ip daddr {MAC4} '
            "tcp dport 443 ct direction original ct state established accept",
            f'oifname "tailscale0" ip6 saddr {HOST6} ip6 daddr {MAC6} '
            f"tcp dport 443 ct direction original {NEW_SYN}",
            f'oifname "tailscale0" ip6 saddr {HOST6} ip6 daddr {MAC6} '
            "tcp dport 443 ct direction original ct state established accept",
            REJECT,
        ])

    def test_host_input_exact_established_reply_only_both_families(self):
        self.assertEqual(rules_for(self.policy, "input"), [
            f'iifname "tailscale0" ip saddr {MAC4} ip daddr {HOST4} '
            "tcp sport 443 ct direction reply ct state established accept",
            f'iifname "tailscale0" ip6 saddr {MAC6} ip6 daddr {HOST6} '
            "tcp sport 443 ct direction reply ct state established accept",
            DROP,
        ])

    def test_forward_exact_tuples_in_both_directions_and_states(self):
        self.assertEqual(rules_for(self.policy, "forward"), [
            'iifname . ip saddr @dpms_clients_v4 oifname "tailscale0" '
            f"ip daddr {MAC4} tcp dport 443 ct direction original {NEW_SYN}",
            'iifname . ip saddr @dpms_clients_v4 oifname "tailscale0" '
            f"ip daddr {MAC4} tcp dport 443 ct direction original ct state established accept",
            'iifname "tailscale0" oifname . ip daddr @dpms_clients_v4 '
            f"ip saddr {MAC4} tcp sport 443 ct direction reply ct state established accept",
            DROP,
            REJECT,
        ])

    def test_all_container_permissions_depend_on_expiring_tuple_set(self):
        declarations = [line for line in self.policy.splitlines() if line.startswith("add set ")]
        self.assertEqual(declarations, [
            f"add set {TABLE} dpms_clients_v4 "
            "{ type ifname . ipv4_addr; flags timeout; timeout 90s; }",
        ])
        elements = [line for line in self.policy.splitlines() if line.startswith("add element ")]
        self.assertEqual(elements, [
            f"add element {TABLE} dpms_clients_v4 "
            '{ "br-dpms" . 172.20.0.2, "docker0" . 10.20.0.3 }',
        ])
        for rule in rules_for(self.policy, "forward"):
            if rule.endswith(" accept"):
                self.assertIn("@dpms_clients_v4", rule)
        self.assertNotIn("update @", self.policy)
        self.assertNotIn("add @", self.policy)

    def test_no_general_conntrack_or_non_tcp_accepts(self):
        accepts = [line for line in self.policy.splitlines() if line.endswith(" accept")]
        self.assertEqual(len(accepts), 9)
        for line in accepts:
            self.assertRegex(line, r" tcp (sport|dport) 443 ct direction (original|reply) ")
            self.assertNotIn("related", line)
            self.assertNotIn("invalid", line)
            self.assertNotIn("untracked", line)
            if "ct state new" in line:
                self.assertTrue(line.endswith(NEW_SYN))
                self.assertIn("ct direction original", line)
            else:
                self.assertTrue(line.endswith("ct state established accept"))

    def test_terminal_guards_cover_invalid_untracked_and_ipv6(self):
        self.assertEqual(rules_for(self.policy, "input")[-1:], [DROP])
        self.assertEqual(rules_for(self.policy, "output")[-1:], [REJECT])
        self.assertEqual(rules_for(self.policy, "forward")[-2:], [DROP, REJECT])
        for rule in rules_for(self.policy, "forward"):
            if rule.endswith(" accept"):
                self.assertIn(" . ip ", rule)
                self.assertIn(f"ip daddr {MAC4}" if "original" in rule else f"ip saddr {MAC4}", rule)
                self.assertNotIn("ip6", rule)

    def test_empty_clients_deny_all_forwarding_but_keep_host_access(self):
        policy = render_policy([MAC4, MAC6], [HOST4, HOST6], [])
        self.assertNotIn("add element ", policy)
        self.assertIn("type ifname . ipv4_addr; flags timeout; timeout 90s;", policy)
        self.assertEqual(rules_for(policy, "forward"), [DROP, REJECT])
        for chain in ("input", "output"):
            self.assertEqual(rules_for(policy, chain), rules_for(self.policy, chain))

    def test_single_family_hosts(self):
        for mac, host, protocol in ((MAC4, HOST4, "ip"), (MAC6, HOST6, "ip6")):
            with self.subTest(protocol=protocol):
                policy = render_policy([mac], [host], [])
                output = rules_for(policy, "output")
                incoming = rules_for(policy, "input")
                self.assertEqual(len(output), 3)
                self.assertEqual(len(incoming), 2)
                self.assertIn(f"{protocol} saddr {host} {protocol} daddr {mac}", output[0])
                self.assertIn(f"{protocol} saddr {mac} {protocol} daddr {host}", incoming[0])
                self.assertEqual(rules_for(policy, "forward"), [DROP, REJECT])

    def test_ipv4_only_hosts_allow_ipv4_clients(self):
        policy = render_policy([MAC4], [HOST4], CLIENTS)
        self.assertEqual(rules_for(policy, "forward"), rules_for(self.policy, "forward"))
        self.assertNotIn("ip6", policy)

    def test_canonical_deterministic_output_without_input_mutation(self):
        args = (
            ["FD7A:115C:A1E0:0000:0000:0000:0000:0010", MAC4],
            [HOST6, HOST4],
            list(reversed(deepcopy(CLIENTS))),
        )
        before = deepcopy(args)
        self.assertEqual(render_policy(*args), self.policy)
        self.assertEqual(args, before)
        self.assertEqual(render_policy(*args), self.policy)

    def test_overlapping_container_subnets_stay_distinct_tuples(self):
        clients = [
            {"interface": "br-b", "ipv4": "172.20.0.2"},
            {"interface": "br-a", "ipv4": "172.20.0.10"},
            {"interface": "br-a", "ipv4": "172.20.0.2"},
        ]
        policy = render_policy([MAC4], [HOST4], clients)
        self.assertIn(
            '{ "br-a" . 172.20.0.2, "br-a" . 172.20.0.10, "br-b" . 172.20.0.2 }',
            policy,
        )


class PolicyValidationTests(unittest.TestCase):
    def assert_bad_hosts(self, mac, host):
        with self.assertRaises(ValueError):
            render_policy(mac, host, [])

    def assert_bad_client(self, client):
        with self.assertRaises(ValueError):
            render_policy([MAC4], [HOST4], [client])

    def test_host_collections_must_be_nonempty_lists(self):
        for bad in (None, MAC4, (MAC4,), {MAC4}, {"ipv4": MAC4}, [], [MAC4, MAC6, HOST4]):
            with self.subTest(value=bad):
                self.assert_bad_hosts(bad, [HOST4])
                self.assert_bad_hosts([MAC4], bad)

    def test_invalid_addresses_types_scopes_and_injection(self):
        invalid = (
            None, True, 1, 1681915914, b"100.100.0.10", [], {},
            "", " 100.100.0.10", "100.100.0.10\n", "100.100.0.10\x00",
            "100.100.000.10", "100.100.0.256", "100.100.0.10/32", "100.100.0.10:443",
            "100.100.0.10-100.100.0.20", "100.100.0.10, 100.100.0.20", "*", "localhost",
            "[fd7a:115c:a1e0::10]", "fd7a:115c:a1e0::10/128", "fd7a:115c:a1e0::gg",
            "fd7a:115c:a1e0::10%tailscale0", "fd7a:115c:a1e0::10%1",
            "fd7a:115c:a1e0::10%\"; flush ruleset; #",
            "100.100.0.10; flush ruleset", '100.100.0.10" accept; #',
            "100.100.0.10\nadd rule inet other input accept",
            "$(id)", "`id`", "\u0661\u0660\u0660.100.0.10",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assert_bad_hosts([value], [HOST4])
                self.assert_bad_hosts([MAC4], [value])
                self.assert_bad_client({"interface": "br-dpms", "ipv4": value})

    def test_host_ranges_are_exact_not_merely_private(self):
        invalid = (
            "100.63.255.255", "100.128.0.0", "10.0.0.1", "172.16.0.1", "192.168.0.1",
            "127.0.0.1", "169.254.1.1", "192.0.2.1", "0.0.0.0", "224.0.0.1",
            "fd7a:115c:a1df:ffff:ffff:ffff:ffff:ffff", "fd7a:115c:a1e1::",
            "fd00::1", "fe80::1", "::1", "::", "2001:db8::1", "ff02::1",
            "::ffff:100.100.0.10",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assert_bad_hosts([value], [value])

    def test_tailnet_range_boundaries(self):
        for mac, host in (
            ("100.64.0.0", "100.127.255.255"),
            ("fd7a:115c:a1e0::", "fd7a:115c:a1e0:ffff:ffff:ffff:ffff:ffff"),
        ):
            with self.subTest(mac=mac):
                policy = render_policy([mac], [host], [])
                self.assertIn(f"saddr {host}", policy)
                self.assertIn(f"daddr {mac}", policy)

    def test_duplicate_host_families_rejected_even_for_identical_addresses(self):
        for values in (
            [MAC4, MAC4], [MAC4, HOST4], [MAC6, HOST6],
            [MAC6, "FD7A:115C:A1E0:0:0:0:0:10"],
        ):
            with self.subTest(values=values):
                self.assert_bad_hosts(values, [HOST4, HOST6])
                self.assert_bad_hosts([MAC4, MAC6], values)

    def test_host_families_must_match_exactly(self):
        for mac, host in (
            ([MAC4], [HOST6]), ([MAC6], [HOST4]),
            ([MAC4, MAC6], [HOST4]), ([MAC4], [HOST4, HOST6]),
            ([MAC4, MAC6], [HOST6]), ([MAC6], [HOST4, HOST6]),
        ):
            with self.subTest(mac=mac, host=host):
                self.assert_bad_hosts(mac, host)

    def test_ipv4_clients_require_ipv4_hosts(self):
        with self.assertRaises(ValueError):
            render_policy([MAC6], [HOST6], CLIENTS)

    def test_client_collection_and_schema(self):
        for clients in (None, "", {}, tuple(CLIENTS)):
            with self.subTest(clients=clients), self.assertRaises(ValueError):
                render_policy([MAC4], [HOST4], clients)
        for client in (
            None, "172.20.0.2", [], ("br-dpms", "172.20.0.2"), {},
            {"interface": "br-dpms"}, {"ipv4": "172.20.0.2"},
            {"interface": "br-dpms", "ipv4": "172.20.0.2", "ipv6": MAC6},
        ):
            with self.subTest(client=client):
                self.assert_bad_client(client)

    def test_ifname_rejects_injection_wildcards_and_tailnet_hairpin(self):
        invalid = (
            None, True, 1, [], {}, b"docker0", "", ".", "..", "a" * 16,
            "tailscale0", "br+", "br*", "br/a", "br:a", "br a", "br\ta", "br\na",
            "br-a\n", "br\x00a", "br\\a", "br\"a", "br'a", ";accept", "@clients",
            'br" . 172.20.0.2 }; flush ruleset; #', "$(id)", "`id`", "br-\u00e9",
        )
        for interface in invalid:
            with self.subTest(interface=interface):
                self.assert_bad_client({"interface": interface, "ipv4": "172.20.0.2"})

    def test_safe_ifnames_including_linux_length_boundary(self):
        for interface in ("docker0", "br-0123456789ab", "veth_a.1", "a" * 15):
            with self.subTest(interface=interface):
                policy = render_policy(
                    [MAC4], [HOST4], [{"interface": interface, "ipv4": "172.20.0.2"}]
                )
                self.assertIn(f'"{interface}" . 172.20.0.2', policy)

    def test_clients_require_rfc1918_not_ipaddress_is_private(self):
        for address in (
            "9.255.255.255", "11.0.0.0", "172.15.255.255", "172.32.0.0",
            "192.167.255.255", "192.169.0.0", "100.100.0.10", "127.0.0.1",
            "169.254.1.1", "192.0.2.1", "198.18.0.1", "0.0.0.0", "224.0.0.1",
            "255.255.255.255", MAC6, "fd00::1", "::ffff:172.20.0.2",
        ):
            with self.subTest(address=address):
                self.assert_bad_client({"interface": "br-dpms", "ipv4": address})

    def test_all_three_rfc1918_ranges_and_boundaries(self):
        for address in (
            "10.0.0.0", "10.255.255.255", "172.16.0.0", "172.31.255.255",
            "192.168.0.0", "192.168.255.255",
        ):
            with self.subTest(address=address):
                policy = render_policy(
                    [MAC4], [HOST4], [{"interface": "br-dpms", "ipv4": address}]
                )
                self.assertIn(f'"br-dpms" . {address}', policy)

    def test_duplicate_client_tuple_is_rejected(self):
        with self.assertRaises(ValueError):
            render_policy([MAC4], [HOST4], [CLIENTS[0], deepcopy(CLIENTS[0])])

    def test_validation_errors_do_not_echo_untrusted_payload(self):
        payload = 'bad"; flush ruleset; #'
        for mac, host, clients in (
            ([payload], [HOST4], []),
            ([MAC4], [payload], []),
            ([MAC4], [HOST4], [{"interface": payload, "ipv4": "172.20.0.2"}]),
            ([MAC4], [HOST4], [{"interface": "br-dpms", "ipv4": payload}]),
        ):
            with self.subTest(mac=mac, host=host, clients=clients):
                with self.assertRaises(ValueError) as caught:
                    render_policy(mac, host, clients)
                self.assertNotIn(payload, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
