#!/usr/bin/env python3
"""Offline renders, plus optional remote chart fetches. Never contacts Kubernetes."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
PIN='80d131a5cd3280f9cef3131fa0c5647bdf3e79d0'


def run(args): return subprocess.check_output(args,text=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',required=True,help='NICo checkout at the pinned release commit')
    p.add_argument('--fetch-charts',action='store_true')
    a=p.parse_args();up=Path(a.upstream).resolve()
    assert run(['git','-C',str(up),'rev-parse','HEAD']).strip()==PIN,'Wrong upstream commit'
    raw=run(['helm','template','nico-stack',str(ROOT/'charts/stack'),'--set','stage=6','--set','storage.install=true'])
    apps=[o for o in yaml.safe_load_all(raw) if o]
    seen={};count=0
    with tempfile.TemporaryDirectory(prefix='nico-render-') as tmp:
        for app in apps:
            name=app['metadata']['name'];source=app['spec']['sources'][0]; ns=app['spec']['destination']['namespace']
            h=source.get('helm',{});cmd=None
            if source.get('path','').startswith('NICo/charts/'):
                cmd=['helm','template',h['releaseName'],str(REPO/source['path']),'-n',ns,'--include-crds']
            elif source.get('path')=='helm':
                cmd=['helm','template','nico',str(up/'helm'),'-n',ns,'--include-crds']
            elif source.get('path')=='deploy/charts/dpf-operator':
                cmd=['helm','template','dpf-operator',str(REPO/'DPF/charts/dpf-operator-v26.4.0.tgz'),'-n',ns,'--include-crds']
            elif 'chart' in source:
                if not a.fetch_charts:
                    print('SKIP remote chart',name);continue
                ref=('oci://'+source['repoURL']+'/'+source['chart']) if not source['repoURL'].startswith('https://') else source['chart']
                cmd=['helm','template',h['releaseName'],ref,'--version',source['targetRevision'],'-n',ns,'--include-crds']
                if ref==source['chart']:cmd+=['--repo',source['repoURL']]
            if cmd:
                for vf in h.get('valueFiles',[]):cmd+=['-f',str(REPO/vf.removeprefix('$settings/'))]
                values=Path(tmp)/'values.yaml';values.write_text(yaml.safe_dump(h.get('valuesObject',{})))
                cmd+=['-f',str(values)]
                output=run(cmd)
            else:
                base=REPO/source['path'] if source['repoURL'].endswith('/dsx-os.git') else up/source['path']
                output='\n---\n'.join(x.read_text() for x in sorted(base.glob('*.yaml')))
            docs=[]
            for obj in yaml.safe_load_all(output):
                if isinstance(obj, dict) and set(obj) == {'Pulled', 'Digest'}:
                    continue  # Helm OCI download diagnostics can precede YAML.
                if obj:
                    docs.extend(obj['items'] if obj.get('kind')=='List' else [obj])
            if name == 'nico-core':
                pxe = next(o for o in docs if o['kind']=='Deployment' and o['metadata']['name']=='nico-pxe')
                checked = 0
                for init in pxe['spec']['template']['spec']['initContainers']:
                    if init['name'] in ['boot-artifacts-x86-64', 'boot-artifacts-aarch64']:
                        checked += 1
                        mounts = [m['mountPath'] for m in init['volumeMounts']]
                        assert '/forge-boot-artifacts/blobs/internal' in mounts
                        assert '/forge-boot-artifacts/blobs/internal' in ' '.join(init.get('command', []))

                assert checked == 2, 'Expected both PXE artifact init containers'
            for obj in docs:
                meta=obj['metadata'];kind=obj['kind']
                if (meta.get('annotations') or {}).get('helm.sh/hook','').startswith('test'):continue
                scope=meta.get('namespace') or ('' if kind in ['Namespace','CustomResourceDefinition','ClusterRole','ClusterRoleBinding','ClusterIssuer','ClusterSecretStore','ClusterExternalSecret','DataStore','StorageClass','ValidatingWebhookConfiguration','MutatingWebhookConfiguration'] else ns)
                key=(obj['apiVersion'].split('/')[0] if '/' in obj['apiVersion'] else '',kind,scope,meta['name'])
                assert key not in seen,f'Duplicate owner: {key}: {seen.get(key)} / {name}'
                seen[key]=name
                if kind=='Secret':
                    assert not obj.get('data') and not obj.get('stringData'),f'Rendered private/random secret: {name}/{meta["name"]}'
                count+=1
            print(f'PASS {name}: {len(docs)} resources',flush=True)
    print(f'PASS: {count} resources; no overlapping owners or embedded private Secrets.')


if __name__=='__main__':main()
