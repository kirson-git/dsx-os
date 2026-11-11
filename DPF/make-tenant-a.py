#!/usr/bin/env python3
"""Create the tenant-a files from the two-tenant example. Run in the DPF folder.

1. Edit the values below.
2. Run:  python3 make-tenant-a.py
The 15 files are written to tenant-a/. Running it again overwrites them.
Needs Python 3 with PyYAML. It only writes files; it does not touch a cluster.
"""
import pathlib, re, yaml
v = dict(
    api='192.0.2.20',          # please change here: management Kubernetes API address (port 6443)
    vip='192.0.2.203',         # please change here: free address for the tenant-a API, outside DHCP
    vip_if='enp7s0',           # please change here: interface on the management nodes that carries the VIP
    vrid=127,                  # please change here: VRRP router id, unique on that network (1 to 255)
    bmc='192.0.2.149',         # please change here: DPU BMC address
    serial='MT0000000000',     # please change here: DPU serial number
    opn='900-9D3B4-00CV-EA0',  # please change here: DPU ordering part number
    dns='192.0.2.53',          # please change here: DNS server the DPU uses
    vrf='TENANT_A',            # please change here: name of the tenant-a routing table
    vni=100010,                # please change here: L3 VNI of that VRF
    asn=65010,                 # please change here: BGP AS number of the DPU
    host_net='10.60.10.0/29',  # please change here: address block between server and DPU
    loopback='10.60.0.10/32',  # please change here: DPU loopback, the VXLAN tunnel source
)
src, out = pathlib.Path('profiles/two-tenant-hbn/desired'), pathlib.Path('tenant-a')
files = {
    '10-operator-config/dpfoperatorconfig-dpfoperatorconfig.yaml': '10-operator/operatorconfig.yaml',
    '20-tenants/namespace-tenant-asia.yaml': '20-cluster/namespace.yaml',
    '20-tenants/dpucluster-tenant-asia.yaml': '20-cluster/dpucluster.yaml',
    '30-hbn/dpuservicetemplate-doca-hbn-asia.yaml': '30-hbn/hbn-template.yaml',
    '30-hbn/dpuserviceconfiguration-doca-hbn-asia.yaml': '30-hbn/hbn-config.yaml',
    '30-hbn/dpuserviceipam-asia-host.yaml': '30-hbn/ipam-host.yaml',
    '30-hbn/dpuserviceipam-asia-loopback.yaml': '30-hbn/ipam-loopback.yaml',
    '30-hbn/dpuserviceinterface-asia-p0.yaml': '30-hbn/if-p0.yaml',
    '30-hbn/dpuserviceinterface-asia-p1.yaml': '30-hbn/if-p1.yaml',
    '30-hbn/dpuserviceinterface-asia-pf0hpf.yaml': '30-hbn/if-pf0hpf.yaml',
    '40-provisioning/bfb-bf-bundle-v26.4.0.yaml': '40-hardware/bfb.yaml',
    '40-provisioning/dpuflavor-hbn-asia-example-v26.4.0.yaml': '40-hardware/dpuflavor.yaml',
    '40-provisioning/dpudevice-example-asia.yaml': '40-hardware/dpudevice.yaml',
    '40-provisioning/dpunode-dpu-node-example-asia.yaml': '40-hardware/dpunode.yaml',
    '40-provisioning/dpudeployment-hbn-asia.yaml': '40-hardware/dpudeployment.yaml',
}
swaps = [  # example name or value -> tenant-a name or your value, in this order
    (re.escape('dpu-node-example-asia'), 'dpu-node-tenant-a'), (re.escape('example-asia'), 'tenant-a-dpu1'),
    ('EXAMPLEASIA', v['serial']), (re.escape('hbn-asia-example-v26.4.0'), 'hbn-tenant-a-v26.4.0'),
    ('tenant-asia', 'tenant-a'), ('60-asia-lab-dns', '60-tenant-a-dns'), (r'\basia\b', 'tenant-a'),
    ('vrf1: ASIA', 'vrf1: ' + v['vrf']), (re.escape('192.0.2.149'), v['bmc']), ('900-9D3B4-00CV-EA0', v['opn']),
    ('l3vni1: 100002', 'l3vni1: %s' % v['vni']), ('bgp_autonomous_system: 65201', 'bgp_autonomous_system: %s' % v['asn']),
    (r'addresses: \[192\.0\.2\.53, 198\.51\.100\.53, 203\.0\.113\.53\]', 'addresses: [%s]' % v['dns']),
]
def fix(x):
    if isinstance(x, dict): return {fix(k): fix(i) for k, i in x.items()}
    if isinstance(x, list): return [fix(i) for i in x]
    if isinstance(x, str):
        for a, b in swaps: x = re.sub(a, lambda m, b=b: b, x)
    return x
yaml.add_representer(str, lambda d, s: d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None))
for s, d in files.items():
    doc = fix(yaml.safe_load((src / s).read_text()))
    if doc['kind'] == 'DPFOperatorConfig': doc['spec']['overrides']['kubernetesAPIServerVIP'] = v['api']
    if doc['kind'] == 'DPUCluster': doc['spec']['clusterEndpoint']['keepalived'].update(interface=v['vip_if'], vip=v['vip'], virtualRouterID=v['vrid'])
    if doc['kind'] == 'DPUServiceIPAM': doc['spec']['ipv4Network']['network'] = v['host_net'] if 'host' in d else v['loopback']
    path = out / d; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(doc, sort_keys=False, width=200)); print('wrote', path)
