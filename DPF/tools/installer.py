#!/usr/bin/env python3
"""Config inspection and scoped teardown for the Bash DPF installer."""
import argparse
from contextlib import contextmanager
from functools import lru_cache
import os
import tempfile
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_NAMES = ['dpf-provisioning', 'dpf-hbn', 'dpf-site', 'dpf-operator-config', 'dpf-tenants', 'dpf', 'dpf-platform']
NAMESPACES = {'dpf-operator-system', 'tenant-europe', 'tenant-asia', 'cert-manager', 'local-path-provisioner'}
ARGO_CRDS = ['applications.argoproj.io', 'applicationsets.argoproj.io', 'appprojects.argoproj.io']
DELETE_STEPS = ['hardware', 'services', 'tenants', 'volumes', 'applications', 'crds', 'external-argo']
CLUSTER_KINDS = {'ClusterRole', 'ClusterRoleBinding', 'MutatingWebhookConfiguration',
                 'ValidatingWebhookConfiguration', 'StorageClass'}
SOURCE_PATHS = ['DPF/generated/platform', 'DPF/charts/site', 'DPF/profiles/two-tenant-hbn/overlapping-subnets',
                'DPF/profiles/two-tenant-hbn/desired/40-provisioning']


def in_scope_namespace(namespace):
    return namespace in NAMESPACES


def command(args, capture=True, input=None):
    # No password/Secret commands are routed through this logger.
    print('+ ' + ' '.join(args), flush=True)
    result = subprocess.run(args, text=True, capture_output=capture, input=input)
    if result.returncode:
        if capture and result.stderr: print(result.stderr, file=sys.stderr)
        raise RuntimeError('Command failed; cleanup stopped')
    return result.stdout if capture else ''


def kube(*args):
    return command(['kubectl', '--request-timeout=30s', *args])


def objects(resource, namespace=None):
    scope = ['-n', namespace] if namespace else ['-A']
    return json.loads(kube('get', resource, *scope, '-o', 'json'))['items']


@lru_cache(maxsize=1)
def platform_objects():
    return [o for p in sorted((ROOT/'generated/platform').glob('*.yaml'))
            for o in yaml.safe_load_all(p.read_text()) if o]


def platform_crds():
    return sorted(o['metadata']['name'] for o in platform_objects() if o['kind'] == 'CustomResourceDefinition')


def validate_config(app):
    if app.get('kind') != 'Application' or app.get('metadata', {}).get('name') != 'dpf' or app['metadata'].get('namespace') != 'argocd':
        raise ValueError('Use the prepared single dpf Application, not the staged config.yaml; see TWO-COMMAND-INSTALL.md')
    spec = app['spec']
    if spec.get('destination') != {'name': 'in-cluster', 'namespace': 'dpf-operator-system'}:
        raise ValueError('This installer targets in-cluster/dpf-operator-system only')
    sources = spec.get('sources', [])
    if [s.get('path') for s in sources] != SOURCE_PATHS:
        raise ValueError('Expected the reviewed platform/site/overlap-HBN/hardware sources')
    if any(s.get('repoURL') != 'https://github.com/kirson-git/dsx-os.git' for s in sources):
        raise ValueError('Unexpected source repository; review a fork before changing this guard')
    revisions = {s.get('targetRevision') for s in sources}
    if len(revisions) != 1 or not re.fullmatch('[0-9a-f]{40}', next(iter(revisions)) or ''):
        raise ValueError('All four sources must pin the same full Git SHA')
    if 'FailOnSharedResource=true' not in spec.get('syncPolicy', {}).get('syncOptions', []):
        raise ValueError('Missing shared-resource ownership guard')
    return sources[1]['helm']['valuesObject']


def show_config(path):
    app = yaml.safe_load(Path(path).read_text())
    values = validate_config(app)
    print('Config:', Path(path).resolve())
    print('Application: argocd/dpf; revision:', app['spec']['sources'][0]['targetRevision'])
    for key in ['apiServerIP', 'vipInterface', 'europeVIP', 'asiaVIP', 'install-dhcp']:
        print(f'{key}: {values.get(key)}')
    print('Host Ubuntu and DHCP/router/switch settings are retained outside Argo.')
    for host in values.get('bootstrap', {}).get('hosts', []):
        print(f"{host['name']}: DPUNode={host['dpuNode']}, iDRAC={host['idracIP']}, service-tag={host['serial']}, helper-node={host['managementNode']}")
    for patch in app['spec']['sources'][3].get('kustomize', {}).get('patches', []):
        if patch['target']['kind'] == 'DPUDevice':
            spec = next((p['value'] for p in yaml.safe_load(patch['patch']) if p['path'] == '/spec'), {})
            print('DPU BMC:', spec.get('bmcIp'), 'serial:', spec.get('serialNumber'))
    return app


