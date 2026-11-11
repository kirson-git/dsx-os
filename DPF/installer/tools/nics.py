"""Generate least-privilege network inventory probes and summarize their logs."""
import json
import ipaddress
from pathlib import Path
import sys

IMAGE = 'nicolaka/netshoot@sha256:7f08c4aff13ff61a35d30e30c5c1ea8396eac6ab4ce19fd02d5a4b3b5d0d09a2'

# hostNetwork exposes the node network namespace. No host mount, host PID,
# NET_ADMIN, privileged mode, service-account token, or network write commands.
PROBE = r'''
set -eu
links=$(ip -j address show)
routes=$(ip -j route show table all)
devices=$(
  for path in /sys/class/net/*; do
    name=${path##*/}
    kind=virtual
    [ ! -e "$path/device" ] || kind=device-backed
    driver=$(readlink "$path/device/driver" 2>/dev/null || true)
    speed=$(cat "$path/speed" 2>/dev/null || true)
    jq -n --arg name "$name" --arg kind "$kind" \
      --arg driver "${driver##*/}" --arg speed "$speed" \
      '{name:$name,kind:$kind,driver:$driver,speed_mbps:$speed}'
  done | jq -s .
)
jq -n --argjson links "$links" --argjson routes "$routes" \
  --argjson devices "$devices" '{links:$links,routes:$routes,devices:$devices}'
'''


def manifest(node, name):
    return {
        'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {'name': name, 'namespace': 'default',
                     'labels': {'app.kubernetes.io/name': 'dpf-nic-discovery'}},
        'spec': {
            'nodeName': node, 'hostNetwork': True,
            'automountServiceAccountToken': False,
            'restartPolicy': 'Never', 'activeDeadlineSeconds': 120,
            'terminationGracePeriodSeconds': 1,
            'tolerations': [{'operator': 'Exists'}],
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 65534,
                                'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{'name': 'inspect', 'image': IMAGE,
                            'command': ['/bin/sh', '-c', PROBE],
                            'securityContext': {'allowPrivilegeEscalation': False,
                                                'readOnlyRootFilesystem': True,
                                                'capabilities': {'drop': ['ALL']}},
                            'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'},
                                          'limits': {'cpu': '100m', 'memory': '128Mi'}}}]}}


def report(directory):
    root = Path(directory)
    failures = 0
    nodes = json.loads((root / 'nodes.json').read_text())['items']
    if not nodes:
        print('FAIL: no Linux nodes returned')
        return 1
    for node in nodes:
        name = node['metadata']['name']
        print(f'\nNODE: {name}')
        try:
            if (root / f'{name}.failed').exists():
                raise ValueError('probe did not complete successfully')
            data = json.loads((root / f'{name}.json').read_text())
            if not isinstance(data.get('links'), list) or not data['links']:
                raise ValueError('probe has no interface inventory')
            devices = {x['name']: x for x in data['devices']}
            if not isinstance(data['routes'], list):
                raise ValueError('invalid routes')
            rows = [['NIC', 'State', 'IP / prefix', 'Subnet', 'MAC', 'MTU']]
            for link in data['links']:
                interface = link['ifname']
                device = devices.get(interface, {})
                if device.get('kind') != 'device-backed':
                    continue
                addresses = []
                for address in link.get('addr_info', []):
                    value = ipaddress.ip_interface(f"{address['local']}/{address['prefixlen']}")
                    addresses.append((str(value), str(value.network)))
                for index, (address, subnet) in enumerate(addresses or [('unassigned', '-')]):
                    rows.append([interface if index == 0 else '',
                                 link.get('operstate', 'unknown') if index == 0 else '',
                                 address, subnet,
                                 link.get('address', '-') if index == 0 else '',
                                 str(link.get('mtu', '?')) if index == 0 else ''])
            if len(rows) == 1:
                print('No device-backed NICs found. Check VM attachment and Linux drivers.')
            widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
            border = '+' + '+'.join('-' * (width + 2) for width in widths) + '+'
            print(border)
            for index, row in enumerate(rows):
                print('| ' + ' | '.join(value.ljust(width) for value, width in zip(row, widths)) + ' |')
                if index == 0:
                    print(border)
            print(border)
        except (OSError, ValueError, TypeError, KeyError) as error:
            failures += 1
            print(f'FAIL: {name}: scan failed: {error}')
    print('\nNICs exposed to these Linux nodes only; VM adapters are included. Software interfaces are hidden.')
    print('No addresses or routes changed. Choose the OOB interface only after confirming its cabling/subnet on every node.')
    return 1 if failures else 0


if __name__ == '__main__':
    if sys.argv[1] == 'manifest':
        print(json.dumps(manifest(sys.argv[2], sys.argv[3]), indent=2))
    elif sys.argv[1] == 'report':
        sys.exit(report(sys.argv[2]))
    else:
        sys.exit('Unknown action')
