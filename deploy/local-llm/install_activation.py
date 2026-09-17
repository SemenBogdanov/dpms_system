"""Root-only connector activation; pinned images and serialized, timed rollback."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

SOURCE = Path(__file__).resolve().parent
CONFIG = Path('/etc/dpms/local-llm')
LIB = Path('/usr/local/lib/dpms-local-llm')
COMPOSE = ['docker', 'compose', '-p', 'deploy', '-f', '/opt/dpms/deploy/docker-compose.prod.yml']
SERVICES = ('backend', 'audit-worker')


def run(args, timeout=20):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('activation_command_failed')
    return result.stdout


def install(source, target, mode):
    if target.exists() or target.is_symlink():
        raise ValueError('existing_activation_file_preserved')
    shutil.copyfile(source, target)
    target.chmod(mode)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def load_state():
    path = CONFIG / 'activation-state.json'
    return json.loads(path.read_text()) if path.exists() else {'phase': 'inactive'}


def save_state(state):
    descriptor, name = tempfile.mkstemp(prefix='.activation-', dir=CONFIG)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, CONFIG / 'activation-state.json')
        directory = os.open(CONFIG, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def activation_allows_network(state, current_boot, now):
    return state.get('phase') == 'confirmed' or (
        state.get('phase') == 'trial' and state.get('boot_id') == current_boot
        and state.get('expires_at', 0) > now
    )


def require_trial():
    state = load_state()
    if state.get('phase') != 'trial' or not activation_allows_network(state, boot_id(), time.time()):
        raise ValueError('activation_trial_expired')
    return state


def pinned_compose(connector):
    inventory = json.loads((CONFIG / 'inventory.json').read_text())
    pins = json.loads((CONFIG / 'activation.pins.json').read_text())
    expected = {'services': {service: {'image': inventory['services'][service]['image_id']}
                             for service in SERVICES}}
    if pins != expected or any(not item['image'].startswith('sha256:') for item in pins['services'].values()):
        raise ValueError('invalid_image_pins')
    files = ['-f', str(CONFIG / 'connector.override.json')] if connector else []
    return COMPOSE + files + ['-f', str(CONFIG / 'activation.pins.json')]


def verify_images(allow_missing=False):
    inventory = json.loads((CONFIG / 'inventory.json').read_text())
    for service in SERVICES:
        if allow_missing:
            containers = run(['docker', 'ps', '-a', '-q', '--filter',
                              'name=^/deploy-' + service + '-1$']).split()
            if not containers:
                continue
            if len(containers) != 1:
                raise ValueError('ambiguous_service')
        actual = run(['docker', 'inspect', '--format', '{{.Image}}', 'deploy-' + service + '-1']).strip()
        if actual != inventory['services'][service]['image_id']:
            raise ValueError('application_image_changed')


def recreate(connector):
    run(pinned_compose(connector) + ['up', '-d', '--no-build', '--no-deps', '--pull', 'never',
                                   '--timeout', '120', '--force-recreate', *SERVICES], timeout=180)
    verify_images()


def rollback(trial_id=None):
    state = load_state()
    if trial_id and (state.get('phase') != 'trial' or state.get('trial_id') != trial_id):
        return {'status': 'ROLLBACK_NOT_NEEDED'}
    was_trial = state.get('phase') == 'trial'
    state['phase'] = 'rolling_back'
    save_state(state)
    errors = []
    for args in (
        ['systemctl', 'disable', '--now', 'dpms-connector-guard.timer'],
        ['systemctl', 'stop', 'dpms-connector-guard.service'],
    ):
        try:
            run(args, timeout=60)
        except Exception:
            errors.append('guard_service_stop_failed')
    try:
        run(['nft', '-f', str(CONFIG / 'tailscale-quarantine.nft')])
    except Exception:
        errors.append('quarantine_restore_failed')
        try:
            run(['tailscale', 'down'])
        except Exception:
            errors.append('tailnet_disconnect_failed')
    # Firewall failure must not prevent restoring the original container configuration.
    marker = CONFIG / 'compose-activated'
    if marker.exists():
        try:
            verify_images(allow_missing=was_trial)
            recreate(False)
            marker.unlink()
        except Exception:
            errors.append('container_restore_failed')
    state['phase'] = 'rollback_failed' if errors else 'rolled_back'
    save_state(state)
    return {'status': state['phase'].upper(), 'errors': errors}


def activate_network():
    if load_state().get('phase') not in ('inactive', 'rolled_back'):
        raise ValueError('activation_already_in_progress')
    trial = uuid.uuid4().hex
    unit = 'dpms-connector-rollback-' + trial
    state = {'phase': 'trial', 'trial_id': trial, 'unit': unit,
             'boot_id': boot_id(), 'expires_at': time.time() + 600}
    save_state(state)
    run(['systemd-run', '--collect', '--unit=' + unit, '--on-active=10m',
         '/bin/sh', str(LIB / 'rollback_connector.sh'), '--if-trial', trial])
    run(['systemctl', 'enable', '--now', 'dpms-connector-guard.timer'])
    run(['systemctl', 'start', 'dpms-connector-guard.service'], timeout=60)
    return {'status': 'NETWORK_ACTIVE', 'rollback_armed': True}


def activate_containers():
    require_trial()
    verify_images()
    pinned_compose(True)
    (CONFIG / 'compose-activated').touch(mode=0o600, exist_ok=False)
    recreate(True)
    require_trial()
    run(['systemctl', 'start', 'dpms-connector-guard.service'], timeout=60)
    return {'status': 'CONTAINERS_CONFIGURED', 'images_unchanged': True}


def confirm():
    state = require_trial()
    if not (CONFIG / 'compose-activated').exists():
        raise ValueError('containers_not_configured')
    state['phase'] = 'confirmed'
    save_state(state)
    # An already-fired rollback waiting for our lock sees confirmed and does nothing.
    run(['systemctl', 'stop', state['unit'] + '.timer'])
    return {'status': 'CONFIRMED', 'rollback_disarmed': True}


def stage():
    LIB.mkdir(mode=0o755, parents=True, exist_ok=True)
    CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('tailnet_connector_policy.py', 'refresh_connector_guard.py', 'install_activation.py'):
        install(SOURCE / name, LIB / name, 0o644)
    install(SOURCE / 'rollback_connector.sh', LIB / 'rollback_connector.sh', 0o700)
    for name in ('connector.json', 'connector.override.json', 'inventory.json', 'activation.pins.json'):
        install(SOURCE / name, CONFIG / name, 0o600)
    for name in ('dpms-connector-guard.service', 'dpms-connector-guard.timer'):
        install(SOURCE / name, Path('/etc/systemd/system') / name, 0o644)
    dropin = Path('/etc/systemd/system/tailscaled.service.d/dpms-connector-guard.conf')
    dropin.parent.mkdir(parents=True, exist_ok=True)
    install(SOURCE / 'tailscaled-connector-guard.conf', dropin, 0o644)
    run(['systemctl', 'daemon-reload'])
    run(['/usr/bin/python3', str(LIB / 'refresh_connector_guard.py'), '--check'])
    return {'status': 'STAGED', 'live_network_changed': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'network', 'containers', 'confirm', 'rollback'])
    parser.add_argument('--if-trial')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('root_required')
    with open('/run/lock/dpms-llm-activation.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'rollback':
            result = rollback(args.if_trial)
        else:
            result = {'install': stage, 'network': activate_network,
                      'containers': activate_containers, 'confirm': confirm}[args.action]()
    print(json.dumps(result))
    if result.get('errors'):
        raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'status': 'FAILED', 'code': 'activation_step_failed',
                          'rollback': 'keep_existing_quarantine_or_wait_for_armed_timer'}))
        raise SystemExit(2) from None