def argo_releases():
    # Explicit status flags work with both Helm 3 and Helm 4.
    releases = json.loads(command(['helm', 'list', '-n', 'argocd', '--deployed', '--failed',
                                  '--pending', '--uninstalled', '--uninstalling', '--superseded',
                                  '--max', '10000', '-o', 'json']))
    if any(r['name'] != 'external-argo-cd' for r in releases):
        raise RuntimeError('Unexpected Helm release in argocd; refusing removal')
    return releases


def platform_cluster_resources():
    desired = {(o['kind'], o['metadata']['name']) for o in platform_objects()
               if o['kind'] in CLUSTER_KINDS}
    # These built-in kinds exist even after all DPF CRDs are gone.
    return [o for o in objects(','.join(sorted(CLUSTER_KINDS)))
            if (o['kind'], o['metadata']['name']) in desired]


def verify_cluster_ownership(apps, allow_orphaned=False):
    app_names = {a['metadata']['name'] for a in apps if a['metadata'].get('namespace') == 'argocd'}
    for obj in platform_cluster_resources():
        annotations = obj['metadata'].get('annotations', {})
        owner = annotations.get('argocd.argoproj.io/tracking-id', '').split(':', 1)[0]
        if annotations.get('argocd.argoproj.io/installation-id') != 'dsx-platform' or (owner not in app_names and not (allow_orphaned and owner in APP_NAMES)):
            raise RuntimeError('Platform resource is shared or orphaned: ' + obj['kind'] + '/' + obj['metadata']['name'] +
                               '; restore its owning Application before cleanup')


def inventory(force=False, keep_argo=False, allow_orphaned=False):
    argo_releases()
    crds = {o['metadata']['name'] for o in objects('crds')}
    apps = objects('applications.argoproj.io') if ARGO_CRDS[0] in crds else []
    for app in apps:
        meta = app['metadata']
        if meta.get('namespace') == 'argocd' and meta['name'] not in APP_NAMES:
            raise RuntimeError('External Argo owns an unrelated Application: ' + meta['name'])
        if meta.get('namespace') not in {'argocd', 'dpf-operator-system'}:
            raise RuntimeError('Another Argo namespace exists; refusing CRD deletion')
        if sync_active(app) and not force:
            raise RuntimeError('An Argo sync is pending/running; wait or use --force to terminate it before teardown')
    if ARGO_CRDS[1] in crds and objects('applicationsets.argoproj.io'):
        raise RuntimeError('ApplicationSets exist; review their ownership before teardown')
    allowed_projects = {('argocd', 'default'), ('dpf-operator-system', 'default'),
                        ('dpf-operator-system', 'doca-platform-project-dpu'),
                        ('dpf-operator-system', 'doca-platform-project-host')}
    if ARGO_CRDS[2] in crds:
        for project in objects('appprojects.argoproj.io'):
            meta = project['metadata']
            if (meta.get('namespace'), meta['name']) not in allowed_projects:
                raise RuntimeError('Unrelated AppProject exists; refusing Argo CRD deletion')
    for storage in objects('storageclasses'):
        if storage['metadata']['name'] == 'local-path' and storage['provisioner'] != 'rancher.io/local-path':
            raise RuntimeError('local-path belongs to another storage provisioner')
    for volume in objects('pv'):
        if volume['spec'].get('storageClassName') == 'local-path':
            claim = volume['spec'].get('claimRef', {})
            if claim.get('namespace') != 'dpf-operator-system':
                raise RuntimeError('Local Path PV exists outside DPF, or without a DPF claim')
    for crd in ['certificates.cert-manager.io', 'issuers.cert-manager.io']:
        if crd in crds and any(not in_scope_namespace(o['metadata'].get('namespace')) for o in objects(crd)):
            raise RuntimeError('cert-manager is used outside the DPF namespaces')
    if 'clusterissuers.cert-manager.io' in crds and objects('clusterissuers.cert-manager.io'):
        raise RuntimeError('ClusterIssuers exist; verify shared cert-manager use before teardown')
    pvcs = objects('pvc')
    if any(o['spec'].get('storageClassName') == 'local-path' and o['metadata']['namespace'] != 'dpf-operator-system' for o in pvcs):
        raise RuntimeError('Local Path storage is used outside DPF')
    # Every bundled CRD is dedicated to this profile. Refuse foreign consumers,
    # including NFD/maintenance and in-flight cert-manager resources.
    defaults = {(o['kind'], o['metadata']['name']) for o in platform_objects()}
    for crd in sorted(crds.intersection(platform_crds())):
        for obj in objects(crd):
            ns = obj['metadata'].get('namespace')
            if ns and not in_scope_namespace(ns):
                raise RuntimeError('Prerequisite resources exist outside the DPF namespaces: ' + crd)
            if not ns and (obj['kind'], obj['metadata']['name']) not in defaults:
                raise RuntimeError('Prerequisite has an unrecognized cluster-scoped instance: ' + crd)
    verify_cluster_ownership(apps, allow_orphaned=allow_orphaned)
    print('Will remove:', len(crds.intersection(platform_crds())), 'DPF/prerequisite CRDs.')
    print('External Argo and its CRDs: ' + ('KEEP' if keep_argo else 'DELETE LAST'))
    if force:
        print('Active syncs are allowed by this cleanup mode; ownership guards remain enforced.')
    print('Will preserve Kubernetes VMs, kube-system, Calico/network-policy CRDs, Ubuntu hosts, DHCP and router/switch configuration.')
    return crds, apps, pvcs


