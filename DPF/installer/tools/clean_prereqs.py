"""Preview/reset the standalone DPF lab; persistent storage is separately opt-in."""
import argparse
from datetime import datetime, timezone
import json
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from prereq_status import read_json
from ui import banner, table, outcome

TARGETS = [
    ('dpf-operator', 'dpf-operator-system', 'dpf-operator'),
    ('kamaji', 'dpf-operator-system', 'kamaji'),
    ('maintenance-operator', 'dpf-operator-system', 'maintenance-operator-chart'),
    ('node-feature-discovery', 'dpf-operator-system', 'node-feature-discovery'),
    ('argo-cd', 'dpf-operator-system', 'argo-cd'),
    ('cert-manager', 'cert-manager', 'cert-manager'),
]
LIST_FLAGS = ['--deployed','--failed','--pending','--uninstalled','--uninstalling','--superseded']
NAMESPACES = {'dpf-operator-system','cert-manager','dpu-cplane-tenant1'}
GROUPS = {'kamaji.clastix.io','maintenance.nvidia.com','nfd.k8s-sigs.io',
          'argoproj.io','cert-manager.io','acme.cert-manager.io'}
# These indicate workload provisioning/maintenance, not merely installed operators.
HARDWARE = {'dpus.provisioning.dpu.nvidia.com','dpusets.provisioning.dpu.nvidia.com',
            'dpudeployments.svc.dpu.nvidia.com','dpunodemaintenances.provisioning.dpu.nvidia.com',
            'nodemaintenances.maintenance.nvidia.com'}


def read_text(command):
    result=subprocess.run(command,capture_output=True,text=True,timeout=45)
    if result.returncode:raise RuntimeError(f'{command[0]} read failed: {result.stderr.strip()}')
    return result.stdout


def targets(releases):
    selected=[]
    for name,namespace,chart in TARGETS:
        for release in releases:
            if (release['name'],release['namespace']) != (name,namespace):continue
            if release['status']=='uninstalled':continue
            if not release['chart'].startswith(chart+'-'):
                raise RuntimeError(f'Refusing {namespace}/{name}: unexpected chart {release["chart"]}')
            if release['status'].startswith('pending-') or release['status']=='uninstalling':
                raise RuntimeError(f'{namespace}/{name} has an unfinished operation; resolve it before cleanup.')
            selected.append(release)
    return selected


def scoped_group(group):
    return group in GROUPS or group.endswith('.dpu.nvidia.com')


def identity(obj, resource):
    meta=obj['metadata']
    return {'resource':resource,'name':meta['name'],'namespace':meta.get('namespace',''),
            'uid':meta.get('uid','')}


def config_targets(items,resource):
    # kube-root-ca.crt is Kubernetes-managed and is recreated automatically.
    return [identity(o,resource) for o in items if o['metadata'].get('namespace') in NAMESPACES
            and not (resource=='configmaps' and o['metadata']['name']=='kube-root-ca.crt')]


LEFTOVER_KINDS='roles,rolebindings,clusterroles,clusterrolebindings,mutatingwebhookconfigurations,validatingwebhookconfigurations,apiservices'


def orphans(context):
    """Helm-labelled RBAC/webhook objects (any namespace, e.g. kube-system) of a lab
    release that is no longer installed. They block a fresh `helm install`
    ('exists and cannot be imported into the current release')."""
    k=['kubectl',f'--context={context}','--request-timeout=30s']
    installed={r['name'] for r in read_json(['helm','--kube-context',context,'list','-A',*LIST_FLAGS,'--max','10000','-o','json'])
               if r['status']!='uninstalled'}
    names=sorted({t[0] for t in TARGETS}-installed)
    if not names:return []
    selector='app.kubernetes.io/managed-by=Helm,app.kubernetes.io/instance in ('+','.join(names)+')'
    items=read_json([*k,'get',LEFTOVER_KINDS,'-A','-l',selector,'-o','json'])['items']
    return [identity(o,o['kind'].lower()) for o in items]


