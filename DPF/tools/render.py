#!/usr/bin/env python3
"""Render the pinned DPF management platform for Argo CD; no cluster access."""
import argparse
import copy
import hashlib
import ipaddress
import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import yaml

ROOT=pathlib.Path(__file__).resolve().parents[1]
NS='dpf-operator-system'
ANN='argocd.argoproj.io/'
CLUSTER_KINDS={'CustomResourceDefinition','ClusterRole','ClusterRoleBinding','ClusterIssuer',
               'MutatingWebhookConfiguration','ValidatingWebhookConfiguration','StorageClass',
               'Namespace','DataStore','PriorityClass'}
COMPONENTS=[
 ('cert-manager','cert-manager-v1.19.3.tgz','cert-manager',0,'cert-manager'),
 ('local-path-provisioner','local-path-provisioner-0.0.34.tgz','local-path-provisioner',10,'local-path-provisioner'),
 ('kamaji','kamaji-1.2.0.tgz',NS,30,'kamaji'),
 ('node-feature-discovery','node-feature-discovery-chart-0.18.3.tgz',NS,40,'node-feature-discovery'),
 ('maintenance-operator','maintenance-operator-chart-0.3.0.tgz',NS,40,'maintenance-operator-chart'),
 ('dpf-operator','dpf-operator-v26.4.0.tgz',NS,50,None),
]

def validate(cfg):
    git=cfg['git']; op=cfg['operator']; storage=cfg['storage']
    url=git['repoURL']; parsed=urlparse(url)
    if 'CHANGE-ME' in url or parsed.scheme not in ('https','ssh') or not parsed.hostname or parsed.password or parsed.query or parsed.fragment or (parsed.scheme=='https' and parsed.username):
        raise ValueError('git.repoURL must be a real HTTPS or ssh:// Git URL without embedded credentials')
    path=pathlib.PurePosixPath(git['path'])
    if not git['path'] or path.is_absolute() or '..' in path.parts or str(path)!=git['path'] or not re.fullmatch(r'[A-Za-z0-9_./-]+',git['path']):
        raise ValueError('git.path must be a normal relative repository path')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',git['revision']):raise ValueError('Invalid Git revision')
    if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?',cfg['argoNamespace']) or len(cfg['argoNamespace'])>63:raise ValueError('Invalid Argo namespace')
    if not re.fullmatch(r'1\.\d+\.\d+',cfg['kubernetesVersion']):raise ValueError('kubernetesVersion requires major.minor.patch')
    if type(storage['installLocalPath']) is not bool or type(op['enabled']) is not bool:raise ValueError('Use YAML booleans for enabled/installLocalPath')
    if not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?',storage['className']):raise ValueError('Invalid StorageClass name')
    if storage['installLocalPath'] and storage['className']!='local-path':raise ValueError('Bundled storage creates class local-path; disable installLocalPath to reuse another class')
    if op['mode'] not in ('zero-trust','host-trusted'):raise ValueError('operator.mode must be zero-trust or host-trusted')
    if type(op['apiServerPort']) is not int or not 1<=op['apiServerPort']<=65535:raise ValueError('apiServerPort must be an integer from 1 to 65535')
    if op['enabled'] and op['mode']=='zero-trust':
        host=op['apiServerHost']
        try:ipaddress.ip_address(host)
        except ValueError:
            if not isinstance(host,str) or host=='CHANGE-ME' or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?',host):raise ValueError('Set operator.apiServerHost to the reachable management API host, without scheme/port')
    validate_tenants(cfg)
    return cfg

def enabled_tenants(cfg):
    tenants=cfg.get('tenants',{})
    return tenants.get('items',[]) if tenants.get('enabled',False) else []