def sync_active(app):
    return bool(app.get('operation')) or app.get('status', {}).get('operationState', {}).get('phase') in {'Running', 'Terminating'}


def stop_syncs(timeout=300):
    """Cancel DPF syncs after disabling auto-sync; never fake completion.

    Argo CD v3.3.0 TerminateOperation sets operationState.phase=Terminating.
    Resource-version tests reject races with a new controller update.
    """
    deadline = time.monotonic() + timeout
    while True:
        active = []
        for app in objects('applications.argoproj.io'):
            meta = app['metadata']
            owned = (meta.get('namespace') == 'argocd' and meta['name'] in APP_NAMES) or meta.get('namespace') == 'dpf-operator-system'
            if not owned:
                raise RuntimeError('Unexpected Argo Application appeared during cleanup; stopped')
            if sync_active(app):
                active.append(app)
        if not active:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Argo sync termination timed out; no DPF resources deleted. Inspect the Argo controller.')
        for app in active:
            meta = app['metadata']
            phase = app.get('status', {}).get('operationState', {}).get('phase')
            if phase == 'Terminating':
                continue
            operations = [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']}]
            if phase == 'Running':
                operations.append({'op': 'replace', 'path': '/status/operationState/phase', 'value': 'Terminating'})
            elif app.get('operation'):
                operations.append({'op': 'remove', 'path': '/operation'})
            kube('-n', meta['namespace'], 'patch', 'application', meta['name'], '--type=json', '-p', json.dumps(operations))
        time.sleep(2)


def wait_empty(resource, namespace=None, timeout=1200):
    deadline = time.monotonic() + timeout
    while objects(resource, namespace):
        if time.monotonic() > deadline:
            raise RuntimeError('Timed out waiting for ' + resource + '; inspect finalizers/controllers. Nothing forced.')
        time.sleep(5)


def remove_objects(resource, crds, namespace=None):
    if resource not in crds:
        return
    for obj in objects(resource, namespace):
        meta = obj['metadata']
        if meta.get('namespace') and not in_scope_namespace(meta['namespace']):
            raise RuntimeError('Refusing a resource outside the DPF namespace boundary')
        scope = ['-n', meta['namespace']] if meta.get('namespace') else []
        kube('delete', resource, meta['name'], *scope, '--ignore-not-found', '--wait=false')
    wait_empty(resource, namespace)


def delete_all(confirm_context, force=False, keep_argo=False):
    context = kube('config', 'current-context').strip()
    if confirm_context != context:
        raise RuntimeError('Deletion requires the exact current kubectl context as confirmation')
    crds, apps, pvcs = inventory(force=force, keep_argo=keep_argo)  # Read-only guards before first write.
    for app in apps:
        if app['metadata']['namespace'] == 'argocd' or force:
            kube('-n', app['metadata']['namespace'], 'patch', 'application', app['metadata']['name'], '--type=merge', '-p',
                 json.dumps({'spec': {'syncPolicy': {'automated': {'enabled': False}}}}))
    if force and ARGO_CRDS[0] in crds:
        stop_syncs()
        crds, apps, pvcs = inventory(keep_argo=keep_argo)
    for step in DELETE_STEPS:
        print('Cleanup stage:', step, flush=True)
        if step == 'hardware':
            for kind in ['dpudiscoveries.provisioning.dpu.nvidia.com', 'dpudeployments.svc.dpu.nvidia.com',
                         'dpusets.provisioning.dpu.nvidia.com', 'dpus.provisioning.dpu.nvidia.com',
                         'dpunodes.provisioning.dpu.nvidia.com', 'dpudevices.provisioning.dpu.nvidia.com']:
                remove_objects(kind, crds)
        elif step == 'services':
            for kind in ['dpuservicechains.svc.dpu.nvidia.com', 'dpuservices.svc.dpu.nvidia.com']:
                remove_objects(kind, crds)
        elif step == 'tenants':
            remove_objects('dpuclusters.provisioning.dpu.nvidia.com', crds)
            if 'tenantcontrolplanes.kamaji.clastix.io' in crds:
                wait_empty('tenantcontrolplanes.kamaji.clastix.io')
        elif step == 'volumes':
            kube('-n', 'dpf-operator-system', 'delete', 'statefulset', 'kamaji-etcd', '--ignore-not-found', '--wait=true', '--timeout=300s')
            selected = [p for p in pvcs if p['metadata']['namespace'] == 'dpf-operator-system']
            volumes = [p['spec']['volumeName'] for p in selected if p['spec'].get('volumeName')]
            for pvc in selected:
                kube('-n', 'dpf-operator-system', 'delete', 'pvc', pvc['metadata']['name'], '--ignore-not-found', '--wait=true', '--timeout=300s')
            for volume in volumes:
                # A retained PV stops cleanup instead of deleting arbitrary host paths.
                kube('wait', 'pv/' + volume, '--for=delete', '--timeout=300s')
        elif step == 'applications':
            existing = {a['metadata']['name']: a for a in apps if a['metadata']['namespace'] == 'argocd'}
            for name in APP_NAMES:
                if name not in existing: continue
                finalizers = list(existing[name]['metadata'].get('finalizers', []))
                if not any(f.startswith('resources-finalizer.argocd.argoproj.io') for f in finalizers):
                    finalizers.append('resources-finalizer.argocd.argoproj.io')
                kube('-n', 'argocd', 'patch', 'application', name, '--type=merge', '-p',
                     json.dumps({'metadata': {'finalizers': finalizers}}))
                kube('-n', 'argocd', 'delete', 'application', name, '--wait=false')
                kube('-n', 'argocd', 'wait', 'application/' + name, '--for=delete', '--timeout=1200s')
        elif step == 'crds':
            selected = sorted(crds.intersection(platform_crds()))
            if selected:
                kube('delete', 'crd', *selected, '--ignore-not-found', '--wait=true', '--timeout=300s')
            kube('delete', 'namespace', *sorted(NAMESPACES), '--ignore-not-found', '--wait=true', '--timeout=600s')
        elif step == 'external-argo':
            if keep_argo:
                print('Keeping external Argo, argocd namespace and Argo CRDs.')
                continue
            # Refuse if a new unrelated Application appeared while cleanup was running.
            if ARGO_CRDS[0] in crds and objects('applications.argoproj.io'):
                raise RuntimeError('Argo Applications remain; inspect before removing external Argo')
            releases = argo_releases()
            if releases:
                command(['helm', 'uninstall', 'external-argo-cd', '-n', 'argocd', '--wait', '--timeout', '5m'], capture=False)
            kube('delete', 'namespace', 'argocd', '--ignore-not-found', '--wait=true', '--timeout=300s')
            kube('delete', 'crd', *ARGO_CRDS, '--ignore-not-found', '--wait=true', '--timeout=300s')
    remaining = {o['metadata']['name'] for o in objects('crds')}
    targeted_crds = set(platform_crds()) | (set() if keep_argo else set(ARGO_CRDS))
    if remaining.intersection(targeted_crds):
        raise RuntimeError('Some targeted CRDs remain')
    leftovers = platform_cluster_resources()
    if leftovers:
        raise RuntimeError('Platform cluster-scoped resources remain: ' + ', '.join(o['kind'] + '/' + o['metadata']['name'] for o in leftovers))
    print('Scoped DPF/prerequisite cleanup complete. Management Kubernetes retained.')
    print('External Argo: ' + ('retained' if keep_argo else 'removed'))


def force_remove(resource, obj):
    """Strip finalizers and request immediate deletion, within the package boundary."""
    meta = obj['metadata']
    namespace = meta.get('namespace')
    kind, name = obj['kind'], meta['name']
    if namespace:
        allowed = namespace in NAMESPACES or (namespace == 'argocd' and kind == 'Application' and name in APP_NAMES)
    elif kind == 'Namespace':
        allowed = name in NAMESPACES
    elif kind == 'PersistentVolume':
        allowed = obj.get('spec', {}).get('claimRef', {}).get('namespace') in NAMESPACES
    elif kind == 'CustomResourceDefinition':
        allowed = name in platform_crds()
    else:
        allowed = (kind, name) in {(o['kind'], o['metadata']['name']) for o in platform_objects()}
    if not allowed:
        raise RuntimeError('Refusing force deletion outside scope: ' + kind + '/' + name)
    scope = ['-n', namespace] if namespace else []
    operations = [{'op': 'test', 'path': '/metadata/uid', 'value': meta['uid']},
                  {'op': 'add', 'path': '/metadata/finalizers', 'value': []}]
    try:
        kube('patch', resource, name, *scope, '--type=json', '-p', json.dumps(operations))
    except RuntimeError:
        if kube('get', resource, name, *scope, '--ignore-not-found', '-o', 'name').strip():
            raise
        return  # Already removed by garbage collection.
    # Raw DELETE sends UID preconditions, unlike kubectl delete-by-name. This
    # avoids deleting a replacement created after a terminating object vanished.
    options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'gracePeriodSeconds': 0,
               'propagationPolicy': 'Background', 'preconditions': {'uid': meta['uid']}}
    try:
        command(['kubectl', '--request-timeout=30s', 'delete', '--raw', resource_endpoint(obj), '-f', '-'],
                input=json.dumps(options))
    except RuntimeError:
        if kube('get', resource, name, *scope, '--ignore-not-found', '-o', 'name').strip():
            raise


