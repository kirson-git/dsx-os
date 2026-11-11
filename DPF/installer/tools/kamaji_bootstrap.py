"""Stage Kamaji startup without a default DataStore, then create it via its webhook."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.tools'))
import yaml
from prereq_status import read_json


def output(command):
    result = subprocess.run(command, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed: {result.stderr.strip()}')
    return result.stdout


def optional_object(k, *args):
    text = output([*k, 'get', *args, '--ignore-not-found', '-o', 'json'])
    return json.loads(text) if text.strip() else None


def needs_bootstrap(k):
    if not optional_object(k, 'crd', 'datastores.kamaji.clastix.io'):
        return True
    if optional_object(k, 'datastores.kamaji.clastix.io', 'default'):
        context = [arg.split('=', 1)[1] for arg in k if arg.startswith('--context=')]
        helm = ['helm', *(['--kube-context', context[0]] if context else [])]
        releases = read_json([*helm, 'list', '-n', 'dpf-operator-system',
                              '--filter', '^kamaji$', '--deployed', '--failed', '--pending',
                              '--uninstalled', '--uninstalling', '--superseded', '-o', 'json'])
        if any(r['status'].startswith('pending-') or r['status'] == 'uninstalling' for r in releases):
            raise RuntimeError('Kamaji has an unfinished Helm operation; resolve it before bootstrap.')
        if any(r['status'] == 'deployed' for r in releases):
            return False
    # Do not alter datastore selection on a controller already serving tenants.
    tenants = read_json([*k, 'get', 'tenantcontrolplanes.kamaji.clastix.io', '-A', '-o', 'json'])['items']
    if tenants:
        raise RuntimeError('Kamaji bootstrap is needed but tenant control planes exist; '
                           'restore their controller/datastore configuration before automatic bootstrap.')
    return True


def prepare(run):
    documents = list(yaml.safe_load_all((run / 'helmfiles/prereqs.yaml').read_text()))
    release = next(r for r in documents[-1]['releases'] if r['name'] == 'kamaji')
    release['values'].append({'defaultDatastoreName': '', 'kamaji-etcd': {'datastore': {'enabled': False}}})
    (run / 'helmfiles/bootstrap.yaml').write_text(yaml.safe_dump_all(documents, sort_keys=False))


def owned_datastore(rendered):
    documents = [d for d in yaml.safe_load_all(rendered) if d]
    if len(documents) != 1 or documents[0].get('kind') != 'DataStore':
        raise ValueError('Expected exactly one rendered Kamaji DataStore')
    obj = documents[0]
    if obj.get('apiVersion') != 'kamaji.clastix.io/v1alpha1' or obj.get('metadata', {}).get('name') != 'default':
        raise ValueError('Expected the default Kamaji DataStore')
    metadata = obj['metadata']
    metadata.setdefault('labels', {})['app.kubernetes.io/managed-by'] = 'Helm'
    metadata.setdefault('annotations', {}).update({
        'meta.helm.sh/release-name': 'kamaji',
        'meta.helm.sh/release-namespace': 'dpf-operator-system',
    })
    return obj


def create_datastore(run, k):
    existing = optional_object(k, 'datastores.kamaji.clastix.io', 'default')
    if existing:
        metadata = existing.get('metadata', {})
        annotations = metadata.get('annotations', {})
        if (annotations.get('meta.helm.sh/release-name') != 'kamaji'
                or annotations.get('meta.helm.sh/release-namespace') != 'dpf-operator-system'
                or metadata.get('labels', {}).get('app.kubernetes.io/managed-by') != 'Helm'):
            raise RuntimeError('Existing default DataStore has different or unknown ownership; '
                               'automatic adoption is disabled.')
        print('Retained default DataStore reused; final Helm reconciliation follows.')
        return
    docs = list(yaml.safe_load_all((run / 'helmfiles/prereqs.yaml').read_text()))
    release = next(r for r in docs[-1]['releases'] if r['name'] == 'kamaji')
    # Helm 4 prints OCI pull progress on stdout. Pull first so template stdout
    # contains only YAML, rather than parsing progress text as an extra document.
    chart_dir = run / 'charts'
    chart_dir.mkdir(exist_ok=True)
    output(['helm', 'pull', release['chart'], '--version', release['version'], '--destination', str(chart_dir)])
    chart_path = chart_dir / f'kamaji-{release["version"]}.tgz'
    command = ['helm', 'template', 'kamaji', str(chart_path),
               '--namespace', release['namespace'], '--show-only', 'charts/kamaji-etcd/templates/etcd_datastore.yaml']
    for index, value in enumerate(release['values']):
        if isinstance(value, str):
            path = run / 'helmfiles' / value
        else:
            path = run / f'kamaji-values-{index}.yaml'
            path.write_text(yaml.safe_dump(value))
        command.extend(['--values', str(path)])
    obj = owned_datastore(output(command))
    path = run / 'default-datastore.json'
    path.write_text(json.dumps(obj, indent=2) + '\n')
    # The staged Helm apply has already waited for controller/webhook/etcd readiness.
    # No failurePolicy changes, forced adoption or finalizer removal are needed.
    output([*k, 'create', '-f', str(path)])
    print('Default DataStore created through the running Kamaji webhook.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'create'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--context', required=True)
    args = parser.parse_args()
    k = ['kubectl', f'--context={args.context}', '--request-timeout=30s']
    try:
        if args.action == 'prepare':
            needed = needs_bootstrap(k)
            (args.run / 'needs-bootstrap').write_text('true' if needed else 'false')
            if needed:
                prepare(args.run)
                print('Kamaji: staged bootstrap required (missing datastore or inactive Helm release).')
            else:
                print('Kamaji: default DataStore exists; normal reconciliation.')
        else:
            create_datastore(args.run, k)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f'Kamaji bootstrap stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
