#!/usr/bin/env python3
"""Validate management credentials from temporary Kubernetes helper pods."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid

import yaml
from installer import pinned_cluster, validate_config

IMAGE = 'docker.io/nicolaka/netshoot@sha256:a20c2531bf35436ed3766cd6cfe89d352b050ccc4d7005ce6400adf97503da1b'


def targets_from_config(app, insecure_bmc=False):
    values = validate_config(app)
    hosts = values.get('bootstrap', {}).get('hosts', [])
    if not hosts or len({h['dpuNode'] for h in hosts}) != len(hosts):
        raise ValueError('Config needs unique bootstrap.hosts with managementNode and iDRAC identities')
    by_node = {h['dpuNode']: h for h in hosts}
    targets = []
    for h in hosts:
        if not re.fullmatch(r'[a-z0-9]([a-z0-9.-]*[a-z0-9])?', h['managementNode']):
            raise ValueError('Invalid managementNode')
        if not isinstance(h['verifyTLS'], bool) or not h['serial']:
            raise ValueError('Missing iDRAC serial or invalid verifyTLS')
        targets.append({'name': h['name'] + ' iDRAC', 'node': h['managementNode'],
                        'ip': str(ipaddress.IPv4Address(h['idracIP'])), 'port': 443,
                        'serial': h['serial'], 'verifyTLS': h['verifyTLS'], 'credential': 'idrac',
                        'path': '/redfish/v1/Systems/System.Embedded.1'})
    seen = set()
    for patch in app['spec']['sources'][3].get('kustomize', {}).get('patches', []):
        if patch['target']['kind'] != 'DPUDevice':
            continue
        operations = yaml.safe_load(patch['patch'])
        allowed = {'/spec', '/metadata/name', '/metadata/labels'}
        if (not isinstance(operations, list) or
                any(p.get('op') not in ('add', 'replace') or p.get('path') not in allowed for p in operations) or
                len({p['path'] for p in operations}) != len(operations)):
            raise ValueError('Unsupported DPUDevice patch shape; regenerate the prepared Application')
        ops = {p['path']: p['value'] for p in operations}
        spec = ops.get('/spec', {})
        node = ops.get('/metadata/labels', {}).get('provisioning.dpu.nvidia.com/dpunode-name')
        if node not in by_node or node in seen or not spec.get('serialNumber'):
            raise ValueError('Each DPUDevice must map to one bootstrap host and include its serial')
        seen.add(node)
        host = by_node[node]
        port = spec.get('bmcPort', 443)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('Invalid BMC port')
        targets.append({'name': host['name'] + ' DPU BMC', 'node': host['managementNode'],
                        'ip': str(ipaddress.IPv4Address(spec['bmcIp'])), 'port': port,
                        'serial': spec['serialNumber'], 'verifyTLS': not insecure_bmc,
                        'credential': 'bmc', 'path': '/redfish/v1/Systems/Bluefield'})
    if seen != set(by_node):
        raise ValueError('Missing DPUDevice settings for a bootstrap host')
    return targets


def private_password(path):
    p = Path(path)
    repo = Path(__file__).resolve().parents[2]
    if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o777 not in (0o400, 0o600):
        raise ValueError('Password files must be regular files with mode 600/400')
    if p.resolve().is_relative_to(repo):
        raise ValueError('Password files must be outside Git')
    value = p.read_text()
    if not value or any(c in value for c in '\r\n\x00'):
        raise ValueError('Password file must be nonempty with no newline/NUL')
    return value


def kube(args, payload=None, timeout=60):
    result = subprocess.run(['kubectl', '--request-timeout=30s', *args], input=payload,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Even an exec error may echo remote input; never print raw diagnostics.
        raise RuntimeError('kubectl ' + args[0] + ' failed; check cluster access, pod events and image pull')
    return result.stdout


def run_checks(targets):
    namespace = 'dpf-preflight-' + uuid.uuid4().hex[:10]
    print('Temporary helper namespace:', namespace, flush=True)
    try:
        kube(['create', 'namespace', namespace])
        results = []
        script = Path(__file__).with_name('preflight_probe.py').read_text()
        for index, node in enumerate(dict.fromkeys(t['node'] for t in targets)):
            name = f'check-{index}'
            pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace},
                   'spec': {'nodeName': node, 'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet',
                            'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                            'activeDeadlineSeconds': 600,
                            'containers': [{'name': 'check', 'image': IMAGE,
                                            'command': ['sleep', '600'],
                                            'securityContext': {'allowPrivilegeEscalation': False,
                                                                'capabilities': {'drop': ['ALL']}},
                                            'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'},
                                                          'limits': {'memory': '256Mi'}}}]}}
            kube(['create', '-f', '-'], json.dumps(pod))
            kube(['-n', namespace, 'wait', 'pod/'+name, '--for=condition=Ready', '--timeout=180s'], timeout=190)
            selected = [t for t in targets if t['node'] == node]
            output = kube(['-n', namespace, 'exec', '-i', name, '--', 'python3', '-c', script],
                          json.dumps(selected), timeout=30 * len(selected) + 15)
            batch = json.loads(output)
            if not isinstance(batch, list) or len(batch) != len(selected):
                raise RuntimeError('Incomplete helper results')
            for target, result in zip(selected, batch):
                if result.get('name') != target['name'] or type(result.get('ok')) is not bool:
                    raise RuntimeError('Invalid helper result')
                results.append(result)
                print(('PASS ' if result['ok'] else 'FAIL ') + result['name'] + ': ' + result['detail'], flush=True)
        return all(r['ok'] for r in results)
    finally:
        kube(['delete', 'namespace', namespace, '--ignore-not-found', '--wait=true', '--timeout=60s'], timeout=70)
        print('Temporary helper removed.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--bmc-password-file', required=True)
    parser.add_argument('--idrac-password-file', required=True)
    parser.add_argument('--idrac-user', default='root')
    parser.add_argument('--insecure-bmc', action='store_true', help='Explicit lab-only opt-out of BMC TLS verification')
    parser.add_argument('--ssh-host', action='append', default=[], help='Optional existing DPU OS IPv4 address; repeat for multiple DPUs')
    parser.add_argument('--ssh-user', default='ubuntu')
    parser.add_argument('--ssh-password-file')
    parser.add_argument('--ssh-known-hosts', help='Previously verified SSH known_hosts file; required for SSH checks')
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        for user in (args.idrac_user, args.ssh_user):
            if not user or any(c in user for c in ':\r\n\x00'):
                raise ValueError('Invalid username')
        targets = targets_from_config(yaml.safe_load(Path(args.config).read_text()), args.insecure_bmc)
        passwords = {'bmc': private_password(args.bmc_password_file),
                     'idrac': private_password(args.idrac_password_file)}
        for target in targets:
            key = target.pop('credential')
            target.update(username='root' if key == 'bmc' else args.idrac_user, password=passwords[key])
            if not target['verifyTLS']:
                print('TLS verification disabled by configuration:', target['name'], flush=True)
        if args.ssh_host:
            if not args.ssh_password_file or not args.ssh_known_hosts:
                raise ValueError('SSH checks require --ssh-password-file and --ssh-known-hosts')
            password = private_password(args.ssh_password_file)
            known = Path(args.ssh_known_hosts).read_text()
            if not known.strip():
                raise ValueError('SSH known_hosts must contain verified host keys')
            for host in args.ssh_host:
                ip = str(ipaddress.IPv4Address(host))
                targets.append({'name': 'DPU SSH ' + ip, 'kind': 'ssh', 'node': targets[0]['node'],
                                'ip': ip, 'username': args.ssh_user, 'password': password, 'knownHosts': known})
        elif args.ssh_password_file or args.ssh_known_hosts:
            raise ValueError('SSH credential options require --ssh-host')
        else:
            print('SKIP DPU OS SSH: no optional SSH targets supplied (OS may not be installed yet).')
        print('IPAM/DHCP allocation and IPMI protocol are not tested by Redfish credential validation.')
        context = kube(['config', 'current-context']).strip()
        with pinned_cluster(context):
            if not run_checks(targets):
                raise RuntimeError('Credential preflight failed; no permanent password Secrets were written')
    except KeyboardInterrupt:
        parser.exit(130, 'Preflight interrupted.\n')
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired):
        parser.exit(1, 'Preflight failed; check the PASS/FAIL summary, config, TLS and helper pod events. No credentials logged.\n')


if __name__ == '__main__':
    main()
