import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

deploy=module('deploy',ROOT/'scripts/deploy.py')
private=module('private_bootstrap',ROOT/'scripts/private-bootstrap.py')


def render(stage=6,values=None):
    args=['helm','template','nico-stack',str(ROOT/'charts/stack'),'--set',f'stage={stage}']
    if values: args+=['-f','-']
    p=subprocess.run(args,input=yaml.safe_dump(values) if values else None,text=True,capture_output=True,check=True)
    return [o for o in yaml.safe_load_all(p.stdout) if o]


class StackTests(unittest.TestCase):
    def setUp(self): self.values=yaml.safe_load((ROOT/'charts/stack/values.yaml').read_text())

    def test_stages_retain_existing_apps_and_delay_core(self):
        old=set()
        for stage in range(1,7):
            apps=render(stage); names={a['metadata']['name'] for a in apps}
            self.assertTrue(old<=names); old=names
            self.assertEqual('nico-core' in names,stage==6)
            for a in apps:
                self.assertNotIn('finalizers',a['metadata'])
                self.assertFalse(a['spec']['syncPolicy']['automated']['prune'])
                self.assertIn('FailOnSharedResource=true',a['spec']['syncPolicy']['syncOptions'])
        self.assertNotIn('dpf-platform',old)

    def test_integrated_toml_and_image_pins(self):
        self.values['dpf']['enableIntegration']=True
        a=next(a for a in render(values=self.values) if a['metadata']['name']=='nico-core')
        source=a['spec']['sources'][0];v=source['helm']['valuesObject']
        self.assertEqual(source['targetRevision'],'80d131a5cd3280f9cef3131fa0c5647bdf3e79d0')
        t=tomllib.loads(v['nico-api']['siteConfig']['nicoApiSiteConfig'])
        self.assertTrue(t['dpf']['enabled'])
        self.assertEqual(t['dpf']['services']['otel']['docker_repo_url'],'harbor.runailabs-ps.com/nico/otelcol-contrib')
        self.assertEqual(len(v['nico-pxe']['bootArtifactContainers']),2)
        self.assertEqual(v['nico-api']['webAuth']['basic']['existingSecret']['name'],'nico-api-web-basic-auth')

    def test_external_dpf_argo_does_not_own_crds(self):
        v=yaml.safe_load((ROOT/'values/argo-cd.yaml').read_text())
        self.assertFalse(v['crds']['install'])
        self.assertEqual(v['configs']['params']['application.namespaces'],'dpf-operator-system')
        self.assertEqual(v['configs']['cm']['installationID'],'nico-dpf-services')

    def test_bad_addresses_duplicates_and_secrets(self):
        cases=[]
        for key,value in [('apiVIP','not-an-ip'),('apiVIP',self.values['network']['dhcpVIP'])]:
            v=copy.deepcopy(self.values);v['network'][key]=value;cases.append(v)
        v=copy.deepcopy(self.values);v['dpf']['dpuVIP']='192.0.2.39';cases.append(v)
        v=copy.deepcopy(self.values);v['coreExtraValues']['password']='secret';cases.append(v)
        v=copy.deepcopy(self.values);v['pools']['vlan']['end']=5000;cases.append(v)
        for v in cases:
            with self.subTest(v=v):
                with self.assertRaises(ValueError): deploy.validate(v)
        deploy.validate(self.values)
        with self.assertRaises(ValueError): deploy.validate(self.values,live=True)

    def test_typo_does_not_silently_install_dhcp_or_storage(self):
        self.values['storag']={'install':True}
        with self.assertRaises(subprocess.CalledProcessError): render(values=self.values)

    def test_storage_opt_in(self):
        self.assertNotIn('nico-storage',{a['metadata']['name'] for a in render()})
        self.values['storage']['install']=True
        self.assertIn('nico-storage',{a['metadata']['name'] for a in render(values=self.values)})

    def test_prereq_render_stable_private_material_absent(self):
        cmd=['helm','template','nico-prereqs',str(ROOT/'charts/prerequisites'),'-n','nico-system','--set','siteName=test']
        first=subprocess.check_output(cmd,text=True); second=subprocess.check_output(cmd,text=True)
        self.assertEqual(first,second)
        objs=[o for o in yaml.safe_load_all(first) if o]
        for o in objs:
            if o['kind']=='Secret':
                self.assertNotIn('data',o);self.assertNotIn('stringData',o)
        job=next(o for o in objs if o['kind']=='Job')
        self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/hook'],'Sync')
        issuer=next(o for o in objs if o['kind']=='ClusterIssuer')
        self.assertGreater(int(issuer['metadata']['annotations']['argocd.argoproj.io/sync-wave']),int(job['metadata']['annotations']['argocd.argoproj.io/sync-wave']))

    def test_bootstrap_trust_and_secret_scope(self):
        raw=subprocess.check_output(['helm','template','nico-prereqs',str(ROOT/'charts/prerequisites'),'-n','nico-system'],text=True)
        self.assertNotIn('VAULT_SKIP_VERIFY',raw)
        self.assertNotIn('--no-check-certificate',raw)
        self.assertNotIn('-tls-skip-verify',raw)
        objs=[o for o in yaml.safe_load_all(raw) if o]
        job=next(o for o in objs if o['kind']=='Job')
        pod=job['spec']['template']['spec']
        self.assertEqual(pod['volumes'][0]['secret']['secretName'],'nico-roots')
        self.assertIn('alpine/k8s:1.34.1@sha256:',pod['initContainers'][1]['image'])
        role=next(o for o in objs if o['metadata']['name']=='eso-postgres-ns-role')
        self.assertEqual(role['kind'],'Role')
        self.assertEqual(role['metadata']['namespace'],'postgres')
        review=next(o for o in objs if o['kind']=='ClusterRole' and o['metadata']['name']=='nico-eso-self-review')
        self.assertEqual(review['rules'][0]['resources'],['selfsubjectrulesreviews'])

    def test_secret_payload_not_in_argv(self):
        seen=[]
        original=private.kubectl
        try:
            private.kubectl=lambda args,data=None,check=True: seen.append((args,data))
            private.secret('test','nico-system',{'password':'private-test-value'})
        finally: private.kubectl=original
        args,body=seen[0]
        self.assertNotIn('private-test-value',str(args))
        self.assertEqual(json.loads(body)['data']['password'],'cHJpdmF0ZS10ZXN0LXZhbHVl')

    def test_private_files_reject_world_readable_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'credentials';p.write_text('private');p.chmod(0o644)
            with self.assertRaises(ValueError):private.private_file(p)
            p.chmod(0o600);self.assertEqual(private.private_file(p),p)
            link=Path(tmp)/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):private.private_file(link)


if __name__=='__main__': unittest.main()
