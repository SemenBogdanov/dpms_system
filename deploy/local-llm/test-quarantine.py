"""Linux/root smoke inside a disposable network namespace, never the host netns."""
import errno
import json
from pathlib import Path
import socket
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)


assert Path('/proc/self/ns/net').readlink() != Path('/proc/1/ns/net').readlink(), 'Run with unshare --net'
policy = Path(__file__).with_name('tailscale-quarantine.nft')
run('ip', 'link', 'set', 'lo', 'up')
run('ip', 'link', 'add', 'tailscale0', 'type', 'dummy')
run('ip', 'link', 'set', 'tailscale0', 'up')
run('ip', 'addr', 'add', '10.250.0.1/24', 'dev', 'tailscale0')
run('ip', '-6', 'addr', 'add', 'fd12:3456::1/64', 'dev', 'tailscale0', 'nodad')
run('nft', 'add', 'table', 'inet', 'unrelated_smoke_guard')
run('nft', '--check', '-f', str(policy))
run('nft', '-f', str(policy))
run('nft', '-f', str(policy))
run('nft', 'list', 'table', 'inet', 'unrelated_smoke_guard')


def output_packets():
    table = json.loads(run('nft', '-j', 'list', 'table', 'inet', 'dpms_llm_tailnet_guard'))
    output = next(item['rule'] for item in table['nftables']
                  if 'rule' in item and item['rule']['chain'] == 'output')
    return next(item['counter']['packets'] for item in output['expr'] if 'counter' in item)


for family, destination in ((socket.AF_INET, '10.250.0.2'), (socket.AF_INET6, 'fd12:3456::2')):
    before_packets = output_packets()
    with socket.socket(family, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        try:
            client.connect((destination, 8443))
        except OSError as exc:
            # ICMP rejection and blocked IPv6 neighbor discovery differ in errno.
            # Require a real guard hit for EACH family, not merely a failed socket.
            assert isinstance(exc, TimeoutError) or exc.errno in {errno.EACCES, errno.EHOSTUNREACH}, type(exc).__name__
        else:
            raise AssertionError('Quarantined interface accepted TCP')
    assert output_packets() > before_packets, 'Probe did not reach the quarantine guard'

with socket.socket() as server:
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    with socket.create_connection(server.getsockname(), timeout=1) as client:
        connection, _ = server.accept()
        with connection:
            client.sendall(b'ok')
            assert connection.recv(2) == b'ok'

table = json.loads(run('nft', '-j', 'list', 'table', 'inet', 'dpms_llm_tailnet_guard'))
rules = [item['rule'] for item in table['nftables'] if 'rule' in item]
assert len(rules) == 4, 'Reapplying must not duplicate rules'
output = next(rule for rule in rules if rule['chain'] == 'output')
packets = next(item['counter']['packets'] for item in output['expr'] if 'counter' in item)
assert packets >= 2
print(json.dumps({'status': 'PASS', 'isolated_netns': True, 'ipv4_blocked': True,
                  'ipv6_blocked': True, 'loopback_unchanged': True,
                  'unrelated_table_preserved': True, 'idempotent': True}))
