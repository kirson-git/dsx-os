import pathlib
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

class LabApplicationTests(unittest.TestCase):
    def test_inline_lab_settings_preserve_resources_and_readiness_gates(self):
        apps = list(yaml.safe_load_all((ROOT / 'DPF/labs/nico-lab/applications.yaml').read_text()))
        self.assertEqual([a['metadata']['name'] for a in apps], ['dpf-operator-config', 'dpf-tenants'])
        rendered = []
        for app in apps:
            self.assertNotIn('automated', app['spec']['syncPolicy'])
            self.assertNotIn('finalizers', app['metadata'])
            self.assertNotIn('directory', app['spec']['source'])
            source = ROOT / app['spec']['source']['path']
            original = [o for p in sorted(source.glob('*.yaml')) for o in yaml.safe_load_all(p.read_text())]
            with tempfile.TemporaryDirectory() as tmp:
                shutil.copytree(source, tmp, dirs_exist_ok=True)
                kfile = pathlib.Path(tmp) / 'Kustomization'
                k = yaml.safe_load(kfile.read_text())
                k['patches'] = app['spec']['source']['kustomize']['patches']
                kfile.write_text(yaml.safe_dump(k, sort_keys=False))
                output = subprocess.check_output(['kubectl', 'kustomize', tmp], text=True)
            objects = list(yaml.safe_load_all(output))
            def identity(o): return (o['kind'], o['metadata'].get('namespace', ''), o['metadata']['name'])
            self.assertEqual(set(map(identity, original)), set(map(identity, objects)))
            for obj in objects:
                if obj['kind'] == 'Job':
                    self.assertEqual(obj['metadata']['annotations']['argocd.argoproj.io/hook'], 'Sync')
                self.assertNotEqual(obj['kind'], 'Secret')
            rendered.extend(objects)
        config = next(o for o in rendered if o['kind'] == 'DPFOperatorConfig')
        self.assertEqual(config['spec']['overrides']['kubernetesAPIServerVIP'], '10.220.175.20')
        self.assertEqual(config['spec']['overrides']['kubernetesAPIServerPort'], 6443)
        for tenant, vip in [('europe', '192.168.0.200'), ('asia', '192.168.0.203')]:
            obj = next(o for o in rendered if o['kind'] == 'DPUCluster' and o['metadata']['name'] == 'tenant-' + tenant)
            self.assertEqual(obj['spec']['clusterEndpoint']['keepalived']['vip'], vip)
            self.assertEqual(obj['spec']['clusterEndpoint']['keepalived']['interface'], 'enp7s0')
        base = yaml.safe_load((ROOT / 'DPF/profiles/two-tenant-hbn/desired/10-operator-config/dpfoperatorconfig-dpfoperatorconfig.yaml').read_text())
        self.assertEqual(base['spec']['overrides']['kubernetesAPIServerVIP'], '198.51.100.20')
