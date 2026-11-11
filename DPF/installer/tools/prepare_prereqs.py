"""Prepare a run-local NVIDIA Helmfile, preserving its values and hooks."""
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.tools'))
try:
    import yaml
except ImportError:
    sys.exit('PyYAML is required: install it for python3 or into dpf-installation/.tools.')


def prepare(base, run, storage, timeout):
    existing = json.loads((run / 'storage.json').read_text())['items']
    reuse = any(item['metadata']['name'] == storage for item in existing)
    if not reuse and storage != 'local-path':
        raise ValueError(f'StorageClass {storage} is absent; only local-path can be installed automatically')
    target = run / 'helmfiles'
    shutil.copytree(base / 'prerequisites' / 'helmfiles', target)
    path = target / 'prereqs.yaml'
    documents = list(yaml.safe_load_all(path.read_text()))
    state = documents[-1]
    # The bundled chart is the same v0.0.34 source as the upstream git URL.
    # This avoids needing the helm-git downloader just to access that chart.
    state['repositories'] = [repo for repo in state['repositories'] if repo['name'] != 'local-storage']
    if reuse:
        state['releases'] = [release for release in state['releases'] if release['name'] != 'local-path-provisioner']
    else:
        local = next(release for release in state['releases'] if release['name'] == 'local-path-provisioner')
        local['chart'] = str(base / 'prerequisites' / 'charts' / 'local-path-provisioner')
        local['version'] = '0.0.34'
    state['helmDefaults']['timeout'] = timeout
    for release in state['releases']:
        release['timeout'] = timeout
        if release['name'] == 'kamaji':
            # Upstream does not express this storage dependency in its needs.
            if not reuse:
                release['needs'].append('local-path-provisioner/local-path-provisioner')
            if storage != 'local-path':
                release['values'].append({'kamaji-etcd': {'persistentVolumeClaim': {'storageClassName': storage}}})
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False))
    print(f'Reusing StorageClass {storage}; existing provisioner version is accepted.' if reuse
          else 'StorageClass local-path is absent: installing Local Path Provisioner v0.0.34.')
    print(f'{len(state["releases"])} chart releases:')
    for release in state['releases']:
        print(f'  {release["name"]:26} {release.get("version", "bundled"):10} {release["namespace"]}')
    print(f'Generated Helmfile: {path}')


if __name__ == '__main__':
    try:
        prepare(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        sys.exit(f'Cannot prepare prerequisites: {error}')
