"""Guided BMC access check from a chosen Kubernetes node's physical NIC."""
import argparse
import getpass
import ipaddress
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

from nics import IMAGE
from ui import banner, color, tone

BASE = Path(__file__).resolve().parents[1]
NAMESPACE = 'dpf-operator-system'


def targets(value):
    values = [v.strip() for v in value.split(',')]
    if not 1 <= len(values) <= 16 or len(set(values)) != len(values):
        raise ValueError('Enter 1-16 distinct BMC IPv4 addresses.')
    for value in values:
        ip = ipaddress.IPv4Address(value)
        if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local or value == '255.255.255.255':
            raise ValueError('Use unicast BMC IPv4 addresses.')
    return values


def quoted(value):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Credentials must not contain control characters.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def curl_config(ip, user, password, insecure, source=None, path='/redfish/v1/Systems'):
    lines = ['url = '+quoted('https://'+ip+path), 'noproxy = "*"']
    if password is not None:
        lines.append('user = '+quoted(user+':'+password))
        lines.append('basic')
    if source:
        lines.append('interface = '+quoted(source))
    if insecure:
        lines.append('insecure')
    return '\n'.join(lines)+'\n'


def evaluate(anonymous, status, body):
    if status == 401:
        return 'AUTH FAILED'
    if status == 403:
        return 'FORBIDDEN'
    if status != 200:
        return f'HTTP {status}'
    try:
        obj = json.loads(body)
        valid = (isinstance(obj, dict) and isinstance(obj.get('Members'), list)
                 and 'ComputerSystemCollection' in obj.get('@odata.type', ''))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        return 'NOT REDFISH'
    return 'PASS' if anonymous in (401, 403) else 'UNVERIFIED'


def manifest(name, node='node1'):
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': name, 'namespace': NAMESPACE,
                         'labels': {'app.kubernetes.io/name': 'dpf-bmc-check'}},
            'spec': {'nodeName': node, 'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet',
                     'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                     'activeDeadlineSeconds': 900, 'terminationGracePeriodSeconds': 1,
                     'tolerations': [{'operator': 'Exists'}],
                     'securityContext': {'runAsNonRoot': True, 'runAsUser': 65534,
                                         'seccompProfile': {'type': 'RuntimeDefault'}},
                     'containers': [{'name': 'check', 'image': IMAGE, 'command': ['sleep','900'],
                                     'securityContext': {'allowPrivilegeEscalation': False,
                                                         'readOnlyRootFilesystem': True,
                                                         'capabilities': {'drop': ['ALL']}},
                                     'resources': {'requests': {'cpu': '10m','memory': '32Mi'},
                                                   'limits': {'cpu': '100m','memory': '128Mi'}}}]}}


def run(k, args, **kwargs):
    return subprocess.run([*k, *args], text=True, capture_output=True, timeout=40, **kwargs)


def wait_ready(k, name, runner=None):
    runner = runner or run
    deadline = time.monotonic()+150
    next_update = time.monotonic()+15
    while time.monotonic() < deadline:
        result = runner(k, ['-n',NAMESPACE,'get','pod',name,'-o','json'])
        if result.returncode:
            raise RuntimeError('Cannot read the diagnostic pod.')
        pod = json.loads(result.stdout)
        if any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in pod.get('status',{}).get('conditions',[])):
            return pod['spec']['nodeName']
        if pod.get('status',{}).get('phase') in ('Failed','Succeeded'):
            raise RuntimeError('Diagnostic pod stopped before the check.')
        if time.monotonic() >= next_update:
            print('  Waiting for the diagnostic pod...', flush=True)
            next_update = time.monotonic()+15
        time.sleep(2)
    raise RuntimeError('Diagnostic pod not ready after 150s; check scheduling, image pulls and admission policy.')


