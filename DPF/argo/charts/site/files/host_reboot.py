#!/usr/bin/env python3
"""DPF-requested, identity-checked iDRAC shutdown/on with a durable retry journal."""
import base64
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.request

SYSTEM = '/redfish/v1/Systems/System.Embedded.1'
RESET = SYSTEM + '/Actions/ComputerSystem.Reset'
JOURNAL = 'dsx-os.github.io/reboot-journal'


def checked_system(client, serial):
    system = client.system()
    if system.get('SerialNumber') != serial:
        raise RuntimeError('Server identity mismatch; no reset permitted')
    action = system.get('Actions', {}).get('#ComputerSystem.Reset', {})
    if action.get('target') != RESET or not {'GracefulShutdown', 'On'}.issubset(action.get('ResetType@Redfish.AllowableValues', [])):
        raise RuntimeError('Expected graceful shutdown/on actions are unavailable')
    return system


def recover(client, serial, job, method, attempts=60, sleep=time.sleep):
    if not job or method not in {'PowerCycle', 'SystemLevelReset', 'SystemReboot'}:
        raise RuntimeError('Missing job identity or unsupported DPF reboot method')
    checked_system(client, serial)
    old = client.journal()
    if old and (old.get('serial') != serial or (old.get('job') != job and old.get('stage') != 'complete')):
        raise RuntimeError('Unresolved previous reboot or changed identity; operator inspection required')
    record = old if old and old.get('job') == job else {'job': job, 'serial': serial, 'stage': 'new'}

    def advance(stage):
        nonlocal record, old
        new = dict(record, stage=stage)
        client.save(old, new)
        old = record = new
        print('Reboot stage: ' + stage, flush=True)

    def wait_power(expected):
        for _ in range(attempts):
            if checked_system(client, serial).get('PowerState') == expected:
                return
            sleep(5)
        raise RuntimeError('Power transition timed out; no repeated reset will be sent')

    if record['stage'] == 'complete':
        if checked_system(client, serial).get('PowerState') != 'On':
            raise RuntimeError('Completed cycle no longer has power On; inspect host')
        return
    if record['stage'] == 'new':
        if checked_system(client, serial).get('PowerState') != 'On':
            raise RuntimeError('Host is not initially On; inspect before starting a cycle')
        advance('shutdown-requested')  # Persist BEFORE a non-idempotent POST.
        client.reset('GracefulShutdown')
    if record['stage'] == 'shutdown-requested':
        wait_power('Off')
        advance('off-observed')
    if record['stage'] == 'off-observed':
        if checked_system(client, serial).get('PowerState') != 'Off':
            raise RuntimeError('Power state changed outside this job; inspect host')
        sleep(10)
        advance('on-requested')
        client.reset('On')
    if record['stage'] == 'on-requested':
        wait_power('On')
        advance('complete')
    if record['stage'] != 'complete':
        raise RuntimeError('Unknown reboot journal state')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('HTTP redirect refused')


class Client:
    def __init__(self, env=os.environ, credentials=Path('/credentials')):
        self.env = env
        ip = str(ipaddress.IPv4Address(env['IDRAC_IP']))
        self.base = 'https://' + ip
        user = (credentials / 'username').read_text()
        password = (credentials / 'password').read_text()
        if not user or not password or ':' in user or any(c in user + password for c in '\r\n'):
            raise RuntimeError('Invalid credential format')
        self.authorization = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
        context = ssl.create_default_context()
        if env.get('VERIFY_TLS', 'true') == 'false':
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.redfish = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))

    @staticmethod
    def request(opener, url, method='GET', data=None, headers=None):
        request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), method=method,
                                         headers=headers or {})
        try:
            with opener.open(request, timeout=20) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            # Never echo request headers, response bodies or credentials.
            raise RuntimeError('Management request failed: ' + type(exc).__name__) from None

    def system(self):
        return self.request(self.redfish, self.base + SYSTEM, headers={'Authorization': self.authorization})

    def reset(self, action):
        self.request(self.redfish, self.base + RESET, 'POST', {'ResetType': action},
                     {'Authorization': self.authorization, 'Content-Type': 'application/json'})

    def kube(self, method='GET', patch=None):
        token_dir = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        context = ssl.create_default_context(cafile=str(token_dir / 'ca.crt'))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))
        headers = {'Authorization': 'Bearer ' + (token_dir / 'token').read_text().strip(),
                   'Content-Type': 'application/json-patch+json'}
        node = self.env['DPUNODE_NAME']
        if node != self.env['EXPECTED_DPUNODE']:
            raise RuntimeError('DPF node identity mismatch')
        namespace = (token_dir / 'namespace').read_text().strip()
        path = f'/apis/provisioning.dpu.nvidia.com/v1alpha1/namespaces/{namespace}/dpunodes/{node}'
        return self.request(opener, 'https://kubernetes.default.svc' + path, method, patch, headers)

    def journal(self):
        value = self.kube()['metadata'].get('annotations', {}).get(JOURNAL)
        return json.loads(value) if value else None

    def save(self, old, new):
        node = self.kube()
        annotations = node['metadata'].get('annotations', {})
        value = annotations.get(JOURNAL)
        if (json.loads(value) if value else None) != old:
            raise RuntimeError('Reboot journal changed concurrently')
        annotations[JOURNAL] = json.dumps(new, separators=(',', ':'))
        self.kube('PATCH', [
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': node['metadata']['resourceVersion']},
            {'op': 'add', 'path': '/metadata/annotations', 'value': annotations}])


def main():
    try:
        client = Client()
        serial = os.environ['EXPECTED_SERIAL']
        if sys.argv[1:] == ['--probe']:
            checked_system(client, serial)
            print('iDRAC credentials, server identity and reset capabilities verified; no reset sent.')
            return
        if sys.argv[1:]:
            raise RuntimeError('Only --probe is accepted; execution is for DPF script Jobs')
        if os.environ.get('DPUNODE_NAME') != os.environ['EXPECTED_DPUNODE']:
            raise RuntimeError('This script must be launched for the configured DPUNode by DPF')
        recover(client, serial, os.environ['REBOOT_JOB_UID'], os.environ.get('DPUNODE_REBOOT_METHOD', ''))
        print('Host power cycle verified; DPF will continue provisioning.')
    except (RuntimeError, KeyError, ValueError, OSError) as exc:
        # Missing input is reported by category, without accidental secret contents.
        print('Reboot stopped: ' + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