def validate_tenants(cfg):
    tenants=cfg.get('tenants',{})
    if not isinstance(tenants,dict) or type(tenants.get('enabled',False)) is not bool:
        raise ValueError('tenants must be a mapping with a boolean enabled')
    if not tenants.get('enabled',False):return
    if not cfg['operator']['enabled']:
        raise ValueError('Enabled tenants require operator.enabled: true so Kamaji cluster management runs')
    items=tenants.get('items')
    if not isinstance(items,list) or not items:raise ValueError('Enabled tenants require a nonempty items list')
    names=set();vips=set();router_ids=set()
    for tenant in items:
        if not isinstance(tenant,dict):raise ValueError('Each tenant must be a mapping')
        name=tenant.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]*[a-z0-9])?',name) or len(name)>56:
            raise ValueError('Tenant name must be a lowercase DNS label, 1-56 characters')
        vip=tenant.get('vip','')
        if not isinstance(vip,str):raise ValueError('Tenant vip must be an IPv4 address string')
        ip=ipaddress.IPv4Address(vip)
        if ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_link_local or int(ip)==2**32-1:
            raise ValueError('Tenant vip must be a usable unicast IPv4 address reserved by your network administrator')
        if vip==cfg['operator']['apiServerHost']:raise ValueError('Tenant VIP must differ from management API address')
        interface=tenant.get('interface','')
        if not isinstance(interface,str) or interface=='CHANGE-ME' or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}',interface):
            raise ValueError('Tenant interface must be the management-node interface name, 1-15 characters')
        router_id=tenant.get('virtualRouterID')
        if type(router_id) is not int or not 1<=router_id<=255:raise ValueError('Tenant virtualRouterID must be an integer from 1 to 255')
        max_nodes=tenant.get('maxNodes',1000)
        if type(max_nodes) is not int or not 1<=max_nodes<=1000:raise ValueError('Tenant maxNodes must be an integer from 1 to 1000')
        if name in names or vip in vips or router_id in router_ids:
            raise ValueError('Tenant names, VIPs and virtualRouterIDs must each be unique in this kit')
        names.add(name);vips.add(vip);router_ids.add(router_id)

def tenant_resources(cfg):
    objects=[]
    for tenant in enabled_tenants(cfg):
        name='tenant-'+tenant['name']
        labels={'customer.dpf.nvidia.com/tenant':tenant['name']}
        namespace={'apiVersion':'v1','kind':'Namespace','metadata':{'name':name,'labels':labels}}
        cluster={'apiVersion':'provisioning.dpu.nvidia.com/v1alpha1','kind':'DPUCluster',
            'metadata':{'name':name,'namespace':name,'labels':labels},
            'spec':{'type':'kamaji','maxNodes':tenant.get('maxNodes',1000),
                'clusterEndpoint':{'keepalived':{
                    'interface':tenant['interface'],'vip':tenant['vip'],'virtualRouterID':tenant['virtualRouterID'],
                    'nodeSelector':{'node-role.kubernetes.io/control-plane':''}}}}}
        objects.extend([prepare_object(namespace,'tenants',-30),prepare_object(cluster,'tenants',70)])
    return objects

def load_config(path):
    cfg=yaml.safe_load(pathlib.Path(path).read_text())
    return validate(cfg)

def operator_config(cfg):
    op=cfg['operator']
    spec={'provisioningController':{'dmsTimeout':900},'kamajiClusterManager':{'disable':False},
          'overrides':{'argoCDNamespace':cfg['argoNamespace']}}
    if op['mode']=='zero-trust':
        spec['overrides'].update(kubernetesAPIServerVIP=op['apiServerHost'],kubernetesAPIServerPort=op['apiServerPort'])
        spec['dpuDetector']={'disable':True}
        spec['provisioningController']['installInterface']={'installViaRedfish':{'skipDPUNodeDiscovery':False}}
    return {'apiVersion':'operator.dpu.nvidia.com/v1alpha1','kind':'DPFOperatorConfig',
            'metadata':{'name':'dpfoperatorconfig','namespace':NS},'spec':spec}

