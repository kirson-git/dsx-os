#!/usr/bin/env python3
"""Bundle canonical operator/tenant manifests for the standalone site Helm chart."""
import argparse
import json
from pathlib import Path

import yaml

DPF = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if the committed bundle is stale')
    args = parser.parse_args()
    objects = []
    for stage in ('10-operator-config', '20-tenants'):
        directory = DPF / 'profiles/two-tenant-hbn/desired' / stage
        for path in sorted(directory.glob('*.yaml')):
            objects.extend(o for o in yaml.safe_load_all(path.read_text()) if o)
    content = json.dumps(objects, indent=2) + '\n'
    destination = DPF / 'charts/site/files/resources.json'
    if args.check:
        if not destination.exists() or destination.read_text() != content:
            parser.exit(1, 'Site chart bundle is stale; run python3 DPF/tools/package_site.py\n')
        print('Site chart bundle matches canonical profiles')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        print(f'Packaged {len(objects)} operator/tenant resources')


if __name__ == '__main__':
    main()
