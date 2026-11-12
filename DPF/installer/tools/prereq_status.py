"""Read-only prerequisite inventory, with versions sourced from the bundled Helmfile."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.tools'))


def read_json(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f'{command[0]} read failed: {result.stderr.strip()}')
    return json.loads(result.stdout)


def workload_ready(item):
    spec, state = item.get('spec', {}), item.get('status', {})
    if state.get('observedGeneration', 0) < item.get('metadata', {}).get('generation', 1):
        return False
    if item['kind'] == 'DaemonSet':
        desired = state.get('desiredNumberScheduled', 0)
        fields = ('numberReady', 'numberAvailable', 'updatedNumberScheduled')
    else:
        desired = spec.get('replicas', 1)
        fields = ('readyReplicas', 'updatedReplicas')
        if item['kind'] == 'Deployment':
            fields += ('availableReplicas',)
        elif state.get('currentRevision') != state.get('updateRevision'):
            return False
    return desired > 0 and all(state.get(field, 0) >= desired for field in fields)


def belongs(item, name):
    meta = item.get('metadata', {})
    labels = meta.get('labels', {})
    aliases = {'argo-cd': ('argocd',), 'node-feature-discovery': ('nfd',)}
    candidates = (name, *aliases.get(name, ()))
    values = [meta.get('name', ''), labels.get('app.kubernetes.io/name', ''),
              labels.get('app.kubernetes.io/instance', ''), labels.get('app', '')]
    return any(value == prefix or value.startswith(prefix + '-')
               for value in values for prefix in candidates)


def chart_version(release, name):
    chart = release.get('chart', '')
    prefix = 'maintenance-operator-chart' if name == 'maintenance-operator' else name
    return chart[len(prefix) + 1:] if chart.startswith(prefix + '-') else 'Unknown'


def health(workloads):
    return ('Ready' if all(workload_ready(w) for w in workloads) else 'Not ready') if workloads else 'Unknown'


def component_row(name, expected, releases, workloads):
    prefix = 'maintenance-operator-chart' if name == 'maintenance-operator' else name
    matches = [r for r in releases if r.get('name') == name or r.get('chart', '').startswith(prefix + '-')]
    if len(matches) > 1:
        return [name, 'Multiple', 'Mixed', expected, 'Unknown', 'Review']
    if not matches:
        found = [w for w in workloads if belongs(w, name)]
        return [name, 'Unmanaged' if found else 'Missing', 'Unknown' if found else '-',
                expected, health(found) if found else '-', 'Review' if found else '-']
    release = matches[0]
    found = [w for w in workloads if w['metadata'].get('namespace') == release['namespace'] and
             (w['metadata'].get('labels', {}).get('app.kubernetes.io/instance') == release['name'] or
              w['metadata'].get('annotations', {}).get('meta.helm.sh/release-name') == release['name'] or
              belongs(w, name))]
    if name == 'argo-cd':
        # NVIDIA's bundled values explicitly disable only the ApplicationSet controller.
        found = [w for w in found if not (
            w.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/name') == 'argocd-applicationset-controller'
            and w.get('spec', {}).get('replicas') == 0)]
    version = chart_version(release, name)
    match = 'Match' if version.lstrip('v') == expected.lstrip('v') else 'Review'
    presence = 'Installed' if release.get('status') == 'deployed' else release.get('status', 'Unknown').capitalize()
    return [name, presence, version, expected, health(found), match]


def print_table(rows, headers=None):
    headers = headers or ['COMPONENT', 'STATUS', 'INSTALLED', 'NVIDIA PIN', 'READINESS', 'VERSION']
    from ui import table
    table(rows, headers)


def report(context, storage, diagnose=False, more=False):
    import yaml
    base = Path(__file__).resolve().parents[1]
    config = list(yaml.safe_load_all((base / 'prerequisites/helmfiles/prereqs.yaml').read_text()))[-1]
    if not context:
        context = subprocess.check_output(['kubectl', 'config', 'current-context'], text=True, timeout=45).strip()
    if not context:
        raise RuntimeError('No Kubernetes context selected')
    k = ['kubectl', f'--context={context}', '--request-timeout=30s']
    from ui import banner
    banner('Environment', context)
    version = read_json([*k, 'version', '-o', 'json'])['serverVersion']['gitVersion']
    nodes = read_json([*k, 'get', 'nodes', '-o', 'json'])['items']
    releases = read_json(['helm', '--kube-context', context, 'list', '-A', '--deployed', '--failed', '--pending', '--uninstalled', '--uninstalling', '--superseded', '--max', '10000', '-o', 'json'])
    workloads = read_json([*k, 'get', 'deployments,daemonsets,statefulsets', '-A', '-o', 'json'])['items']
    classes = read_json([*k, 'get', 'storageclasses', '-o', 'json'])['items']
    ready_nodes = sum(any(c['type'] == 'Ready' and c['status'] == 'True'
                          for c in n.get('status', {}).get('conditions', [])) for n in nodes)
    supported = bool(re.match(r'^v1\.(33|34|35|36)\.', version))
    rows = [['Kubernetes', 'Installed', version, '1.33–1.36',
             f'{ready_nodes}/{len(nodes)} nodes', 'In range' if supported else 'Out of range']]
    for release in config['releases']:
        if release['name'] != 'local-path-provisioner':
            rows.append(component_row(release['name'], release['version'], releases, workloads))
    if any(r.get('name') == 'kamaji' and r.get('status') != 'uninstalled' for r in releases):
        datastores = read_json([*k, 'get', 'datastores.kamaji.clastix.io', '-o', 'json'])['items']
        default = next((d for d in datastores if d['metadata']['name'] == 'default'), None)
        rows.append(['Kamaji DataStore', 'Installed' if default else 'Missing', '-', 'default',
                     'Configured' if default else '-', '-'])
    sc = next((s for s in classes if s['metadata']['name'] == storage), None)
    if sc:
        # Upstream uses rancher.io/local-path; the bundled chart can be configured
        # with a custom name such as cluster.local/local-path-provisioner.
        is_local = 'local-path' in sc.get('provisioner', '')
        found = [w for w in workloads if belongs(w, 'local-path-provisioner')] if is_local else []
        images = sorted({c['image'].rsplit(':', 1)[-1] for w in found
                         for c in w.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
                         if c.get('image', '').split('@')[0].split(':')[0].endswith('/local-path-provisioner')
                         and '@' not in c['image'] and ':' in c['image'].rsplit('/', 1)[-1]})
        rows.append([f'Storage ({storage})', 'Reused', ', '.join(images) + ' app' if images else 'Unknown',
                     'Any existing', health(found), 'Accepted'])
    else:
        rows.append([f'Storage ({storage})', 'Missing', '-', '0.0.34' if storage == 'local-path' else 'Existing class', '-', '-'])
    missing = sum(row[1] == 'Missing' for row in rows)
    review = sum(row[5] in ('Review', 'Out of range') or row[4] in ('Unknown', 'Not ready') or
                 row[1] not in ('Installed', 'Reused', 'Missing') for row in rows)
    operator = component_row('dpf-operator', 'v26.4.0', releases, workloads)
    print_table([*rows, operator])
    if more:
        print('\nVersions are Helm chart versions, except Kubernetes and storage image tags.')
        print('Match = NVIDIA v26.4.0 pin. Review = compatibility is not verified.')
        print('Readiness checks controller rollout status; storage provisioning is not tested.')
        print(f'\nSummary: {missing} missing | {review} need review | nodes {ready_nodes}/{len(nodes)} ready')
        print('\nNext steps:')
        if not supported or not nodes or ready_nodes != len(nodes):
            print('  Restore a supported, Ready Kubernetes cluster before installing prerequisites.')
        if missing:
            print('  Install missing prerequisites: ./dpf-install.sh --install-prereq')
        if review:
            print('  Investigate component health/version differences: ./dpf-install.sh --diagnose --more')
            print('  Unmanaged = found outside a matching Helm release; do not blindly reinstall.')
        if not missing and not review and nodes and ready_nodes == len(nodes):
            print('  Prerequisites look ready. Continue with the DPF operator installation guide.')
        print('The prerequisite action does not install the operator or provision DPUs.')
    problems = 0
    if diagnose:
        namespaces = {'cert-manager', 'dpf-operator-system', 'local-path-storage', 'local-path-provisioner'}
        for release in releases:
            if any(release.get('name') == r['name'] or release.get('chart', '').startswith(
                    r['chart'].rsplit('/', 1)[-1] + '-') for r in config['releases']):
                namespaces.add(release['namespace'])
        problems = diagnose_cluster(k, namespaces, more=more)
    return 0 if (not missing and not review and not problems and nodes and ready_nodes == len(nodes)) else 1


def problem_hint(reason):
    if reason in ('ImagePullBackOff', 'ErrImagePull', 'InvalidImageName'):
        return 'Check the image name, registry access and image-pull credentials.'
    if reason == 'CrashLoopBackOff':
        return 'Read this container’s previous logs; check its configuration and dependencies.'
    if reason in ('FailedScheduling', 'Pending'):
        return 'Check node capacity, taints, scheduling rules and unbound volumes.'
    if reason in ('FailedMount', 'FailedAttachVolume', 'ProvisioningFailed', 'Unbound PVC'):
        return 'Check the StorageClass, provisioner and volume events.'
    if reason == 'OOMKilled':
        return 'Check container memory limits and node memory pressure.'
    return 'Inspect this resource and its events for the reported cause.'


def diagnose_cluster(k, namespaces, more=False):
    # Complete every read before presenting findings: failed reads are never "all healthy".
    pods = read_json([*k, 'get', 'pods', '-A', '-o', 'json'])['items']
    pvcs = read_json([*k, 'get', 'pvc', '-A', '-o', 'json'])['items']
    events = read_json([*k, 'get', 'events', '-A', '--field-selector=type=Warning', '-o', 'json'])['items']
    issues = []
    for pod in pods:
        meta, state = pod['metadata'], pod.get('status', {})
        if meta['namespace'] not in namespaces or state.get('phase') == 'Succeeded':
            continue
        for container in state.get('initContainerStatuses', []) + state.get('containerStatuses', []):
            detail = container.get('state', {}).get('waiting') or container.get('state', {}).get('terminated')
            if detail and detail.get('reason') != 'Completed':
                issues.append((meta['namespace'], meta['name'], detail.get('reason', 'Unknown')))
        if state.get('phase') in ('Pending', 'Failed', 'Unknown'):
            issues.append((meta['namespace'], meta['name'], state.get('reason', state['phase'])))
        elif state.get('phase') == 'Running' and not any(
                c.get('type') == 'Ready' and c.get('status') == 'True' for c in state.get('conditions', [])):
            issues.append((meta['namespace'], meta['name'], 'NotReady'))
    for pvc in pvcs:
        meta = pvc['metadata']
        if meta['namespace'] in namespaces and pvc.get('status', {}).get('phase') != 'Bound':
            issues.append((meta['namespace'], meta['name'], 'Unbound PVC'))
    kamaji_crash = any(belongs(pod, 'kamaji') and any(
        c.get('state', {}).get('waiting', {}).get('reason') == 'CrashLoopBackOff'
        for c in pod.get('status', {}).get('containerStatuses', [])) for pod in pods)
    missing_datastore = False
    if kamaji_crash:
        datastores = read_json([*k, 'get', 'datastores.kamaji.clastix.io', '-o', 'json'])['items']
        missing_datastore = not any(d['metadata']['name'] == 'default' for d in datastores)
        if missing_datastore:
            issues.append(('cluster', 'Kamaji default DataStore', 'Missing'))
    relevant = [e for e in events if e['metadata']['namespace'] in namespaces]
    relevant.sort(key=lambda e: e.get('lastTimestamp') or e.get('eventTime') or
                  e['metadata'].get('creationTimestamp', ''))
    print()
    if not more:
        print_table([['Pod/PVC issues', str(len(set(issues)))], ['Warning events', str(len(relevant))]],
                    headers=['CHECK', 'COUNT'])
        if issues:
            print()
            print_table(sorted(set(issues)), headers=['NAMESPACE', 'RESOURCE', 'STATUS'])
    else:
        print('Diagnostics | prerequisite and DPF namespaces')
        if not issues:
            print('  No pod/PVC problems detected in this snapshot.')
        for namespace, name, reason in sorted(set(issues)):
            print(f'  {namespace}/{name}: {reason}\n    {problem_hint(reason)}')
        if missing_datastore:
            print('\nKamaji is missing its default DataStore. This points to a bootstrap issue, not a missing NIC.')
            print('Run ./dpf-install.sh --install-prereq to perform the staged bootstrap.')
        print('\nLatest warning events (up to 10; may describe an earlier failure):')
        if not relevant:
            print('  None found.')
        for event in relevant[-10:]:
            obj = event.get('involvedObject', {})
            message = ' '.join(event.get('message', '').split())
            print(f"  {event['metadata']['namespace']}/{obj.get('name', '?')}: {event.get('reason', '?')}")
            print(f'    {message}')
    return len(issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', default='')
    parser.add_argument('--storage-class', default='local-path')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--more', action='store_true')
    args = parser.parse_args()
    try:
        return report(args.context, args.storage_class, args.diagnose, args.more)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, ImportError) as error:
        print(f'\nUnable to complete status check: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