@lru_cache(maxsize=None)
def api_resource_names(api_version):
    prefix = '/apis/' + api_version if '/' in api_version else '/api/' + api_version
    response = json.loads(kube('get', '--raw', prefix))
    return prefix, {r['kind']: r['name'] for r in response['resources'] if '/' not in r['name']}


def resource_endpoint(obj):
    prefix, names = api_resource_names(obj['apiVersion'])
    meta = obj['metadata']
    namespace = '/namespaces/' + meta['namespace'] if meta.get('namespace') else ''
    return prefix + namespace + '/' + names[obj['kind']] + '/' + meta['name']


def resource_type(obj):
    group = obj['apiVersion'].split('/')[0] if '/' in obj['apiVersion'] else ''
    return obj['kind'] + ('.' + group if group else '')


def immediate_delete(confirm_context):
    if kube('config', 'current-context').strip() != confirm_context:
        raise RuntimeError('Cluster context does not match confirmation')
    crds, apps, _ = inventory(force=True, keep_argo=True, allow_orphaned=True)
    # Snapshot the scope before removing its Applications/controllers. Do not
    # print resource bodies: they can include Secrets or private addresses.
    clusters = platform_cluster_resources()
    namespaces = [o for o in objects('namespaces') if o['metadata']['name'] in NAMESPACES]
    volumes = [o for o in objects('pv') if o.get('spec', {}).get('claimRef', {}).get('namespace') in NAMESPACES]
    selected_crds = [o for o in objects('crds') if o['metadata']['name'] in set(platform_crds())]
    custom = [o for crd in sorted(crds.intersection(platform_crds())) for o in objects(crd)]
    types = kube('api-resources', '--namespaced=true', '--verbs=list,delete', '-o', 'name').split()
    # Custom resources above are already captured. Core/extension resources
    # include PVCs, Secrets, RBAC, Jobs and controllers, not just kubectl get all.
    types = [r for r in types if r not in set(platform_crds()) and r != "applications.argoproj.io"]
    resources = []
    for namespace in namespaces:
        if types:
            resources.extend(objects(','.join(types), namespace['metadata']['name']))
    print('IMMEDIATE FORCE: stripping scoped finalizers; no controller/completion waits. External Argo stays.')
    print('This can orphan DPU workloads and backing storage; physical disks are not wiped.')
    # Detach Argo ownership first. Unlike normal cascade deletion this does not
    # require Argo or DPF controllers to complete reconciliation.
    for app in apps:
        meta = app['metadata']
        kube('-n', meta['namespace'], 'patch', 'application', meta['name'], '--type=merge', '-p',
             json.dumps({'metadata': {'annotations': {'argocd.argoproj.io/skip-reconcile': 'true'}},
                         'spec': {'syncPolicy': {'automated': {'enabled': False}}}, 'operation': None}))
        force_remove('applications.argoproj.io', app)
    # Remove admission hooks before stopping the servers that serve them.
    for obj in clusters:
        if obj['kind'].endswith('WebhookConfiguration'):
            force_remove(resource_type(obj), obj)
    priority = {'CronJob': 0, 'Job': 1, 'Deployment': 2, 'StatefulSet': 2, 'DaemonSet': 2,
                'ReplicaSet': 3, 'ReplicationController': 3, 'Pod': 4}
    for obj in sorted(resources, key=lambda o: priority.get(o['kind'], 5)):
        force_remove(resource_type(obj), obj)
    for obj in custom:
        force_remove(resource_type(obj), obj)
    for obj in volumes:
        force_remove('pv', obj)
    for obj in clusters:
        if not obj['kind'].endswith('WebhookConfiguration'):
            force_remove(resource_type(obj), obj)
    for obj in selected_crds:
        force_remove('crds', obj)
    for namespace in namespaces:
        name = namespace['metadata']['name']
        force_remove('namespace', namespace)
        current = kube('get', 'namespace', name, '--ignore-not-found', '-o', 'json').strip()
        if current:
            remaining = json.loads(current)
            if remaining['metadata']['uid'] != namespace['metadata']['uid']:
                raise RuntimeError('Namespace was recreated; refusing to finalize new namespace ' + name)
            body = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
                k: remaining['metadata'][k] for k in ['name', 'uid', 'resourceVersion']}, 'spec': {'finalizers': []}}
            command(['kubectl', '--request-timeout=30s', 'replace', '--raw',
                     '/api/v1/namespaces/' + name + '/finalize', '-f', '-'], input=json.dumps(body))
    print('Force-delete requests submitted. No completion waits were performed.')
    print('Verify remaining namespaces/CRDs before reinstalling; API requests can still take time.')