def prepare_object(original,component,wave):
    obj=copy.deepcopy(original);meta=obj.setdefault('metadata',{});ann=meta.setdefault('annotations',{})
    kind=obj['kind'];hook=ann.get('helm.sh/hook','');name=meta['name']
    if kind=='Secret' and (obj.get('data') or obj.get('stringData')):raise ValueError(f'Refusing to write secret material: {name}')
    if hook.startswith('test'):return None
    if hook in ('pre-delete','post-delete'):return None # Never automatically dismantle the etcd store.
    if hook:
        if component!='kamaji':raise ValueError(f'Unreviewed Helm hook: {component}/{name}: {hook}')
        if kind=='Job':
            waves={'kamaji-etcd-setup-1':21,'kamaji-etcd-setup-2':31}
            if name not in waves:raise ValueError(f'Unreviewed Kamaji Job: {name}')
            wave=waves[name]
            ann[ANN+'hook']='Sync'
            ann[ANN+'hook-delete-policy']='BeforeHookCreation'
        else:
            wave=20 # Persistent SA/RBAC/config precede certificate-generation Job.
    if kind=='CustomResourceDefinition':wave=-20
    if kind=='DataStore':wave=32
    if kind=='MaintenanceOperatorConfig':wave=41
    for key in list(ann):
        if key.startswith('helm.sh/hook'):del ann[key]
    if ann.pop('helm.sh/resource-policy',None)=='keep':ann[ANN+'sync-options']='Delete=false,Prune=false'
    if kind=='CustomResourceDefinition':
        options=ann.get(ANN+'sync-options','').split(',') if ann.get(ANN+'sync-options') else []
        options.append('ServerSideApply=true')
        ann[ANN+'sync-options']=','.join(options)
    ann[ANN+'sync-wave']=str(wave)
    meta.setdefault('labels',{})['customer.dpf.nvidia.com/component']=component
    if component=='kamaji' and kind=='Job' and name=='kamaji-etcd-setup-1':
        # The upstream shell uses bash redirection under /bin/sh; use portable syntax.
        container=obj.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[{}])[0]
        if container.get('args'):
            script=container['args'][0].replace('&>/dev/null','>/dev/null 2>&1')
            guard='''set -eu
ca=no; client=no
kubectl get secret kamaji-etcd-certs -n dpf-operator-system >/dev/null 2>&1 && ca=yes
kubectl get secret kamaji-etcd-root-client-certs -n dpf-operator-system >/dev/null 2>&1 && client=yes
if [ "$ca" != "$client" ]; then
  echo "Incomplete existing etcd certificate pair; recover the matching secrets before retrying." >&2
  exit 1
fi
'''
            container['args'][0]=guard+script
    if component=='kamaji' and kind=='Job':
        pod=obj.get('spec',{}).get('template',{}).get('spec',{})
        for container in pod.get('initContainers',[]):
            if container.get('name')=='cfssl':container['image']='cfssl/cfssl:v1.6.5'
        if name=='kamaji-etcd-setup-2':
            for container in pod.get('containers',[]):
                if container.get('name')=='etcd-client':
                    container['command']=['bash','-c',
                        'set -euo pipefail\n'
                        'etcdctl member list -w table\n'
                        'if ! etcdctl user get root >/dev/null 2>&1; then etcdctl user add --no-password=true root; fi\n'
                        'if ! etcdctl role get root >/dev/null 2>&1; then etcdctl role add root; fi\n'
                        'etcdctl user grant-role root root\n'
                        'etcdctl auth enable\n'
                        'etcdctl auth status\n']
    return obj

def application(cfg):
    return {'apiVersion':'argoproj.io/v1alpha1','kind':'Application',
      'metadata':{'name':'dpf-platform','namespace':cfg['argoNamespace'],
                  'labels':{'customer.dpf.nvidia.com/package':'dpf-platform-v26.4.0'}},
      'spec':{'project':'default','source':{'repoURL':cfg['git']['repoURL'],'targetRevision':cfg['git']['revision'],
        'path':cfg['git']['path'],'directory':{'recurse':False,'include':'*.yaml'}},
        'destination':{'server':'https://kubernetes.default.svc','namespace':NS},
        'syncPolicy':{'automated':{'prune':False,'selfHeal':True},
          'syncOptions':['ServerSideApply=true','ClientSideApplyMigration=false','FailOnSharedResource=true'],
          'retry':{'limit':5,'backoff':{'duration':'10s','factor':2,'maxDuration':'3m'}}}}}

def run(command):
    print('+ '+shlex.join(map(str,command)),file=sys.stderr)
    return subprocess.run(command,check=True,text=True,capture_output=True).stdout