def inventory(context,delete_storage=False,force_finalizers=False):
    k=['kubectl',f'--context={context}','--request-timeout=30s']
    all_releases=read_json(['helm','--kube-context',context,'list','-A',*LIST_FLAGS,'--max','10000','-o','json'])
    releases=targets(all_releases)
    known={(r[0],r[1]) for r in TARGETS}
    foreign=[r for r in all_releases if r['namespace'] in NAMESPACES and (r['name'],r['namespace']) not in known and r['status']!='uninstalled']
    if foreign:raise RuntimeError('Unrelated Helm release in a lab namespace: '+foreign[0]['name']+'. Move/review it before resetting that namespace.')
    definitions=[o for o in read_json([*k,'get','crds','-o','json'])['items'] if scoped_group(o['spec']['group'])]
    custom=[];stuck=[]
    for crd in definitions:
        resource=crd['metadata']['name']
        instances=read_json([*k,'get',resource,'-A','-o','json'])['items']
        for obj in instances:
            namespace=obj['metadata'].get('namespace','')
            if namespace and namespace not in NAMESPACES:
                raise RuntimeError(f'{resource} is used outside this lab ({namespace}). Shared CRDs cannot be removed.')
            # A stuck object: already marked for deletion, held only by a finalizer whose
            # controller can no longer finish (e.g. its DPU cluster is gone). Opt-in only.
            if obj['metadata'].get('deletionTimestamp') and obj['metadata'].get('finalizers'):
                if force_finalizers:
                    record=identity(obj,resource);record['finalizers']=obj['metadata']['finalizers']
                    stuck.append(record);continue
                raise RuntimeError(f'{resource}/{obj["metadata"]["name"]} is stuck in deletion (finalizers: '
                                   +', '.join(obj['metadata']['finalizers'])+'). If what it waits for is already gone, rerun with --force-finalizers.')
            if resource in HARDWARE:
                raise RuntimeError(f'Deprovision {resource}/{obj["metadata"]["name"]} first, while its controller is running.')
            # Shared cluster-scoped prerequisites need ownership evidence.
            if not namespace and not crd['spec']['group'].endswith('.dpu.nvidia.com'):
                annotations=obj['metadata'].get('annotations',{})
                labels=obj['metadata'].get('labels',{})
                owned=(annotations.get('meta.helm.sh/release-name'),annotations.get('meta.helm.sh/release-namespace')) in known
                # The upstream NFD hook creates node feature rules without Helm ownership.
                owned=owned or (resource=='nodefeaturerules.nfd.k8s-sigs.io' and labels.get('app.kubernetes.io/part-of')=='dpf-operator-controller-manager')
                if not owned:raise RuntimeError(f'Cluster-scoped {resource}/{obj["metadata"]["name"]} has no verified lab ownership.')
            custom.append(identity(obj,resource))
    configs=[]
    for resource in ['secrets','configmaps']:
        # Object values stay in memory only; plans contain names/UIDs, never data.
        configs+=config_targets(read_json([*k,'get',resource,'-A','-o','json'])['items'],resource)
    pvcs=[o for o in read_json([*k,'get','pvc','-A','-o','json'])['items'] if o['metadata'].get('namespace') in NAMESPACES]
    volumes=read_json([*k,'get','pv','-o','json'])['items']
    claims=[identity(o,'persistentvolumeclaims') for o in pvcs]
    pvs=[]
    for obj in volumes:
        ref=obj.get('spec',{}).get('claimRef',{})
        # Covers a previous interrupted reset only when the binding still identifies
        # this dedicated lab namespace. Unbound/shared PVs are never inferred.
        if ref.get('namespace') in NAMESPACES:
            linked=next((c for c in pvcs if c['metadata']['name']==ref.get('name') and c['metadata']['namespace']==ref['namespace']),None)
            if linked and ref.get('uid') != linked['metadata'].get('uid'):
                raise RuntimeError('PV claim UID differs from the current claim; review storage ownership.')
            record=identity(obj,'persistentvolumes')
            record['reclaimPolicy']=obj['spec'].get('persistentVolumeReclaimPolicy','Unknown')
            pvs.append(record)
    plan={'context':context,'releases':releases,'crds':[identity(o,'customresourcedefinitions') for o in definitions],
          'custom':custom,'stuck':stuck,'configs':configs,'orphans':orphans(context),'pvcs':claims,'pvs':pvs,'delete_storage':delete_storage}
    check_volume_retention(context,plan)
    return plan


