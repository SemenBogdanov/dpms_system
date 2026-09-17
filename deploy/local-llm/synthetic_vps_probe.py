"""Fixed synthetic VPS probe. Own gateway value travels only over SSH stdin."""

import json
import os
import shlex
import subprocess

import httpx

REMOTE_CODE = r'''
import asyncio,json,sys
from types import SimpleNamespace
from app.services.ai_provider import generate_text,encrypt_ai_api_key,AIProviderError

async def main():
    request=json.load(sys.stdin)
    provider=SimpleNamespace(enabled=True,last_test_status='ok',config_version=1,
        last_verified_config_version=1,base_url=request['base_url'],model_name=request['model'],
        api_key_ciphertext=encrypt_ai_api_key(request.pop('bearer')))
    messages=[
      {'role':'system','content':'Return only JSON with an atoms array. Each atom has name and evidence strings. Extract exactly the two UI elements explicitly required below. Do not add anything.'},
      {'role':'user','content':'SYNTHETIC TEST, NOT A REAL DOCUMENT. Section 1: The Test panel has a Save button. Section 2: The Test panel has a Name text field.'}]
    text=await generate_text(provider,messages,max_tokens=2048,temperature=0)
    atoms=json.loads(text)['atoms']
    valid=isinstance(atoms,list) and len(atoms)==2 and all(isinstance(a,dict) and
        isinstance(a.get('name'),str) and a['name'].strip() and
        isinstance(a.get('evidence'),str) and a['evidence'].strip() for a in atoms)
    print(json.dumps({'status':'PASS' if valid else 'FAIL','atoms':len(atoms) if valid else None,
        'db_writes':0,'real_documents':0}))
try:
    asyncio.run(main())
except AIProviderError as exc:
    print(json.dumps({'status':'BLOCKED','code':exc.code if exc.code.isidentifier() else 'provider_error'}))
    sys.exit(2)
except Exception:
    print(json.dumps({'status':'FAIL','code':'synthetic_validation_failed'}))
    sys.exit(2)
'''


def ssh_command(service):
    if service not in ('backend', 'audit-worker'):
        raise ValueError('fixed_service_required')
    remote = 'sudo -n docker exec -i deploy-' + service + '-1 python -c ' + shlex.quote(REMOTE_CODE)
    return ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2', 'dpms-vps', remote]


def run_probe(bearer):
    status = json.loads(subprocess.run(['/usr/local/bin/tailscale', 'status', '--json'], capture_output=True,
                                       text=True, check=True, timeout=5).stdout)
    host = status['Self']['DNSName'].rstrip('.')
    if not host.endswith('.ts.net') or host not in status.get('CertDomains', []):
        raise ValueError('unconfirmed_certificate_name')
    with httpx.Client(trust_env=False, timeout=5, follow_redirects=False) as client:
        response = client.get('http://127.0.0.1:18080/v1/models',
                              headers={'Authorization': 'Bearer ' + bearer})
        response.raise_for_status()
        models = response.json()['data']
    if len(models) != 1 or not isinstance(models[0].get('id'), str):
        raise ValueError('exact_model_required')
    payload = {'bearer': bearer, 'base_url': 'https://' + host + '/v1', 'model': models[0]['id']}
    environment = {key: os.environ[key] for key in ('HOME', 'SSH_AUTH_SOCK') if key in os.environ}
    environment['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    results = []
    for service in ('backend', 'audit-worker'):
        result = subprocess.run(ssh_command(service), input=json.dumps(payload),
                                capture_output=True, text=True, timeout=115, env=environment)
        document = json.loads(result.stdout)
        record = {'service': service, 'status': document.get('status'), 'atoms': document.get('atoms')}
        results.append(record)
        if result.returncode or document.get('status') != 'PASS':
            return {'status': 'BLOCKED', 'checks': results}
    return {'status': 'PASS', 'checks': results, 'scope': 'real_container_provider_client_to_local_model',
            'audit_job_tested': False, 'db_writes': 0, 'real_documents': 0}


if __name__ == '__main__':
    bearer = os.environ.pop('DPMS_LOCAL_LLM_BEARER', '')
    try:
        if len(bearer) < 43:
            raise ValueError('own_gateway_value_required')
        result = run_probe(bearer)
    except Exception:
        result = {'status': 'BLOCKED', 'code': 'synthetic_vps_probe_failed'}
    finally:
        bearer = ''
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'PASS' else 2)
