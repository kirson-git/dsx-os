"""Exercise the simple customer file against the established lab installation."""
import copy
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import jsonschema
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / 'DPF/charts/site'


def identity(obj):
    return obj['apiVersion'], obj['kind'], obj['metadata'].get('namespace', ''), obj['metadata']['name']


class SiteChartTests(unittest.TestCase):
    def application(self):
        apps = list(yaml.safe_load_all((ROOT / 'DPF/config.yaml').read_text()))
        self.assertEqual(len(apps), 1, 'Customer settings must be one Application')
        return apps[0]

    def values(self):
        return self.application()['spec']['source']['helm']['valuesObject']

    def render(self, values):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'values.yaml'
            path.write_text(yaml.safe_dump(values))
            return subprocess.run(
                ['helm', 'template', 'dpf-site', str(CHART), '-f', str(path)],
                capture_output=True, text=True)

    def objects(self, values):
        result = self.render(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [o for o in yaml.safe_load_all(result.stdout) if o]

    def test_site_application_has_safe_ownership_and_sync_defaults(self):
        app = self.application()
        self.assertEqual(app['metadata']['name'], 'dpf-site')
        self.assertEqual(ROOT / app['spec']['source']['path'], CHART)
        self.assertNotIn('finalizers', app['metadata'])
        policy = app['spec']['syncPolicy']
        self.assertEqual(policy['automated'], {'prune': False, 'selfHeal': False})
        for option in ['ServerSideApply=true', 'ClientSideApplyMigration=false', 'FailOnSharedResource=true']:
            self.assertIn(option, policy['syncOptions'])

    def test_lab_render_matches_existing_kustomize_installation(self):
        expected = []
        apps = yaml.safe_load_all((ROOT / 'DPF/labs/nico-lab/applications.yaml').read_text())
        for app in apps:
            with tempfile.TemporaryDirectory() as tmp:
                shutil.copytree(ROOT / app['spec']['source']['path'], tmp, dirs_exist_ok=True)
                path = pathlib.Path(tmp) / 'Kustomization'
                config = yaml.safe_load(path.read_text())
                config['patches'] = app['spec']['source']['kustomize']['patches']
                path.write_text(yaml.safe_dump(config))
                expected.extend(yaml.safe_load_all(subprocess.check_output(['kubectl', 'kustomize', tmp], text=True)))
        actual = self.objects(self.values())
        self.assertEqual({identity(o): o for o in actual}, {identity(o): o for o in expected})

    def test_customer_values_reach_the_right_endpoints_and_preserve_gates(self):
        values = dict(apiServerIP='10.10.0.10', apiServerPort=7443,
                      vipInterface='ens192', europeVIP='10.11.0.200', asiaVIP='10.11.0.201')
        objects = self.objects(values)
        config = next(o for o in objects if o['kind'] == 'DPFOperatorConfig')
        self.assertEqual(config['spec']['overrides']['kubernetesAPIServerVIP'], '10.10.0.10')
        self.assertEqual(config['spec']['overrides']['kubernetesAPIServerPort'], 7443)
        clusters = {o['metadata']['name']: o for o in objects if o['kind'] == 'DPUCluster'}
        for name, vip in [('tenant-europe', '10.11.0.200'), ('tenant-asia', '10.11.0.201')]:
            endpoint = clusters[name]['spec']['clusterEndpoint']['keepalived']
            self.assertEqual(endpoint['vip'], vip)
            self.assertEqual(endpoint['interface'], 'ens192')
        waves = {o['metadata']['name']: int(o['metadata']['annotations']['argocd.argoproj.io/sync-wave'])
                 for o in objects}
        self.assertLess(waves['dpfoperatorconfig'], waves['dpf-wait-operator'])
        self.assertLess(waves['dpf-wait-operator'], waves['tenant-europe'])
        self.assertLess(waves['tenant-europe'], waves['dpf-wait-tenants'])
        for obj in objects:
            self.assertNotIn(obj['kind'], ['Secret', 'DPU', 'DPUSet', 'DPUDeployment', 'DPUDevice', 'BFB'])
            if obj['kind'] == 'Job':
                self.assertEqual(obj['metadata']['annotations']['argocd.argoproj.io/hook'], 'Sync')
        crds = yaml.safe_load_all((ROOT / 'DPF/generated/platform/platform.yaml').read_text())
        schemas = {o['spec']['names']['kind']: o['spec']['versions'][0]['schema']['openAPIV3Schema']
                   for o in crds if o and o['kind'] == 'CustomResourceDefinition'}
        for obj in [config, *clusters.values()]:
            jsonschema.Draft7Validator(schemas[obj['kind']]).validate(obj)

    def test_invalid_settings_fail_before_any_resources_are_emitted(self):
        original = self.values()
        cases = [('apiServerIP', 'host.example.com'), ('apiServerIP', '10.0.0.256'),
                 ('apiServerIP', '127.0.0.1'), ('apiServerIP', '0.0.0.0'),
                 ('europeVIP', '224.0.0.1'), ('asiaVIP', '2001:db8::1'),
                 ('asiaVIP', original['europeVIP']), ('asiaVIP', original['apiServerIP']),
                 ('europeVIP', original['apiServerIP']), ('europeVIP', None),
                 ('vipInterface', ''), ('vipInterface', 'interface-too-long'),
                 ('vipInterface', 'bad iface'), ('apiServerPort', 0),
                 ('apiServerPort', 65536), ('apiServerPort', '6443'),
                 ('apiServerPort', True), ('unknownSetting', 'typo')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = copy.deepcopy(original)
                values[key] = value
                result = self.render(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(result.stdout.strip())
        for key in ('apiServerIP', 'vipInterface', 'europeVIP', 'asiaVIP'):
            with self.subTest(missing=key):
                values = dict(original)
                del values[key]
                self.assertNotEqual(self.render(values).returncode, 0)

    def test_chart_bundle_is_current_with_canonical_profiles(self):
        result = subprocess.run(['python3', str(ROOT / 'DPF/tools/package_site.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
