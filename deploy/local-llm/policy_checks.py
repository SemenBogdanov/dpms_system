"""Offline port/test-family lint; not a Tailscale policy compiler."""

import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


def lint_policy_tests(policy):
    for grant in policy["grants"]:
        for capability in grant["ip"]:
            ports = capability.split(":", 1)[-1]
            if ports == "*":
                continue
            try:
                bounds = [int(part) for part in ports.split("-")]
            except ValueError:
                raise ValueError("invalid_port_range") from None
            if len(bounds) not in (1, 2) or not 1 <= bounds[0] <= bounds[-1] <= 65535:
                raise ValueError("invalid_port_range")

    counts = {"tests": 0, "ipv4_tests": 0, "ipv6_tests": 0, "assertions": 0}
    for test in policy["tests"]:
        if test.get("proto") not in {"tcp", "udp"}:
            raise ValueError("only_explicit_tcp_udp_tests_supported")
        family = ipaddress.ip_address(test["src"]).version
        assertions = 0
        for decision in ("accept", "deny"):
            for destination in test.get(decision, []):
                target = urlsplit("//" + destination)
                if target.username is not None or target.password is not None or target.path or target.query or target.fragment:
                    raise ValueError("invalid_test_destination")
                if target.port is None or not 1 <= target.port <= 65535:
                    raise ValueError("invalid_test_port")
                if ipaddress.ip_address(target.hostname).version != family:
                    raise ValueError("cross_family_test_pair")
                assertions += 1
        if not assertions:
            raise ValueError("empty_test")
        counts["tests"] += 1
        counts[f"ipv{family}_tests"] += 1
        counts["assertions"] += assertions
    if not counts["tests"]:
        raise ValueError("missing_tests")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    args = parser.parse_args()
    try:
        counts = lint_policy_tests(json.loads(args.policy.read_text()))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({"status": "FAIL", "scope": "offline_port_and_family_checks"}))
        raise SystemExit(2) from None
    print(json.dumps({"status": "PASS", "scope": "offline_port_and_family_checks", **counts,
                      "control_plane_validation": "NOT_RUN"}))


if __name__ == "__main__":
    main()