@contextmanager
def pinned_cluster(expected_context):
    """Freeze the selected cluster for kubectl and Helm; never log credentials."""
    result = subprocess.run(['kubectl', 'config', 'view', '--raw', '--minify', '--flatten',
                             '--context', expected_context, '-o', 'json'],
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Could not pin the confirmed cluster; nothing changed')
    snapshot = json.loads(result.stdout)
    if snapshot.get('current-context') != expected_context:
        raise RuntimeError('Cluster snapshot does not match confirmation')
    previous = os.environ.get('KUBECONFIG')
    with tempfile.TemporaryDirectory(prefix='dsx-cluster-') as directory:
        path = Path(directory) / 'kubeconfig'
        path.touch(mode=0o600)
        path.write_text(result.stdout)
        os.environ['KUBECONFIG'] = str(path)
        try:
            yield
        finally:
            if previous is None: os.environ.pop('KUBECONFIG', None)
            else: os.environ['KUBECONFIG'] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['config', 'delete-plan', 'delete', 'delete-force'])
    parser.add_argument('--config')
    parser.add_argument('--confirm-context')
    parser.add_argument('--force', action='store_true', help='Terminate DPF syncs before guarded cleanup; never strip finalizers')
    parser.add_argument('--keep-argo', action='store_true', help='Keep external Argo, its namespace and CRDs')
    args = parser.parse_args()
    try:
        if args.action == 'config':
            if not args.config: raise ValueError('--config is required')
            show_config(args.config)
        elif args.action == 'delete-plan': inventory(force=args.force, keep_argo=args.keep_argo)
        else:
            if not args.confirm_context: raise ValueError('--confirm-context is required')
            with pinned_cluster(args.confirm_context):
                if args.action == 'delete-force':
                    immediate_delete(args.confirm_context)
                else:
                    delete_all(args.confirm_context, force=args.force, keep_argo=args.keep_argo)
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        parser.exit(1, 'Stopped: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
