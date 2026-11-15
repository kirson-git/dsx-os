#!/usr/bin/env bash
# Turn one values file into the YAML files of one tenant.
# A tenant here is: one DPU cluster + one HBN network (VRF) + one DPU.
#
#   bash dpu-lab/new-tenant.sh dpu-lab/tenant-europe.conf           # first tenant: compare with the numbered folders
#   bash dpu-lab/new-tenant.sh dpu-lab/tenant-europe.conf --force   # first tenant: write its values into them
#   bash dpu-lab/new-tenant.sh dpu-lab/tenant-asia.conf             # second tenant: writes dpu-lab/tenant-asia/
#
# Keep your real values out of Git: copy the .conf files to dpu-lab/site/ (Git ignores that
# folder), edit the copies, and run the script on them. The YAML is then written next to them:
#
#   bash dpu-lab/new-tenant.sh dpu-lab/site/tenant-europe.conf      # writes dpu-lab/site/1-dpf-settings ... 4-dpu-install
#   bash dpu-lab/new-tenant.sh dpu-lab/site/tenant-asia.conf        # writes dpu-lab/site/tenant-asia/
#
# Add --force to overwrite files that the script wrote before.
# It only writes files. It does not touch the cluster, the switch or a DPU.
set -eu
[ $# -ge 1 ] || { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
exec python3 -I - "$(cd "$(dirname "$0")" && pwd)" "$@" <<'PY'
import ipaddress, os, pathlib, re, sys

base = pathlib.Path(sys.argv[1]).resolve(); conf = pathlib.Path(sys.argv[2]); force = '--force' in sys.argv[3:]
ALL = ['1-dpf-settings', '2-dpu-cluster', '3-hbn-network', '4-dpu-install']
TENANT = ALL[1:]             # folder 1 and the OS image are shared by all tenants
SHARED = {'bfb.yaml'}
KEYS = ['NAME', 'VIP', 'VRID', 'DPU_BMC', 'SERIAL', 'OPN', 'VRF', 'L3VNI', 'ASN', 'HOST_NET', 'LOOPBACK']
OPTIONAL = ['API_IP', 'API_PORT', 'VIP_IF', 'DNS']
FIRST = 'lab'                # the name inside the objects of the first tenant

def stop(msg):
    print('STOP: ' + msg); sys.exit(1)
def read(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            k, val = line.split('=', 1); out[k.strip()] = val.strip()
    return out
def show(path):
    try: return os.path.relpath(path)
    except ValueError: return str(path)

# ---- read and check the values file ----
if not conf.is_file(): stop('values file not found: %s' % conf)
home = conf.resolve().parent; in_place = home == base
v = read(conf)
missing = [k for k in KEYS if not v.get(k)]
if missing: stop('missing in %s: %s' % (conf.name, ', '.join(missing)))
n = v['NAME']
if not re.fullmatch(r'[a-z][a-z0-9-]{1,19}', n): stop('NAME must be 2 to 20 lower-case letters, digits or "-"')
try:
    ipaddress.ip_address(v['VIP']); ipaddress.ip_address(v['DPU_BMC'])
    host = ipaddress.ip_network(v['HOST_NET']); loop = ipaddress.ip_network(v['LOOPBACK'])
    if v.get('API_IP'): ipaddress.ip_address(v['API_IP'])
    dns = [str(ipaddress.ip_address(d.strip())) for d in v.get('DNS', '').split(',') if d.strip()]
except ValueError as e: stop('bad address: %s' % e)
if loop.prefixlen != 32: stop('LOOPBACK must end in /32')
if host.num_addresses < 4: stop('HOST_NET is too small: the server and HBN each need an address')
for k, lo, hi in (('VRID', 1, 255), ('L3VNI', 1, 16777215), ('ASN', 1, 4294967295)):
    if not v[k].isdigit() or not lo <= int(v[k]) <= hi: stop('%s must be a number from %d to %d' % (k, lo, hi))

# ---- no value may repeat between tenants ----
UNIQUE = ['VIP', 'VRID', 'DPU_BMC', 'SERIAL', 'VRF', 'L3VNI', 'ASN']
def clash(other):
    same = [k for k in UNIQUE if v[k] == other.get(k)]
    try:
        if host.overlaps(ipaddress.ip_network(other['HOST_NET'])): same.append('HOST_NET')
        if loop.overlaps(ipaddress.ip_network(other['LOOPBACK'])): same.append('LOOPBACK')
    except (KeyError, ValueError): pass
    return same
for other_conf in sorted(home.glob('tenant-*.conf')):
    if other_conf.resolve() == conf.resolve(): continue
    o = read(other_conf)
    if o.get('NAME') == n: stop('%s uses the same NAME' % other_conf.name)
    same = clash(o)
    if same: stop('these values are already used in %s: %s' % (other_conf.name, ', '.join(same)))
if in_place and n != FIRST:   # the numbered folders are the first tenant
    def find(rel, pattern):
        m = re.search(pattern, (base / rel).read_text(), re.M)
        return m.group(1) if m else ''
    first = {'VIP': find('2-dpu-cluster/dpucluster.yaml', r'^\s*vip: (\S+)'),
             'VRID': find('2-dpu-cluster/dpucluster.yaml', r'^\s*virtualRouterID: (\S+)'),
             'DPU_BMC': find('4-dpu-install/dpudevice.yaml', r'^\s*bmcIp: (\S+)'),
             'SERIAL': find('4-dpu-install/dpudevice.yaml', r'^\s*serialNumber: (\S+)'),
             'VRF': find('3-hbn-network/hbn-config.yaml', r'^\s*vrf1: (\S+)'),
             'L3VNI': find('3-hbn-network/hbn-config.yaml', r'^\s*l3vni1: (\S+)'),
             'ASN': find('3-hbn-network/hbn-config.yaml', r'^\s*bgp_autonomous_system: (\S+)'),
             'HOST_NET': find('3-hbn-network/ipam-host.yaml', r'^\s*network: (\S+)'),
             'LOOPBACK': find('3-hbn-network/ipam-loopback.yaml', r'^\s*network: (\S+)')}
    same = clash(first)
    if same: stop('these values are already used by the first tenant (the numbered folders): %s' % ', '.join(same))

# ---- put the values into one file ----
def setkey(text, key, value):
    return re.sub(r'(^\s*%s: )\S+' % re.escape(key), lambda m: m.group(1) + value, text, flags=re.M)
def values(text, name):
    for key, k in (('vip', 'VIP'), ('virtualRouterID', 'VRID'), ('bmcIp', 'DPU_BMC'),
                   ('provisioning.dpu.nvidia.com/dpudevice-bmc-ip', 'DPU_BMC'), ('serialNumber', 'SERIAL'),
                   ('provisioning.dpu.nvidia.com/dpudevice-psid', 'SERIAL'), ('opn', 'OPN'),
                   ('provisioning.dpu.nvidia.com/dpudevice-opn', 'OPN'), ('vrf1', 'VRF'), ('l3vni1', 'L3VNI'),
                   ('bgp_autonomous_system', 'ASN')):
        text = setkey(text, key, v[k])
    if name == 'ipam-host.yaml': text = setkey(setkey(text, 'network', v['HOST_NET']), 'prefixSize', str(host.prefixlen))
    if name == 'ipam-loopback.yaml': text = setkey(text, 'network', v['LOOPBACK'])
    if name == 'dpucluster.yaml' and v.get('VIP_IF'): text = setkey(text, 'interface', v['VIP_IF'])
    if name == 'dpuflavor.yaml' and dns:
        text = re.sub(r'(addresses: )\[[^\]]*\]', lambda m: m.group(1) + '[' + ', '.join(dns) + ']', text)
    if name == 'operatorconfig.yaml':
        if v.get('API_IP'): text = setkey(text, 'kubernetesAPIServerVIP', v['API_IP'])
        if v.get('API_PORT'): text = setkey(text, 'kubernetesAPIServerPort', v['API_PORT'])
    return text

# ---- the first tenant, values file next to the numbered folders: compare, or write in place ----
if n == FIRST and in_place:
    changed = []
    for folder in ALL:
        for src in sorted((base / folder).glob('*.yaml')):
            if src.name in SHARED: continue
            old = src.read_text(); new = values(old, src.name)
            if new != old:
                changed.append('%s/%s' % (folder, src.name))
                if force: src.write_text(new)
    if not changed:
        print('Tenant %s is the first tenant: its files are the numbered folders.' % n)
        print('OK: all values in %s match those files. Nothing to do.' % conf.name)
    elif force:
        print('Wrote the values of %s into: %s' % (conf.name, ', '.join(changed)))
        print('Apply the changed folders with kubectl when you are ready. A change to a DPU that is')
        print('already installed can reinstall it: read README step 6 first.')
    else:
        print('Tenant %s is the first tenant: its files are the numbered folders.' % n)
        print('These files hold other values than %s: %s' % (conf.name, ', '.join(changed)))
        print('Nothing was written. Add --force to write the values of %s into them.' % conf.name)
        sys.exit(1)
    sys.exit(0)

# ---- every other case: write a generated copy next to the values file ----
if n == FIRST:
    out = home; folders = ALL; skip = set(); names = []
    exists = any((out / f).exists() for f in folders)
else:
    out = home / ('tenant-' + n); folders = TENANT; skip = SHARED
    names = [('dpu-cluster-lab', 'dpu-cluster-' + n), ('dpu-node-lab', 'dpu-node-' + n), ('doca-hbn-lab', 'doca-hbn-' + n),
             ('hbn-lab', 'hbn-' + n), ('lab-dpu1', n + '-dpu1'), ('lab-p0', n + '-p0'), ('lab-p1', n + '-p1'),
             ('lab-pf0hpf', n + '-pf0hpf'), ('lab-host', n + '-host'), ('lab-loopback', n + '-loopback'),
             ('tenant: lab', 'tenant: ' + n), ('nameSuffix: lab', 'nameSuffix: ' + n)]
    exists = out.exists()
if exists and not force: stop('%s already holds generated files. Add --force to overwrite them.' % show(out))
count = 0
for folder in folders:
    for src in sorted((base / folder).glob('*.yaml')):
        if src.name in skip: continue
        t = src.read_text()
        for old, new in names: t = t.replace(old, new)
        t = values(t, src.name)
        if n != FIRST:
            left = re.findall(r'(?<![a-z0-9])lab(?![a-z0-9])', t.replace('60-lab-dns', ''))
            if left: stop('%s still holds the name of the first tenant. Nothing more was written.' % src.name)
        dst = out / folder / src.name; dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(t); count += 1

gw = host.network_address + 2; srv = host.network_address + 1; o = show(out)
print('Wrote %d files to %s/ (%s)' % (count, o, ', '.join(folders)))
print('''
Tenant %(n)s: DPU cluster dpu-cluster-%(n)s at %(VIP)s, VRF %(VRF)s, VNI %(L3VNI)s, AS %(ASN)s, DPU %(SERIAL)s.

Next steps, from the DPF folder:
  1. Switch first: the ports of this DPU need remote-as %(ASN)s, VRF %(VRF)s with VNI %(L3VNI)s,
     and a prefix list that permits %(LOOPBACK)s. Check with: bash dpu-lab/get-values.sh --switch <user@switch>
  2. Apply the folders in order: %(apply)s
     After the last one DPF holds; nothing is written to the DPU yet.
  3. Release the hold, power-cycle the server and check, as in README steps 7 to 9.
     The object names end in "%(n)s", for example dpu-node-%(n)s-hold and dpu-node-%(n)s.
  4. On the server of this DPU: address %(srv)s/%(pfx)d, gateway %(gw)s (README step 10).
''' % dict(v, n=n, srv=srv, gw=gw, pfx=host.prefixlen, apply=', '.join('kubectl apply -f %s/%s/' % (o, f) for f in folders)))
PY
