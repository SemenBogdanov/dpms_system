"""Build ignored, non-credential activation data from selected runtime metadata."""

import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent
REMOTE = r'''
import json,subprocess
def run(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=15)
 if r.returncode:raise RuntimeError('inventory_failed')
 return r.stdout
state=json.loads(run(['tailscale','status','--json']))
result={'vps_ips':state['Self']['TailscaleIPs'],'tags':state['Self'].get('Tags',[]),'services':{}}
for service in ('backend','audit-worker'):
 name='deploy-'+service+'-1'
 template='{{json .Image}}|{{json .Config.Image}}'
 image_id,image=json.loads('['+run(['sudo','-n','docker','inspect','--format',template,name]).strip().replace('|',',')+']')
 inner="import json,os; print(json.dumps(os.environ.get('AI_PROVIDER_ALLOWED_ORIGINS','')))"
 origins=json.loads(run(['sudo','-n','docker','exec',name,'python','-c',inner]))
 result['services'][service]={'image_id':image_id,'image':image,'origins':origins}
print(json.dumps(result))
'''


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(value, output, indent=2)
        output.write('\n')


def main():
    state = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True,
                                      text=True, check=True, timeout=5).stdout)
    host = state['Self']['DNSName'].rstrip('.')
    if not host.endswith('.ts.net') or host not in state.get('CertDomains', []):
        raise ValueError('certificate_not_ready')
    remote = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                             'dpms-vps', 'python3 -c ' + shlex.quote(REMOTE)], capture_output=True,
                            text=True, check=True, timeout=45)
    inventory = json.loads(remote.stdout)
    if inventory['tags'] != ['tag:dpms-local-llm']:
        raise ValueError('unexpected_vps_identity')
    mac_ips = state['Self']['TailscaleIPs']
    mac_v4 = next(value for value in mac_ips if ipaddress.ip_address(value).version == 4)
    origin = 'https://' + host
    override = {'services': {}}
    for service, data in inventory['services'].items():
        origins = [value.strip() for value in data['origins'].split(',') if value.strip()]
        if origin not in origins:
            origins.append(origin)
        override['services'][service] = {
            'environment': {'AI_PROVIDER_ALLOWED_ORIGINS': ','.join(origins)},
            'extra_hosts': {host: mac_v4},
        }
    runtime = ROOT / 'runtime' / 'activation'
    runtime.mkdir(mode=0o700)
    write_private(runtime / 'connector.json', {'enabled': True, 'host': host, 'mac_ips': mac_ips,
                                              'vps_ips': inventory['vps_ips']})
    write_private(runtime / 'connector.override.json', override)
    write_private(runtime / 'inventory.json', inventory)
    write_private(runtime / 'activation.pins.json', {'services': {
        service: {'image': data['image_id']} for service, data in inventory['services'].items()
    }})
    print(json.dumps({'status': 'PREPARED', 'services': list(override['services']),
                      'private_files': 4, 'credential_files_read': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('activation_preparation_failed_existing_files_preserved') from None
