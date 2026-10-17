#!/usr/bin/env python3
"""Private, explicit Vault/Secret bootstrap. Never writes credentials to Git."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = None


def kubectl(args, data=None, check=True):
    cmd = ['kubectl', '--context', CONTEXT, '--request-timeout=30s', *args]
    p = subprocess.run(cmd, input=data, text=True, capture_output=True)
    if check and p.returncode:
        # API errors can contain the submitted Secret; never echo raw stderr.
        raise RuntimeError('kubectl operation failed: ' + ' '.join(args[:3]))
    return p


def private_file(value):
    p = Path(value).absolute()
    if p.is_symlink() or not p.is_file():
        raise ValueError('Private input must be a regular, non-symlink file')
    if stat.S_IMODE(p.stat().st_mode) & 0o077:
        raise ValueError('Private input requires chmod 600 (or 400)')
    if p.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Keep private inputs outside this Git checkout')
    return p


def namespace(name):
    kubectl(['apply', '-f', '-'], json.dumps({'apiVersion': 'v1', 'kind': 'Namespace',
            'metadata': {'name': name}}))


def secret(name, ns, values, kind='Opaque', labels=None, only_if_absent=False):
    if only_if_absent:
        p = kubectl(['get', 'secret', name, '-n', ns, '--ignore-not-found', '-o', 'name'])
        if p.stdout.strip():
            return
    obj = {'apiVersion': 'v1', 'kind': 'Secret',
           'metadata': {'name': name, 'namespace': ns, 'labels': labels or {}},
           'type': kind, 'data': {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}}
    kubectl(['apply', '--server-side', '--field-manager=nico-private-bootstrap', '-f', '-'], json.dumps(obj))
    print(f'Secret ready: {ns}/{name}')


def vault(pod, command, data=None, check=True):
    # The certificate includes the short vault-N.vault-internal SAN.
    script = ('export VAULT_ADDR=https://' + pod + '.vault-internal:8200 '
              'VAULT_CACERT=/vault/userconfig/nicoca-vault/ca.crt; ' + command)
    return kubectl(['exec', '-i', '-n', 'vault', pod, '-c', 'vault', '--',
                    'sh', '-c', script], data, check)


def vault_status(pod):
    p = vault(pod, 'vault status -format=json', check=False)
    if p.returncode not in (0, 2):
        raise RuntimeError(f'{pod}: cannot read Vault status')
    return json.loads(p.stdout)


def initialize(recovery):
    path = Path(recovery).absolute()
    if path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Recovery file must be outside this Git checkout')
    status = vault_status('vault-0')
    if not status['initialized']:
        # Reserve the private file before irreversible initialization.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            p = vault('vault-0', 'vault operator init -format=json -key-shares=5 -key-threshold=3')
            out.write(p.stdout)
            out.flush()
            os.fsync(out.fileno())
        print('Vault initialized; recovery material saved privately.')
    else:
        private_file(path)
    recovery_data = json.loads(private_file(path).read_text())
    for n in range(3):
        pod = f'vault-{n}'
        for attempt in range(36):
            status = vault_status(pod)
            if not status['sealed']:
                break
            if status['initialized']:
                for key in recovery_data['unseal_keys_b64'][:3]:
                    vault(pod, 'read -r key; vault operator unseal "$key" >/dev/null', key + '\n')
            time.sleep(5)
        else:
            raise RuntimeError(f'{pod}: unseal did not complete')
        print(f'{pod}: unsealed')
    namespace('nico-system')
    secret('nico-vault-token', 'nico-system', {'token': recovery_data['root_token']})
    secret('nico-vault-approle-tokens', 'nico-system', {'VAULT_ROLE_ID': '', 'VAULT_SECRET_ID': ''}, only_if_absent=True)
    p = kubectl(['get', 'secret', 'ssh-host-key', '-n', 'nico-system', '--ignore-not-found', '-o', 'name'])
    if not p.stdout.strip():
        key = subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519'],
                             text=True, capture_output=True, check=True).stdout
        secret('ssh-host-key', 'nico-system', {'ssh_host_ed25519_key': key, 'ssh_host_ed25519_key_pub': ''})
    secret('nico-api-web-basic-auth', 'nico-system', {'password': secrets.token_urlsafe(32)}, only_if_absent=True)


def seed(filename):
    data = yaml.safe_load(private_file(filename).read_text())
    required = {'bmcRootPassword', 'hostUEFIPassword', 'dpuUEFIPassword'}
    if set(data or {}) != required or any(not isinstance(data[k], str) or not data[k] for k in required):
        raise ValueError('Supply exactly bmcRootPassword, hostUEFIPassword, dpuUEFIPassword as nonempty strings')
    p = kubectl(['get', 'secret', 'nico-vault-token', '-n', 'nico-system', '-o', 'json'])
    token = base64.b64decode(json.loads(p.stdout)['data']['token']).decode()
    paths = {'bmcRootPassword': ('machines/bmc/site/root', 'root'),
             'hostUEFIPassword': ('machines/all_hosts/site_default/uefi-metadata-items/auth', ''),
             'dpuUEFIPassword': ('machines/all_dpus/site_default/uefi-metadata-items/auth', '')}
    for key, (path, user) in paths.items():
        payload = json.dumps({'UsernamePassword': {'username': user, 'password': data[key]}})
        vault('vault-0', 'read -r VAULT_TOKEN; export VAULT_TOKEN; vault kv put secrets/' + path + ' - >/dev/null', token + '\n' + payload)
        print(f'Vault credential stored: {path}')
    print('Credentials stored. This does not test BMC/iDRAC login or add expected machines.')


def registry(filename, config):
    raw = private_file(filename).read_text()
    data = json.loads(raw)
    settings = yaml.safe_load(Path(config).read_text())['spec']['source']['helm']['valuesObject']
    host = settings['images']['registry'].split('/')[0]
    auth = data.get('auths', {}).get(host)
    if not auth:
        raise ValueError(f'dockerconfigjson must contain auths[{host!r}] with embedded auth, not a credential helper')
    if 'auth' in auth:
        user, password = base64.b64decode(auth['auth']).decode().split(':', 1)
    else:
        user, password = auth['username'], auth['password']
    chart_url = settings['images']['dpuChartRepository']
    if not chart_url.startswith('oci://' + host + '/'):
        raise ValueError('This registry helper requires the DPU OCI charts and images on the same registry host')
    for ns in ['nico-system', 'dpf-operator-system']:
        namespace(ns)
        secret(settings['images']['pullSecret'] if ns == 'nico-system' else 'nico-pull-secret', ns,
               {'.dockerconfigjson': raw}, 'kubernetes.io/dockerconfigjson',
               {'dpu.nvidia.com/image-pull-secret': ''} if ns == 'dpf-operator-system' else None)
    secret('nico-service-charts', 'dpf-operator-system',
           {'name': 'nico-service-charts', 'type': 'helm', 'enableOCI': 'true',
            'url': chart_url.removeprefix('oci://'), 'username': user, 'password': password},
           labels={'argocd.argoproj.io/secret-type': 'repository'})
    secret('hbn-user-password', 'dpf-operator-system', {'password': secrets.token_urlsafe(24)},
           labels={'dpu.nvidia.com/image-pull-secret': ''}, only_if_absent=True)


def main():
    global CONTEXT
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('vault-init'); a.add_argument('--recovery-file', required=True)
    a = sub.add_parser('seed'); a.add_argument('--credentials', required=True)
    a = sub.add_parser('registry'); a.add_argument('--dockerconfig', required=True); a.add_argument('--config', required=True)
    args = p.parse_args()
    CONTEXT = subprocess.check_output(['kubectl', 'config', 'current-context'], text=True).strip()
    print('Target context:', CONTEXT)
    if args.action == 'vault-init': initialize(args.recovery_file)
    elif args.action == 'seed': seed(args.credentials)
    else: registry(args.dockerconfig, args.config)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # Do not leak subprocess/API payloads, credentials, or YAML snippets.
        print('Stopped:', str(e) if isinstance(e, (ValueError, RuntimeError)) and not isinstance(e, json.JSONDecodeError) else type(e).__name__)
        raise SystemExit(1)
