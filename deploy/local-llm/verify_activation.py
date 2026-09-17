"""Bounded network checks. No credentials, prompts, or database operations."""

import argparse
import json
from pathlib import Path
import socket
import ssl
import subprocess

CONFIG = Path('/etc/dpms/local-llm/connector.json')
CLIENT = r'''
import json,socket,ssl,sys
request=json.load(sys.stdin)
try:
    with socket.create_connection((request['address'],443),timeout=3) as sock:
        if request['blocked']:
            result={'status':'FAIL','connected':True}
        else:
            with ssl.create_default_context().wrap_socket(sock,server_hostname=request['host']) as tls:
                tls.sendall(('GET /v1/models HTTP/1.1\r\nHost: '+request['host']+'\r\nConnection: close\r\n\r\n').encode())
                code=int(tls.recv(128).split(b' ')[1])
                result={'status':'PASS' if code==request['expected_http'] else 'FAIL','http':code}
except OSError:
    result={'status':'PASS' if request['blocked'] else 'FAIL','connected':False}
print(json.dumps(result))
'''


def probe(address, host, blocked=False, expected_http=401, service=None):
    payload = {'address': address, 'host': host, 'blocked': blocked, 'expected_http': expected_http}
    args = ['python3', '-c', CLIENT] if service is None else [
        'docker', 'exec', '-i', 'deploy-' + service + '-1', 'python', '-c', CLIENT]
    result = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, timeout=8)
    if result.returncode:
        return {'status': 'FAIL', 'code': 'probe_process_failed'}
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scope', choices=['host', 'quarantine', 'containers', 'unavailable', 'settings'])
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    checks = []
    if args.scope == 'settings':
        inventory = json.loads(CONFIG.with_name('inventory.json').read_text())
        overlay = json.loads(CONFIG.with_name('connector.override.json').read_text())
        active = CONFIG.with_name('compose-activated').exists()
        for service in ('backend', 'audit-worker'):
            container = 'deploy-' + service + '-1'
            expected = overlay['services'][service]['environment']['AI_PROVIDER_ALLOWED_ORIGINS'] if active else inventory['services'][service]['origins']
            command = ['docker', 'exec', container, 'python', '-c',
                       "import os; print(os.environ.get('AI_PROVIDER_ALLOWED_ORIGINS',''))"]
            origins = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5).stdout.strip()
            image = subprocess.run(['docker', 'inspect', '--format', '{{.Image}}', container],
                                   capture_output=True, text=True, check=True, timeout=5).stdout.strip()
            checks.append({'check': service + '_origins', 'status': 'PASS' if origins == expected else 'FAIL'})
            checks.append({'check': service + '_image', 'status': 'PASS' if image == inventory['services'][service]['image_id'] else 'FAIL'})
    elif args.scope in ('host', 'quarantine'):
        for address in config['mac_ips']:
            result = probe(address, config['host'], blocked=args.scope == 'quarantine')
            checks.append({'check': 'https_ipv6' if ':' in address else 'https_ipv4', **result})
            for port in (22, 80, 8080, 18080):
                try:
                    with socket.create_connection((address, port), timeout=2):
                        blocked = False
                except OSError:
                    blocked = True
                checks.append({'check': 'management_blocked', 'status': 'PASS' if blocked else 'FAIL'})
    else:
        for service in ('backend', 'audit-worker'):
            result = probe(config['host'], config['host'], service=service,
                           expected_http=502 if args.scope == 'unavailable' else 401)
            checks.append({'check': service + '_dns_tls', **result})
        for service in ('email-worker', 'deadline-worker'):
            for address in config['mac_ips']:
                checks.append({'check': service + '_isolated',
                               **probe(address, config['host'], service=service, blocked=True)})
    result = {'status': 'PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL', 'checks': checks}
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'PASS' else 2)


if __name__ == '__main__':
    main()