def render(cfg,out):
    validate(cfg)
    out=pathlib.Path(out); out.mkdir(parents=True,exist_ok=True)
    resources=[]
    for namespace in [NS,'cert-manager']+(['local-path-provisioner'] if cfg['storage']['installLocalPath'] else []):
        resources.append(prepare_object({'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace}},'namespaces',-30))
    with tempfile.TemporaryDirectory() as temporary:
        for name,chart,namespace,wave,value_name in COMPONENTS:
            if name=='local-path-provisioner' and not cfg['storage']['installLocalPath']:continue
            command=['helm','template',name,str(ROOT/'charts'/chart),'--namespace',namespace,'--include-crds','--kube-version',cfg['kubernetesVersion']]
            if value_name:command+=['--values',str(ROOT/'values'/f'{value_name}.yaml')]
            if name=='kamaji':
                override={'defaultDatastoreName':'','replicaCount':2,'kamaji-etcd':{'persistentVolumeClaim':{'storageClassName':cfg['storage']['className']}}}
                override_path=pathlib.Path(temporary)/'kamaji.yaml';override_path.write_text(yaml.safe_dump(override));command+=['--values',str(override_path)]
            for obj in yaml.safe_load_all(run(command)):
                if not obj:continue
                if obj['kind'] not in CLUSTER_KINDS:obj['metadata'].setdefault('namespace',namespace)
                prepared=prepare_object(obj,name,wave)
                if prepared:resources.append(prepared)
    if cfg['operator']['enabled']:resources.append(prepare_object(operator_config(cfg),'operator-config',60))
    resources.extend(tenant_resources(cfg))
    keys=[(o['apiVersion'],o['kind'],o['metadata'].get('namespace',''),o['metadata']['name']) for o in resources]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate resource identity in rendered charts')
    images=set()
    def collect_images(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('containers','initContainers') and isinstance(item,list):
                    images.update(c['image'] for c in item if isinstance(c,dict) and 'image' in c)
                else:collect_images(item)
        elif isinstance(value,list):
            for item in value:collect_images(item)
    for obj in resources:
        if obj['kind']!='CustomResourceDefinition':collect_images(obj)
    images=sorted(images)
    payload='# Generated by tools/render.py from bundled pinned charts. Do not hand-edit.\n'+yaml.safe_dump_all(resources,sort_keys=False)
    (out/'platform.yaml').write_text(payload)
    (out.parent/'application.yaml').write_text(yaml.safe_dump(application(cfg),sort_keys=False))
    bootstrap=yaml.safe_load((ROOT/'values/argo-cd.yaml').read_text())
    bootstrap.setdefault('configs',{}).setdefault('cm',{})['application.resourceTrackingMethod']='annotation'
    (out.parent/'argo-bootstrap-values.yaml').write_text(yaml.safe_dump(bootstrap,sort_keys=False))
    (out.parent/'images.txt').write_text('\n'.join(images)+'\n')
    report={'resources':len(resources),'platformSHA256':hashlib.sha256(payload.encode()).hexdigest(),
            'site':cfg,'validation':'Rendered only; not proof of a successful cluster installation.'}
    (out.parent/'render-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Rendered {len(resources)} resources to {out}; Application: {out.parent / "application.yaml"}',file=sys.stderr)
    return resources

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=pathlib.Path,default=ROOT/'site.yaml')
    parser.add_argument('--output',type=pathlib.Path,default=ROOT/'rendered')
    parser.add_argument('--get',choices=['argoNamespace','storage.className','storage.installLocalPath'])
    args=parser.parse_args()
    try:
        cfg=load_config(args.config)
        if args.get:
            value=cfg
            for key in args.get.split('.'):value=value[key]
            print(str(value).lower() if isinstance(value,bool) else value)
        else:render(cfg,args.output)
    except (ValueError,KeyError,TypeError,OSError,yaml.YAMLError,subprocess.CalledProcessError) as error:
        print('ERROR: '+str(error),file=sys.stderr)
        if isinstance(error,subprocess.CalledProcessError):print(error.stderr,file=sys.stderr)
        return 1
    return 0
if __name__=='__main__':sys.exit(main())
