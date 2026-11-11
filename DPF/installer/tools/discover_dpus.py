"""Guided Redfish range discovery from a temporary Kubernetes node-network pod."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import bmc_check as bmc
from install_log import append, now, redact, write_json
from ui import banner, table

BASE = Path(__file__).resolve().parents[1]
MEMBER_PATH = re.compile(r'/redfish/v1/Systems/[A-Za-z0-9_-]+/?')


def address_range(start, end):
    first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
    count = int(last) - int(first) + 1
    if not 1 <= count <= 256:
        raise ValueError('Use an ascending range containing 1-256 IPv4 addresses.')
    addresses = [str(ipaddress.IPv4Address(int(first) + i)) for i in range(count)]
    for address in addresses:
        bmc.targets(address)
    return addresses


class Audit:
    """Record argv and exit codes, never credential stdin or raw device responses."""
    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.Lock()

    def event(self, text):
        with self.lock:
            append(self.directory / 'commands.log', text)
            append(self.directory / 'discovery.log', text)

    def message(self, text):
        with self.lock:
            append(self.directory / 'discovery.log', text + '\n')
        print(text, flush=True)

    def run(self, k, args, **kwargs):
        command = [*k, *args]
        ident = uuid.uuid4().hex[:12]
        started = time.monotonic()
        self.event(f'[{now()}] start id={ident} {shlex.join(redact(command))}\n')
        if 'curl' in args:
            target = re.search(r'^url = "(https://[0-9.]+/redfish/v1/Systems(?:/[A-Za-z0-9_-]+/?)?)"$',
                               kwargs.get('input', ''), re.M)
            if target:
                self.event(f'[{now()}] id={ident} request={target.group(1)} (credentials omitted)\n')
        code = 'interrupted'
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=40, **kwargs)
            code = result.returncode
            return result
        except subprocess.TimeoutExpired:
            code = 'timeout'
            raise
        except OSError:
            code = 'execution-error'
            raise
        finally:
            self.event(f'[{now()}] end id={ident} exit={code} elapsed={time.monotonic()-started:.1f}s\n')


def safe_field(value, password):
    if not isinstance(value, str):
        return '-'
    value = value.replace(password, '[REDACTED]') if password else value
    return ''.join(c if c.isprintable() else ' ' for c in value)[:120] or '-'


def probe(k, name, ip, user, password, insecure, source, interface, runner, stop=None):
    row = {'ip': ip, 'status': 'PROBE ERROR', 'authentication': '-', 'systems': []}
    stop = stop or threading.Event()

    def request(secret, path='/redfish/v1/Systems'):
        if stop.is_set():
            raise RuntimeError('Discovery cancelled.')
        status, body, error = bmc.request(k, name, ip, user, secret, insecure, source, path, runner)
        if status in (423, 429) or (status in (401, 403) and
                re.search(r'(?:account|user)[^\n]{0,80}lock|lock[^\n]{0,80}(?:account|user)', body, re.I)):
            error = 'ACCOUNT LOCKED / RATE LIMITED'
        return status, body, error

    try:
        if stop.is_set():
            row['status'] = 'CANCELLED'
            return row
        if not bmc.route_matches(k, name, ip, source, interface, runner):
            row['status'] = 'WRONG / NO ROUTE'
            return row
        anonymous, _, error = request(None)
        if error or anonymous not in (200, 401, 403):
            row['status'] = error or f'HTTP {anonymous}'
            return row
        status, body, error = request(password)
        verdict = error or bmc.evaluate(anonymous, status, body)
        if verdict not in ('PASS', 'UNVERIFIED'):
            row['status'] = verdict
            return row
        row['authentication'] = verdict
        collection = json.loads(body)
        members = collection['Members']
        # Do not follow pagination or arbitrary links supplied by a remote BMC.
        incomplete = bool(collection.get('Members@odata.nextLink')) or len(members) > 4
        for member in members[:4]:
            path = member.get('@odata.id') if isinstance(member, dict) else None
            if not isinstance(path, str) or not MEMBER_PATH.fullmatch(path):
                incomplete = True
                continue
            status, body, error = request(password, path)
            if error or status != 200:
                row['status'] = error or {401: 'AUTH FAILED', 403: 'FORBIDDEN'}.get(status, f'HTTP {status}')
                return row
            system = json.loads(body)
            if (not isinstance(system, dict)
                    or not isinstance(system.get('@odata.type'), str)
                    or not re.fullmatch(r'#ComputerSystem\.[^.]+\.ComputerSystem', system['@odata.type'])):
                incomplete = True
                continue
            row['systems'].append({key: safe_field(system.get(field), password)
                                   for key, field in [('manufacturer', 'Manufacturer'),
                                                      ('model', 'Model'), ('serial', 'SerialNumber')]})
        if incomplete:
            row['status'] = 'INCOMPLETE'
        elif not row['systems']:
            row['status'] = 'NO SYSTEMS'
        elif any('bluefield' in s['model'].lower() for s in row['systems']):
            row['status'] = 'DPU FOUND'
        else:
            row['status'] = 'REDFISH DEVICE'
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        # Neither device bodies nor subprocess exceptions are safe to print.
        row['status'] = 'CANCELLED' if stop.is_set() else 'PROBE ERROR'
    return row


def scan(k, ips, user, password, insecure, node, interface, audit):
    name = 'dpf-discovery-' + uuid.uuid4().hex[:16]
    pod = bmc.manifest(name, node)
    pod['metadata']['labels']['app.kubernetes.io/name'] = 'dpf-discovery'
    pod['spec']['activeDeadlineSeconds'] = 3600
    pod['spec']['containers'][0]['command'] = ['sleep', '3600']
    pod['spec']['containers'][0]['resources']['limits'] = {'cpu': '500m', 'memory': '256Mi'}
    rows = []
    stop = threading.Event()
    cleanup_ok = False
    try:
        created = audit.run(k, ['create', '-f', '-'], input=json.dumps(pod))
        if created.returncode:
            raise RuntimeError('Cannot create the discovery pod; check namespace, permissions and admission policy.')
        bmc.wait_ready(k, name, audit.run)
        source = bmc.nic_source(k, name, interface, audit.run)
        audit.message(f'Node: {node} | NIC: {interface} | Source: {source} | Targets: {len(ips)}')
        pool = ThreadPoolExecutor(max_workers=8)
        try:
            futures = [pool.submit(probe, k, name, ip, user, password, insecure,
                                   source, interface, audit.run, stop) for ip in ips]
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                audit.message(f'[{len(rows)}/{len(ips)}] {row["ip"]}: {row["status"]}')
        finally:
            stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
    finally:
        try:
            deleted = audit.run(k, ['-n', bmc.NAMESPACE, 'delete', 'pod', name,
                                    '--ignore-not-found', '--wait=true', '--timeout=20s'])
            cleanup_ok = deleted.returncode == 0
        except (OSError, subprocess.SubprocessError):
            cleanup_ok = False
        if not cleanup_ok:
            audit.message(f'Cleanup failed: remove pod {bmc.NAMESPACE}/{name} in the selected context.')
        rows.sort(key=lambda row: int(ipaddress.IPv4Address(row['ip'])))
        write_json(audit.directory / 'results.json', {'results': rows, 'cleanupSucceeded': cleanup_ok})
    return rows, cleanup_ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(2, 'Run --discover-dpus in a terminal; credentials are entered privately.\n')
    banner('Discover DPUs', args.context)
    print('Scan only the BMC range you supply. Redfish GET requests; no provisioning or Secret changes.')
    ips = address_range(input('BMC range start IPv4: ').strip(), input('BMC range end IPv4 (inclusive): ').strip())
    user = bmc.ask('BMC username', 'root')
    if not user or ':' in user or len(user) > 128:
        raise ValueError('Invalid BMC username.')
    bmc.quoted(user)
    tls = bmc.ask('Verify BMC TLS certificates? y/n', 'y').lower()
    if tls not in ('y', 'n'):
        raise ValueError('Choose y or n for TLS verification.')
    insecure = tls == 'n'
    # Audit only this discovery; installation latest-run pointers are untouched.
    root = BASE / 'logs-discovery'
    root.mkdir(mode=0o700, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='discovery-', dir=root))
    audit = Audit(directory)
    temporary = root / ('.latest-' + uuid.uuid4().hex)
    temporary.symlink_to(directory.name)
    temporary.replace(root / 'latest')
    state = {'context': args.context, 'startedAt': now(), 'state': 'running',
             'rangeStart': ips[0], 'rangeEnd': ips[-1], 'verifyTLS': not insecure}
    write_json(directory / 'status.json', state)
    code = 1
    k = ['kubectl', f'--context={args.context}', '--request-timeout=30s']
    try:
        result = audit.run(k, ['get', 'nodes', '-l', 'kubernetes.io/os=linux', '-o', 'json'])
        if result.returncode:
            raise RuntimeError('Unable to list Kubernetes nodes.')
        nodes = [n for n in json.loads(result.stdout)['items']
                 if any(c.get('type') == 'Ready' and c.get('status') == 'True'
                        for c in n.get('status', {}).get('conditions', []))]
        if not nodes:
            raise RuntimeError('No Ready Linux nodes available.')
        for index, node in enumerate(nodes, 1):
            print(f'  {index}. {node["metadata"]["name"]}')
        choice = int(bmc.ask('Node to scan from', '1'))
        if not 1 <= choice <= len(nodes):
            raise ValueError('Invalid node selection.')
        node = nodes[choice - 1]['metadata']['name']
        interface = input('DPU-facing NIC on that node (for this lab: enp7s0): ').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface):
            raise ValueError('Invalid NIC name.')
        password = getpass.getpass('Shared BMC password (not saved): ')
        if not password:
            raise ValueError('Password is empty.')
        bmc.quoted(password)
        state.update(node=node, interface=interface)
        audit.message(f'Scanning {ips[0]} through {ips[-1]} from {node}/{interface}.')
        audit.message('TLS certificate verification: ' + ('disabled by user' if insecure else 'enabled'))
        rows, cleanup_ok = scan(k, ips, user, password, insecure, node, interface, audit)
        display = [[r['ip'], r['status'], r['authentication'], s['model'], s['serial']]
                   for r in rows for s in (r['systems'] or [{'model': '-', 'serial': '-'}])]
        table(display, ['BMC IP', 'RESULT', 'AUTH', 'MODEL', 'SERIAL'])
        for row in display:
            append(directory / 'discovery.log', ' | '.join(row) + '\n')
        found = sum(r['status'] == 'DPU FOUND' for r in rows)
        audit.message(f'Found {found} BMC endpoint(s) reporting a BlueField model.')
        audit.message('UNVERIFIED means anonymous access was allowed; the password was not proven.')
        audit.message('REDFISH DEVICE needs manual identification. Results prove this node/NIC path only.')
        problems = any(r['status'] not in ('DPU FOUND', 'REDFISH DEVICE', 'NO SYSTEMS',
                                          'UNREACHABLE', 'TIMEOUT', 'NOT REDFISH', 'HTTP 404')
                       or r['authentication'] == 'UNVERIFIED' for r in rows)
        code = 0 if found and cleanup_ok and not problems else 1
        return code
    finally:
        state.update(state='succeeded' if code == 0 else 'failed', exitCode=code, finishedAt=now())
        write_json(directory / 'status.json', state)
        audit.message(f'Discovery logs: {directory}')


if __name__ == '__main__':
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nDiscovery cancelled.')
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, RuntimeError) else 'Check range, setup values and Kubernetes access.'
        sys.exit('Discovery stopped: ' + message)
