#!/usr/bin/env python3
"""Run inside the temporary helper; input contains credentials, output never does."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def redfish(target):
    token = base64.b64encode((target['username'] + ':' + target['password']).encode()).decode()
    command = ['curl', '--silent', '--show-error', '--noproxy', '*', '--proto', '=https',
               '--connect-timeout', '5', '--max-time', '20', '--max-filesize', '1048576',
               '--config', '-', '--write-out', '\n%{http_code}']
    if not target['verifyTLS']:
        command.append('--insecure')
    command.append(f"https://{target['ip']}:{target['port']}{target['path']}")
    # Send the Authorization header over stdin, never in argv, env or a pod spec.
    result = subprocess.run(command, input=f'header = "Authorization: Basic {token}"\n',
                            capture_output=True, text=True, timeout=25)
    ok = False
    detail = 'network/TLS/curl failure'
    if result.returncode == 60:
        detail = 'TLS certificate verification failed'
    elif result.returncode in (7, 28):
        detail = 'unreachable or timed out'
    elif result.returncode == 0:
        body, _, code = result.stdout.rpartition('\n')
        if code in ('401', '403'):
            detail = 'authentication denied or account lacks access'
        elif code != '200':
            detail = 'unexpected HTTP status (redirects refused)'
        else:
            try:
                identity = json.loads(body)
                ok = isinstance(identity, dict) and identity.get('SerialNumber') == target['serial']
                detail = 'authenticated; device identity matches' if ok else 'device identity mismatch'
            except ValueError:
                detail = 'invalid Redfish response'
    return {'name': target['name'], 'ok': ok, 'detail': detail}


def ssh(target):
    with tempfile.TemporaryDirectory(prefix='dsx-ssh-') as directory:
        root = Path(directory)
        known = root/'known_hosts'; known.write_text(target['knownHosts']); known.chmod(0o600)
        askpass = root/'askpass'
        askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$DSX_SSH_PASSWORD"\n'); askpass.chmod(0o700)
        env = dict(os.environ, SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE='force',
                   DISPLAY=':0', DSX_SSH_PASSWORD=target['password'])
        result = subprocess.run(['ssh', '-F', '/dev/null', '-o', 'ConnectTimeout=5',
                                 '-o', 'ConnectionAttempts=1', '-o', 'NumberOfPasswordPrompts=1',
                                 '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}',
                                 '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'PubkeyAuthentication=no',
                                 '-o', 'PreferredAuthentications=password', '-o', 'LogLevel=ERROR',
                                 '-l', target['username'], target['ip'], 'true'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                env=env, start_new_session=True, timeout=20)
        ok = result.returncode == 0
        return {'name': target['name'], 'ok': ok,
                'detail': 'SSH login succeeded' if ok else 'SSH failed: check reachability, host key and credentials'}


def main():
    targets = json.load(sys.stdin)
    results = []
    for target in targets:
        try:
            results.append(ssh(target) if target.get('kind') == 'ssh' else redfish(target))
        except Exception:
            # Exception strings and endpoint responses can contain credentials.
            results.append({'name': target['name'], 'ok': False, 'detail': 'probe could not complete'})
    print(json.dumps(results))


if __name__ == '__main__':
    main()
