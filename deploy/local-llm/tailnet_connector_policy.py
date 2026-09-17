"""Pure renderer for the already-owned inet dpms_llm_tailnet_guard table.

Apply the complete result in one nft batch: delete/add is one atomic transaction.
The caller owns installation, rollback, and the 20-second refresh timer. Container
tuples expire after 90 seconds, including permission for established connections.
Both host address families are supported; containers are IPv4-only. All IPv6
forwarding involving tailscale0 is denied. Other interfaces remain unaffected.

Root and Docker administrators are trusted. Interface/address tuple matching does
not prevent same-host privileged spoofing or prove a container's identity.
"""

import ipaddress
import re


_TABLE = "inet dpms_llm_tailnet_guard"
_CLIENT_SET = "dpms_clients_v4"
_TAILNET_RANGES = {
    4: ipaddress.ip_network("100.64.0.0/10"),
    6: ipaddress.ip_network("fd7a:115c:a1e0::/48"),
}
_PRIVATE_V4_RANGES = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_IFNAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}", re.ASCII)
_NEW_SYN = "ct state new tcp flags & (fin | syn | rst | ack) == syn accept"
_REJECT = 'oifname "tailscale0" reject with icmpx type admin-prohibited'
_DROP = 'iifname "tailscale0" drop'


def _parse_address(value):
    if not isinstance(value, str) or not value.isascii() or "%" in value:
        raise ValueError("IP addresses must be plain, unscoped strings")
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("Invalid IP address") from None


def _tailnet_addresses(values, label):
    if not isinstance(values, list) or not 1 <= len(values) <= 2:
        raise ValueError(f"{label} must contain one address per configured family")
    addresses = {}
    for value in values:
        address = _parse_address(value)
        if address not in _TAILNET_RANGES[address.version]:
            raise ValueError(f"{label} must use Tailscale address ranges")
        if address.version in addresses:
            raise ValueError(f"{label} must not repeat an address family")
        addresses[address.version] = address
    return addresses


def _client_tuples(clients):
    if not isinstance(clients, list):
        raise ValueError("clients must be a list")
    tuples = set()
    for client in clients:
        if not isinstance(client, dict) or set(client) != {"interface", "ipv4"}:
            raise ValueError("Each client must have exactly interface and ipv4")
        interface = client["interface"]
        if (
            not isinstance(interface, str)
            or _IFNAME.fullmatch(interface) is None
            or interface == "tailscale0"
        ):
            raise ValueError("Client interface must be a safe, non-tailnet ifname")
        address = _parse_address(client["ipv4"])
        if address.version != 4 or not any(
            address in network for network in _PRIVATE_V4_RANGES
        ):
            raise ValueError("Client ipv4 must be an RFC1918 IPv4 address")
        entry = (interface, address)
        if entry in tuples:
            raise ValueError("Duplicate client tuple")
        tuples.add(entry)
    return sorted(tuples, key=lambda entry: (entry[0], int(entry[1])))


def render_policy(
    mac_ips: list[str], vps_ips: list[str], clients: list[dict[str, str]]
) -> str:
    """Return a deterministic nft batch, or raise ValueError for invalid input.

    Host lists must be nonempty and have matching families, at most one IP each.
    Nonempty clients require IPv4 hosts; an empty client list denies forwarding.
    No input is mutated and no filesystem, process, or network access occurs.
    """
    mac = _tailnet_addresses(mac_ips, "mac_ips")
    vps = _tailnet_addresses(vps_ips, "vps_ips")
    if mac.keys() != vps.keys():
        raise ValueError("Mac and VPS address families must match")
    tuples = _client_tuples(clients)
    if tuples and 4 not in mac:
        raise ValueError("IPv4 clients require matching IPv4 host addresses")

    lines = [
        f"delete table {_TABLE}",
        f"add table {_TABLE}",
        f"add set {_TABLE} {_CLIENT_SET} "
        "{ type ifname . ipv4_addr; flags timeout; timeout 90s; }",
    ]
    if tuples:
        elements = ", ".join(f'"{interface}" . {address}' for interface, address in tuples)
        lines.append(f"add element {_TABLE} {_CLIENT_SET} {{ {elements} }}")
    for chain in ("input", "output", "forward"):
        lines.append(
            f"add chain {_TABLE} {chain} "
            f"{{ type filter hook {chain} priority -10; policy accept; }}"
        )

    for family in sorted(mac):
        protocol = "ip" if family == 4 else "ip6"
        original = (
            f'add rule {_TABLE} output oifname "tailscale0" '
            f"{protocol} saddr {vps[family]} {protocol} daddr {mac[family]} "
            "tcp dport 443 ct direction original "
        )
        lines.extend((original + _NEW_SYN, original + "ct state established accept"))
        lines.append(
            f'add rule {_TABLE} input iifname "tailscale0" '
            f"{protocol} saddr {mac[family]} {protocol} daddr {vps[family]} "
            "tcp sport 443 ct direction reply ct state established accept"
        )

    if tuples:
        original = (
            f"add rule {_TABLE} forward iifname . ip saddr @{_CLIENT_SET} "
            f'oifname "tailscale0" ip daddr {mac[4]} '
            "tcp dport 443 ct direction original "
        )
        lines.extend((original + _NEW_SYN, original + "ct state established accept"))
        lines.append(
            f'add rule {_TABLE} forward iifname "tailscale0" '
            f"oifname . ip daddr @{_CLIENT_SET} ip saddr {mac[4]} "
            "tcp sport 443 ct direction reply ct state established accept"
        )

    # Catch every remaining tailnet packet, including invalid/untracked traffic.
    # Drop incoming traffic first, so tailnet-to-tailnet forwarding cannot reply.
    lines.extend((
        f"add rule {_TABLE} input {_DROP}",
        f"add rule {_TABLE} output {_REJECT}",
        f"add rule {_TABLE} forward {_DROP}",
        f"add rule {_TABLE} forward {_REJECT}",
    ))
    return "\n".join(lines) + "\n"
