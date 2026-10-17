#!/usr/bin/env python3
"""Submit one NICo settings Application at a selected, additive rollout stage."""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate(v, live=False):
    if type(v.get('stage')) is not int or not 1 <= v['stage'] <= 6:
        raise ValueError('stage must be an integer from 1 through 6')
    n, d = v['network'], v['dpf']
    ips = [n[k] for k in ['apiVIP', 'dhcpVIP', 'pxeVIP', 'consoleVIP', 'resolverVIP']]
    ips += n['dnsVIPs'] + n['ntpVIPs'] + [d['dpuVIP']]
    if not n['dnsVIPs'] or not n['ntpVIPs']:
        raise ValueError('DNS and NTP VIP lists must not be empty')
    for addr in ips + [d['apiServerIP']] + n['upstreamDNS']:
        ipaddress.IPv4Address(addr)
    if len(ips) != len(set(ips)):
        raise ValueError('Every service VIP and DPU control-plane VIP must be unique')
    if d['apiServerIP'] in ips:
        raise ValueError('Management API IP must not overlap a service VIP')
    if type(d['apiServerPort']) is not int or not 1 <= d['apiServerPort'] <= 65535:
        raise ValueError('dpf.apiServerPort must be 1..65535')
    if type(d['virtualRouterID']) is not int or not 1 <= d['virtualRouterID'] <= 255:
        raise ValueError('dpf.virtualRouterID must be 1..255')
    for c in n['fabricCIDRs'] + n['denyCIDRs']: ipaddress.IPv4Network(c)
    for key, bounds in v['pools'].items():
        lo, hi = bounds['start'], bounds['end']
        if key == 'loopback': lo, hi = int(ipaddress.IPv4Address(lo)), int(ipaddress.IPv4Address(hi))
        else:
            if type(lo) is not int or type(hi) is not int:
                raise ValueError('Pool bounds must be integers')
            maximum = 4094 if key == 'vlan' else 16777215
            if not 1 <= lo <= hi <= maximum: raise ValueError('Invalid VLAN/VNI range')
        if lo > hi: raise ValueError('Pool start must be <= end')
    if v['metallb']['install']:
        ranges=[]
        for r in v['metallb']['addresses']:
            if '/' in r:
                net=ipaddress.IPv4Network(r); ranges.append((int(net.network_address),int(net.broadcast_address)))
            else:
                a,b=r.split('-'); ranges.append((int(ipaddress.IPv4Address(a)),int(ipaddress.IPv4Address(b))))
        # The DPU VIP belongs to keepalived, not the MetalLB allocator.
        for addr in ips[:-1]:
            if not any(lo <= int(ipaddress.IPv4Address(addr)) <= hi for lo,hi in ranges):
                raise ValueError('All NICo service VIPs must belong to a MetalLB range')
        if any(lo <= int(ipaddress.IPv4Address(d['dpuVIP'])) <= hi for lo,hi in ranges):
            raise ValueError('Keep the keepalived DPU VIP outside MetalLB ranges')
    def no_secrets(obj):
        if isinstance(obj,dict):
            for key,val in obj.items():
                if key.lower() in ['password','token','privatekey','bmcrootpassword','hostuefipassword','dpuuefipassword']:
                    raise ValueError('Credentials must not be stored in the settings Application')
                no_secrets(val)
        elif isinstance(obj,list):
            for val in obj: no_secrets(val)
    no_secrets(v)
    if live:
        raw=json.dumps(v)
        if 'CHANGE_ME' in raw or '.example.test' in raw:
            raise ValueError('Replace CHANGE_ME and example DNS names in your settings file')
        examples=[ipaddress.ip_network(x) for x in ['192.0.2.0/24','198.51.100.0/24','203.0.113.0/24']]
        if any(any(ipaddress.ip_address(ip) in net for net in examples) for ip in ips+[d['apiServerIP']]):
            raise ValueError('Replace the documentation-example addresses with allocated site IPs')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True)
    p.add_argument('--stage',type=int,choices=range(1,7),required=True)
    p.add_argument('--render-only',action='store_true',help='Print the settings Application; do not contact Kubernetes')
    a=p.parse_args()
    obj=yaml.safe_load(Path(a.config).read_text())
    if obj.get('kind')!='Application' or obj['metadata'].get('name')!='nico-stack' or obj['metadata'].get('namespace')!='argocd':
        raise ValueError('Use NICo/config.yaml: Application nico-stack in argocd')
    v=obj['spec']['source']['helm']['valuesObject']; v['stage']=a.stage
    validate(v,live=not a.render_only)
    # Use the local stack schema too: typos must not be silently ignored by Helm.
    subprocess.run(['helm','template','nico-stack',str(ROOT/'charts/stack'),'-f','-'],
                   input=yaml.safe_dump(v),text=True,stdout=subprocess.DEVNULL,check=True)
    if a.render_only:
        print(yaml.safe_dump(obj,sort_keys=False),end=''); return
    context=subprocess.check_output(['kubectl','config','current-context'],text=True).strip()
    kube=['kubectl','--context',context,'--request-timeout=30s']
    apps=json.loads(subprocess.check_output(kube+['get','applications','-n','argocd','-o','json'],text=True))['items']
    standalone={'dpf','dpf-platform','dpf-site','dpf-hbn','dpf-provisioning','dpf-operator-config','dpf-tenants'}
    if any(app['metadata']['name'] in standalone for app in apps):
        raise ValueError('Standalone DPF Applications exist. Plan an ownership migration or use a clean cluster.')
    prerequisites={2:['nico-cert-manager'],3:['nico-vault','nico-external-secrets','nico-postgres-operator'],
                   4:['nico-prerequisites'],5:['nico-dpf-operator','nico-kamaji','nico-dpf-argo','nico-maintenance','nico-nfd'],
                   6:['nico-prerequisites','nico-dpf-operator']}
    byname={app['metadata']['name']:app for app in apps}
    for name in prerequisites.get(a.stage,[]):
        st=byname.get(name,{}).get('status',{})
        if st.get('sync',{}).get('status')!='Synced' or st.get('health',{}).get('status')!='Healthy':
            raise ValueError(f'Wait for {name} to become Synced/Healthy before this stage')
    if a.stage>=6:
        for name in ['nico-vault-token','nico-vault-approle-tokens','ssh-host-key','nico-api-web-basic-auth',v['images']['pullSecret']]:
            subprocess.run(kube+['get','secret',name,'-n','nico-system','-o','name'],stdout=subprocess.DEVNULL,check=True)
    print(f'Context: {context}; submitting stage {a.stage}',flush=True)
    subprocess.run(kube+['apply','--server-side','--field-manager=nico-site-config','-f','-'],input=json.dumps(obj),text=True,check=True)
    print('Submitted. Argo sync is asynchronous; check Applications and workload readiness.')


if __name__=='__main__':
    try: main()
    except Exception as e:
        print('Stopped:',str(e) if isinstance(e,ValueError) else type(e).__name__,file=sys.stderr)
        raise SystemExit(1)
