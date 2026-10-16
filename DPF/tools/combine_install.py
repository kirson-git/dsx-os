#!/usr/bin/env python3
"""Compose existing site Applications into one pinned, clean-install Application."""
import argparse
import copy
import os
from pathlib import Path
import re

import yaml


def combine(apps, revision, reboot=False):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use a full, published Git commit SHA')
    expected = ['dpf-platform', 'dpf-site', 'dpf-hbn', 'dpf-provisioning']
    if [a.get('metadata', {}).get('name') for a in apps] != expected:
        raise ValueError('Expected platform, site, HBN and provisioning Applications in order')
    for a in apps:
        if a.get('kind') != 'Application' or 'source' not in a['spec']:
            raise ValueError('Each input must be a single-source Application')
        if a['metadata'].get('namespace') != 'argocd' or a['spec']['destination'] != apps[0]['spec']['destination']:
            raise ValueError('All Applications must use argocd and the same destination')
        if a['spec']['source']['repoURL'] != apps[0]['spec']['source']['repoURL']:
            raise ValueError('All four sources must use the same repository')
    sources = [copy.deepcopy(a['spec']['source']) for a in apps]
    for source in sources:
        source['targetRevision'] = revision
    if reboot:
        hosts = sources[1]['helm']['valuesObject'].get('bootstrap', {}).get('hosts', [])
        if not hosts or len({h['dpuNode'] for h in hosts}) != len(hosts):
            raise ValueError('Reboot requires unique bootstrap.hosts DPUNode identities')
        by_node = {h['dpuNode']: h for h in hosts}
        matched = set()
        for patch in sources[3]['kustomize']['patches']:
            ops = yaml.safe_load(patch['patch'])
            name = patch['target']['name']
            for op in ops:
                if op['path'] == '/metadata/name':
                    name = op['value']
            for op in ops:
                if op['path'] != '/spec':
                    continue
                spec = op['value']
                kind = patch['target']['kind']
                if kind == 'DPUNode':
                    if name not in by_node:
                        raise ValueError(f'Missing verified reboot host for {name}')
                    spec['nodeRebootMethod'] = {'script': {'name': 'dpf-reboot-' + by_node[name]['name']}}
                    matched.add(name)
                elif kind == 'DPUSet':
                    spec['dpuTemplate']['spec']['nodeEffect']['hold'] = False
                elif kind == 'DPUDeployment':
                    spec['dpus']['nodeEffect']['hold'] = False
            patch['patch'] = yaml.safe_dump(ops, sort_keys=False)
        if matched != set(by_node):
            raise ValueError('Reboot hosts do not match the overridden DPUNode specs')
    elif sources[1]['helm']['valuesObject'].get('bootstrap', {}).get('hosts'):
        raise ValueError('bootstrap.hosts requires --reboot so hardware policy stays consistent')
    return {
        'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
        'metadata': {'name': 'dpf', 'namespace': 'argocd'},
        'spec': {'project': apps[0]['spec'].get('project', 'default'),
                 'destination': copy.deepcopy(apps[0]['spec']['destination']),
                 'sources': sources,
                 'syncPolicy': {'automated': {'prune': False, 'selfHeal': False},
                                'syncOptions': ['ServerSideApply=true', 'ClientSideApplyMigration=false',
                                                'FailOnSharedResource=true'],
                                'retry': {'limit': 5, 'backoff': {'duration': '10s', 'factor': 2, 'maxDuration': '3m'}}}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['platform', 'config', 'hbn', 'provisioning']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--revision', required=True, help='Full published Git commit SHA for all sources')
    parser.add_argument('--reboot', action='store_true', help='Use configured bootstrap.hosts; remove maintenance holds for unattended provisioning')
    parser.add_argument('--output', required=True, type=Path, help='New private Application file; must not already exist')
    args = parser.parse_args()
    try:
        apps = [yaml.safe_load(getattr(args, n).read_text()) for n in ['platform', 'config', 'hbn', 'provisioning']]
        app = combine(apps, args.revision, args.reboot)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('# Private site settings. Clean install only; do not combine with the four staged Applications.\n')
            yaml.safe_dump(app, stream, sort_keys=False, width=100)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Cannot compose Application: {exc}\n')
    print(f'Prepared {args.output}; no cluster changes. Apply only after the agreed DPF cleanup.')


if __name__ == '__main__':
    main()