def check_volume_retention(context,plan):
    import yaml
    deletable={o['name'] for o in plan['crds']}
    claims={(o['namespace'],o['name']) for o in plan['pvcs']}
    volumes={o['name'] for o in plan['pvs']}
    for release in plan['releases']:
        manifest=read_text(['helm','--kube-context',context,'get','manifest',release['name'],'-n',release['namespace']])
        for obj in yaml.safe_load_all(manifest):
            if not isinstance(obj,dict):continue
            meta=obj.get('metadata',{});kind=obj.get('kind')
            kept=meta.get('annotations',{}).get('helm.sh/resource-policy')=='keep'
            if kind=='CustomResourceDefinition' and meta['name'] not in deletable and not kept:
                raise RuntimeError('Release contains a CRD outside the reset scope: '+meta['name'])
            if kind in ('PersistentVolumeClaim','PersistentVolume','StorageClass') and not kept:
                scoped=(kind=='PersistentVolumeClaim' and (meta.get('namespace',release['namespace']),meta['name']) in claims) or (kind=='PersistentVolume' and meta['name'] in volumes)
                if not plan['delete_storage'] or not scoped:
                    raise RuntimeError(f'{release["name"]} would remove {kind}/{meta["name"]} outside the selected storage scope.')
    if not plan['delete_storage']:
        for ns in sorted(NAMESPACES):
            for obj in read_json(['kubectl',f'--context={context}','--request-timeout=30s','-n',ns,'get','statefulsets','-o','json'])['items']:
                if obj.get('spec',{}).get('persistentVolumeClaimRetentionPolicy',{}).get('whenDeleted','Retain') != 'Retain':
                    raise RuntimeError(f'{ns}/{obj["metadata"]["name"]} deletes PVCs on removal. Choose storage deletion or change its retention policy first.')


def show(plan,more=False):
    banner('Clean / full lab reset',plan['context'])
    if plan['releases']:
        table([[r['name'],r['status'].capitalize(),'Remove'] for r in plan['releases']],['COMPONENT','STATUS','ACTION'])
        print()
    rows=[['Stuck in deletion',len(plan['stuck']),'Remove finalizers'],['Custom resources',len(plan['custom']),'Delete'],['DPF / prerequisite CRDs',len(plan['crds']),'Delete'],
          ['Orphaned Helm RBAC/webhooks',len(plan['orphans']),'Delete'],
          ['Secrets',sum(o['resource']=='secrets' for o in plan['configs']),'Delete'],
          ['ConfigMaps',sum(o['resource']=='configmaps' for o in plan['configs']),'Delete'],
          ['Persistent claims',len(plan['pvcs']),'Delete' if plan['delete_storage'] else 'Keep'],
          ['Lab-bound volumes',len(plan['pvs']),'Delete' if plan['delete_storage'] else 'Keep']]
    table(rows,['RESOURCE','COUNT','ACTION'])
    print('\nScope: dpf-operator-system, cert-manager, dpu-cplane-tenant1, plus leftover RBAC/webhooks of removed lab releases in any namespace (e.g. kube-system).')
    print('Keep: Kubernetes/CNI, namespaces, kube-root-ca, storage provisioner and StorageClasses.')
    if plan['delete_storage']:
        outcome('warn','Storage deletion selected. Backend data removal follows the PV reclaim policy.')
    if more:
        print('\nExact resource scope:')
        objects=plan['stuck']+plan['custom']+plan['crds']+plan['orphans']+plan['configs']+plan['pvcs']+plan['pvs']
        table([[o['resource'],o['namespace'] or '-',o['name']] for o in objects],['KIND','NAMESPACE','NAME'])
        if plan['pvs']:table([[o['name'],o['reclaimPolicy']] for o in plan['pvs']],['PV','RECLAIM POLICY'])
        print('\nRuntime objects are deleted before their controllers. No hardware reset.')
        print('Finalizers are removed only with --force-finalizers, and only from objects already marked for deletion.')


