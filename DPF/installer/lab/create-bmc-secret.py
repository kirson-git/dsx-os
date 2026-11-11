#!/usr/bin/env python3
"""Prompt for the shared BMC password and send it directly to kubectl stdin."""
import argparse
import base64
import getpass
import json
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        sys.exit('Run in a terminal to enter the shared BMC password.')
    password = getpass.getpass('Shared DPU BMC root password: ')
    if not password:
        sys.exit('Password is empty; no change made.')
    secret = {'apiVersion': 'v1', 'kind': 'Secret',
              'metadata': {'name': 'bmc-shared-password', 'namespace': 'dpf-operator-system'},
              'type': 'Opaque', 'data': {'password': base64.b64encode(password.encode()).decode()}}
    result = subprocess.run(['kubectl', f'--context={args.context}', '--request-timeout=30s',
                             'apply', '--server-side', '--field-manager=dpf-lab', '-f', '-'],
                            input=json.dumps(secret), text=True, capture_output=True)
    if result.returncode:
        # Do not echo an API error which could contain submitted Secret data.
        sys.exit('Secret update failed. Check context, namespace and Secret write permissions.')
    print('BMC password configured.')


if __name__ == '__main__':
    main()