def request(k, name, ip, user, password, insecure, source=None, path='/redfish/v1/Systems', runner=None):
    runner = runner or run
    config = curl_config(ip,user,password,insecure,source,path)
    # The credential travels only in the encrypted exec stdin stream, never Pod
    # metadata, command arguments, a Secret, a log file, or a local config file.
    result = runner(k, ['-n',NAMESPACE,'exec','-i',name,'--','curl','--disable','--silent','--show-error',
                     '--connect-timeout','5','--max-time','15','--max-filesize','1048576',
                     '--config','-','--write-out','\n%{http_code}'], input=config)
    if result.returncode:
        return 0, '', {28:'TIMEOUT',60:'TLS ERROR',35:'TLS ERROR',7:'UNREACHABLE'}.get(result.returncode,'PROBE ERROR')
    try:
        body, status = result.stdout.rsplit('\n',1)
        return int(status), body, None
    except ValueError:
        return 0, '', 'PROBE ERROR'


def nic_source(k, name, interface, runner=None):
    runner = runner or run
    result = runner(k, ['-n',NAMESPACE,'exec',name,'--','sh','-c',
                    '[ -e "/sys/class/net/$1/device" ] || exit 4; ip -j -4 address show dev "$1"',
                    'inspect',interface])
    if result.returncode:
        raise RuntimeError('NIC is missing or is not hardware-backed. Use menu 4 to inspect node NICs.')
    links = json.loads(result.stdout)
    addresses = [a for link in links for a in link.get('addr_info',[])
                 if a.get('family') == 'inet' and a.get('scope') == 'global']
    if not addresses:
        raise RuntimeError('Selected NIC has no global IPv4 address. Configure it on the node first.')
    print('\n  NIC             IP / PREFIX')
    for i, address in enumerate(addresses,1):
        print(f'  {i}. {interface:<12} {address["local"]}/{address["prefixlen"]}')
    choice = 1
    if len(addresses) > 1:
        choice = int(input('Source address [1]: ').strip() or '1')
        if not 1 <= choice <= len(addresses):
            raise ValueError('Invalid source address selection.')
    return addresses[choice-1]['local']


def route_matches(k, name, ip, source, interface, runner=None):
    runner = runner or run
    result = runner(k, ['-n',NAMESPACE,'exec',name,'--','ip','-j','route','get',ip,'from',source])
    if result.returncode:
        return False
    routes = json.loads(result.stdout)
    return bool(routes) and all(r.get('dev') == interface for r in routes)


def check(k, ips, user, password, insecure, node='node1', interface='enp7s0'):
    name = 'dpf-bmc-'+uuid.uuid4().hex[:16]
    results=[]
    cleanup_ok=True
    try:
        created=run(k,['create','-f','-'],input=json.dumps(manifest(name,node)))
        if created.returncode:
            raise RuntimeError('Cannot create the diagnostic pod. Check namespace, pod permissions and admission policy.')
        wait_ready(k,name)
        source=nic_source(k,name,interface)
        banner('BMC access')
        print(f'Node: {node} | NIC: {interface} | Source: {source}')
        print('TLS: '+('certificate verification disabled (lab)' if insecure else 'certificate verification enabled'))
        print('\n  BMC IP            RESULT')
        for ip in ips:
            if not route_matches(k,name,ip,source,interface):
                status='WRONG / NO ROUTE'
            else:
                anonymous, _, error=request(k,name,ip,user,None,insecure,source)
                if error:
                    status=error
                elif anonymous not in (200,401,403):
                    status=f'HTTP {anonymous}'
                else:
                    code,body,error=request(k,name,ip,user,password,insecure,source)
                    status=error or evaluate(anonymous,code,body)
            results.append(status)
            print(f'  {ip:<17} '+color(status, tone(status) or 'warn'),flush=True)
        if 'UNVERIFIED' in results:
            print('UNVERIFIED: endpoint permits anonymous access; password validity is not proven.')
        if 'TLS ERROR' in results:
            print('TLS ERROR: review certificate trust; setup can disable verification for lab BMCs.')
        if 'WRONG / NO ROUTE' in results:
            print('Route does not use the selected NIC. Review node addressing/routing or choose another NIC.')
        print('\nChecks node-network Redfish reads; controller-pod routing and provisioning permissions are separate.')
    finally:
        try:
            deleted=run(k,['-n',NAMESPACE,'delete','pod',name,'--ignore-not-found','--wait=true','--timeout=20s'])
            cleanup_ok=deleted.returncode == 0
        except (OSError,subprocess.SubprocessError):
            cleanup_ok=False
        if not cleanup_ok:
            print(f'Cleanup failed: remove pod {NAMESPACE}/{name} in the selected context.',file=sys.stderr)
    return 0 if results and all(r == 'PASS' for r in results) and cleanup_ok else 1


