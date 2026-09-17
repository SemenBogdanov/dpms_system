"""Refresh only the DPMS-owned tailnet table; never inspect container secrets."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from tailnet_connector_policy import render_policy
from install_activation import activation_allows_network, boot_id, load_state

CONFIG = Path('/etc/dpms/local-llm/connector.json')
QUARANTINE = '/etc/dpms/local-llm/tailscale-quarantine.nft'
SERVICES = ('backend', 'audit-worker')


def command(args, *, data=None):
    result = subprocess.run(args, input=data, capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError('command_failed')
    return result.stdout


def docker_clients():
    clients = []
    for service in SERVICES:
        ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=deploy',
                       '--filter', 'label=com.docker.compose.service=' + service]).split()
        if len(ids) > 1:
            raise ValueError('ambiguous_service')
        for cid in ids:
            template = '{{json .HostConfig.Privileged}}|{{json .HostConfig.NetworkMode}}|{{json .NetworkSettings.Networks}}'
            privileged, mode, networks = [json.loads(value) for value in command(
                ['docker', 'inspect', '--format', template, cid]).strip().split('|')]
            if privileged or mode == 'host' or set(networks) != {'deploy_default'}:
                raise ValueError('unexpected_container_network')
            network = networks['deploy_default']
            if network.get('GlobalIPv6Address'):
                raise ValueError('container_ipv6_requires_review')
            bridge = command(['docker', 'network', 'inspect', '--format',
                              '{{index .Options "com.docker.network.bridge.name"}}',
                              network['NetworkID']]).strip()
            if not bridge or bridge == '<no value>':
                bridge = 'br-' + network['NetworkID'][:12]
            clients.append({'interface': bridge, 'ipv4': network['IPAddress']})
    return clients


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('root_required')
    try:
        config = json.loads(CONFIG.read_text())
        if not config.get('enabled'):
            raise ValueError('not_enabled')
        state = json.loads(command(['tailscale', 'status', '--json']))
        if state.get('BackendState') != 'Running' or set(state['Self']['TailscaleIPs']) != set(config['vps_ips']):
            raise ValueError('vps_identity_changed')
        if state['Self'].get('Tags') != ['tag:dpms-local-llm']:
            raise ValueError('vps_tag_changed')
        clients = docker_clients()
        policy = render_policy(config['mac_ips'], config['vps_ips'], clients)
        command(['nft', '--check', '-f', '-'], data=policy)
        if not args.check:
            if not activation_allows_network(load_state(), boot_id(), time.time()):
                raise ValueError('activation_not_confirmed_or_expired')
            command(['nft', '-f', '-'], data=policy)
        print(json.dumps({'status': 'CHECKED' if args.check else 'APPLIED', 'client_count': len(clients)}))
    except Exception:
        closed = args.check
        if not args.check:
            for fallback in (['nft', '-f', QUARANTINE], ['tailscale', 'down']):
                try:
                    command(fallback)
                    closed = True
                    break
                except Exception:
                    pass
        print(json.dumps({'status': 'CHECK_FAILED' if args.check else
                          'FAIL_CLOSED' if closed else 'ISOLATION_FAILED'}))
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
