#!/usr/bin/env python3
"""Privately create/update DPF's shared BMC password Secret in the current cluster."""
import argparse
import getpass
import json
import pathlib
import subprocess
import sys


def install(password):
    if not password or '\n' in password or '\r' in password:
        raise ValueError('Password must be nonempty and contain no newline; file input must have no trailing newline')
    obj = {'apiVersion': 'v1', 'kind': 'Secret',
           'metadata': {'name': 'bmc-shared-password', 'namespace': 'dpf-operator-system'},
           'type': 'Opaque', 'stringData': {'password': password}}
    # STDIN avoids credentials in argv, shell history and repository files.
    result = subprocess.run(['kubectl', 'apply', '--server-side', '--field-manager=dsx-private-credentials', '-f', '-'],
                            input=json.dumps(obj), text=True, capture_output=True)
    if result.returncode:
        # Admission errors can echo payloads. Do not print their raw text.
        raise ValueError('Secret write failed. Check current context, RBAC, namespace and field ownership; no secret output was logged')
    print('Saved Secret dpf-operator-system/bmc-shared-password; value not displayed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--password-file', type=pathlib.Path, help='Existing private file outside the checkout, with no trailing newline; otherwise prompt without echo')
    args = parser.parse_args()
    try:
        if args.password_file:
            source = args.password_file.resolve()
            checkout = pathlib.Path(__file__).resolve().parents[2]
            if source == checkout or checkout in source.parents:
                raise ValueError('Credential file must be outside the repository')
            if source.stat().st_mode & 0o077:
                raise ValueError('Credential file must not be accessible to group/other; use mode 600')
            password = source.read_text()
        else:
            if not sys.stdin.isatty():
                raise ValueError('Use an interactive terminal or --password-file; piped password input is not supported')
            password = getpass.getpass('DPF shared BMC password: ')
        install(password)
        return 0
    except (ValueError, OSError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