def ask(label, default):
    value=input(f'{label} [{default}]: ').strip()
    return value or default


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',required=True)
    args=parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(2,'Run --check-bmc in a terminal; the password is entered privately.\n')
    k=['kubectl',f'--context={args.context}','--request-timeout=30s']
    path=BASE/'state/bmc-settings.json'
    defaults={}
    for source in [BASE/'state/answers.json',path]:
        if source.is_file():
            values=json.loads(source.read_text())
            if values.get('context') == args.context:
                defaults.update(values)
    result=run(k,['get','nodes','-l','kubernetes.io/os=linux','-o','json'])
    if result.returncode:
        raise RuntimeError('Unable to list Kubernetes nodes.')
    nodes=[n for n in json.loads(result.stdout)['items'] if any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in n.get('status',{}).get('conditions',[]))]
    if not nodes:
        raise RuntimeError('No Ready Linux nodes available.')
    banner('BMC setup', args.context)
    for index,node in enumerate(nodes,1):
        address=next((a['address'] for a in node.get('status',{}).get('addresses',[]) if a['type']=='InternalIP'),'-')
        print(f'  {index}  {node["metadata"]["name"]:<30} {address}')
    default=next((str(i) for i,n in enumerate(nodes,1) if n['metadata']['name']==defaults.get('node')),'1')
    choice=int(ask('Node to test from',default))
    if not 1 <= choice <= len(nodes):
        raise ValueError('Invalid node selection.')
    node=nodes[choice-1]['metadata']['name']
    interface=ask('DPU-facing physical NIC (menu 4 lists NICs)',defaults.get('node_interface','enp7s0'))
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}',interface):
        raise ValueError('Invalid NIC name.')
    ips=targets(ask('DPU BMC IPv4 addresses, comma separated',','.join(defaults.get('bmc_ips',['192.0.2.146','192.0.2.149']))))
    user=ask('BMC username (DPF Zero Trust uses root)',defaults.get('bmc_user','root'))
    if ':' in user or len(user)>128:
        raise ValueError('Invalid BMC username.')
    quoted(user)
    tls=ask('Verify BMC TLS certificates? y/n','n' if defaults.get('insecure') else 'y').lower()
    if tls not in ('y','n'):
        raise ValueError('Choose y or n for TLS verification.')
    insecure=tls=='n'
    password=getpass.getpass('Shared BMC password (not saved): ')
    if not password:
        raise ValueError('Password is empty; no probe created.')
    quoted(password)
    settings={'context':args.context,'node':node,'node_interface':interface,'bmc_ips':ips,'bmc_user':user,'insecure':insecure}
    path.parent.mkdir(parents=True,exist_ok=True)
    # Contains connection settings only. Existing setup is intentionally updated.
    path.write_text(json.dumps(settings,indent=2)+'\n')
    print('Settings saved. Starting temporary node-network probe...',flush=True)
    return check(k,ips,user,password,insecure,node,interface)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM,lambda *_: sys.exit(143))
    try:
        sys.exit(main())
    except (KeyboardInterrupt,EOFError):
        sys.exit('\nBMC check cancelled.')
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        # Never print subprocess output: it could contain the submitted credential.
        message=str(error) if isinstance(error,RuntimeError) else 'Check setup values, kubectl access and the selected node.'
        print('BMC check stopped: '+message,file=sys.stderr)
        sys.exit(1)