def execute_command(command,log,seconds):
    with log.open('a') as out:
        process=subprocess.Popen(command,stdout=out,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+seconds+60
            while process.poll() is None:
                if time.monotonic()>deadline:raise RuntimeError(f'Cleanup command timed out. Details: {log}')
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:print('  Waiting for removal...',flush=True)
            if process.returncode:raise RuntimeError(f'Removal stopped. Details: {log}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


def delete_objects(k,objects,seconds,log):
    for obj in objects:
        args=[*k]
        if obj['namespace']:args+=['-n',obj['namespace']]
        # Identity check prevents deleting a replaced object under a stale name.
        text=read_text([*args,'get',obj['resource'],obj['name'],'--ignore-not-found','-o','json'])
        if not text.strip():continue
        live=json.loads(text)
        if live['metadata'].get('uid') != obj['uid']:
            raise RuntimeError('Resource changed since preview; rerun cleanup: '+obj['name'])
        execute_command([*args,'delete',obj['resource'],obj['name'],'--ignore-not-found','--wait=true','--timeout',f'{seconds}s'],log,seconds)


def release_stuck(k,objects,log):
    for obj in objects:
        args=[*k]
        if obj['namespace']:args+=['-n',obj['namespace']]
        text=read_text([*args,'get',obj['resource'],obj['name'],'--ignore-not-found','-o','json'])
        if not text.strip():continue
        live=json.loads(text)
        # Only the same object, and only while it is still marked for deletion.
        if live['metadata'].get('uid') != obj['uid'] or not live['metadata'].get('deletionTimestamp'):
            raise RuntimeError('Resource changed since preview; rerun cleanup: '+obj['name'])
        print(f'  Removing finalizers from {obj["resource"]}/{obj["name"]}...',flush=True)
        execute_command([*args,'patch',obj['resource'],obj['name'],'--type=merge','-p','{"metadata":{"finalizers":null}}'],log,60)


def uninstall(context,release,seconds,log):
    execute_command(['helm','--kube-context',context,'uninstall',release['name'],'-n',release['namespace'],
                     '--wait','--timeout',f'{seconds}s','--no-hooks'],log,seconds)


def run(context,execute,seconds,more=False,delete_storage=False,force_finalizers=False):
    if not context:context=read_text(['kubectl','config','current-context']).strip()
    if not context:raise RuntimeError('No Kubernetes context selected')
    plan=inventory(context,delete_storage,force_finalizers)
    show(plan,more)
    if not execute:
        outcome('ready','Preview only. No cluster changes. M: exact resource list.')
        return 0
    base=Path(__file__).resolve().parents[1]/'state'
    base.mkdir(exist_ok=True)
    run_dir=Path(tempfile.mkdtemp(prefix='clean-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),dir=base))
    (run_dir/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    k=['kubectl',f'--context={context}','--request-timeout=30s']
    # OperatorConfig goes after dependent DPF objects; certificate objects go last.
    def priority(obj):
        r=obj['resource']
        if r=='dpfoperatorconfigs.operator.dpu.nvidia.com':return 30
        if r.endswith('.cert-manager.io'):return 50
        if r=='datastores.kamaji.clastix.io':return 40
        if r=='tenantcontrolplanes.kamaji.clastix.io':return 20
        return 10
    if plan['stuck']:
        outcome('warn','Removing finalizers from objects stuck in deletion...')
        release_stuck(k,plan['stuck'],run_dir/'stuck.log')
        time.sleep(5)
    outcome('info','Removing lab custom resources...')
    delete_objects(k,sorted(plan['custom'],key=priority),seconds,run_dir/'custom-resources.log')
    for index,release in enumerate(plan['releases'],1):
        print(f'  [{index}/{len(plan["releases"])}] Removing {release["name"]}...',flush=True)
        uninstall(context,release,seconds,run_dir/(release['name']+'.log'))
    # Leftovers of releases removed earlier (e.g. cert-manager leader-election RoleBinding in kube-system).
    delete_objects(k,orphans(context),seconds,run_dir/'orphans.log')
    # Helm may already have removed a CRD without a keep annotation.
    delete_objects(k,plan['crds'],seconds,run_dir/'crds.log')
    # Relist generated Secrets/ConfigMaps after controllers stop. Never save values.
    configs=[]
    for resource in ['secrets','configmaps']:
        configs+=config_targets(read_json([*k,'get',resource,'-A','-o','json'])['items'],resource)
    delete_objects(k,configs,seconds,run_dir/'configuration.log')
    if delete_storage:
        delete_objects(k,plan['pvcs'],seconds,run_dir/'storage.log')
        delete_objects(k,plan['pvs'],seconds,run_dir/'storage.log')
    remaining=inventory(context,delete_storage,force_finalizers)
    if remaining['releases'] or remaining['crds'] or remaining['configs'] or remaining['custom'] or remaining['stuck'] or remaining['orphans'] or (delete_storage and (remaining['pvcs'] or remaining['pvs'])):
        raise RuntimeError('Some lab objects remain. Inspect --clean --more before retrying.')
    outcome('complete','DPF lab configuration removed. Storage '+('deletion requested.' if delete_storage else 'kept.'))
    print('Next: 3 Install prerequisites, then 9 Install DPF.')
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',default='')
    parser.add_argument('--yes',action='store_true')
    parser.add_argument('--delete-storage',action='store_true')
    parser.add_argument('--more',action='store_true')
    parser.add_argument('--force-finalizers',action='store_true')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    try:return run(args.context,args.yes,args.timeout,args.more,args.delete_storage,args.force_finalizers)
    except KeyboardInterrupt:
        outcome('blocked','Cleanup interrupted; rerun the preview to inspect remaining resources.')
        return 130
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError,ImportError) as error:
        outcome('blocked',str(error))
        return 2


if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_: sys.exit(143))
    sys.exit(main())
