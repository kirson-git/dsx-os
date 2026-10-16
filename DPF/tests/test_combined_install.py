import copy
import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import combine_install


class CombinedInstallTests(unittest.TestCase):
    def inputs(self):
        platform = yaml.safe_load((ROOT / 'generated/applications/00-platform.yaml').read_text())
        site = yaml.safe_load((ROOT / 'config.yaml').read_text())
        stages = []
        for stage in ['30-hbn', '40-provisioning']:
            app = yaml.safe_load((ROOT / f'generated/applications/{stage}.yaml').read_text())
            app['spec']['source'].pop('directory', None)
            app['spec']['source']['kustomize'] = {'patches': []}
            stages.append(app)
        return [platform, site, *stages]

    def test_preserves_private_overrides_and_pins_all_sources(self):
        apps = self.inputs()
        patch = {'target': {'kind': 'DPUService', 'name': 'demo'},
                 'patch': '- op: replace\n  path: /spec/example\n  value: 10.0.0.2\n'}
        apps[2]['spec']['source']['kustomize']['patches'].append(patch)
        before = copy.deepcopy(apps)
        result = combine_install.combine(apps, 'a' * 40)
        self.assertEqual(apps, before)
        self.assertEqual(result['metadata']['name'], 'dpf')
        self.assertNotIn('source', result['spec'])
        self.assertEqual(len(result['spec']['sources']), 4)
        self.assertTrue(all(s['targetRevision'] == 'a' * 40 for s in result['spec']['sources']))
        self.assertEqual(result['spec']['sources'][2]['kustomize']['patches'][0], patch)
        self.assertIn('FailOnSharedResource=true', result['spec']['syncPolicy']['syncOptions'])
        self.assertFalse(result['spec']['syncPolicy']['automated']['prune'])

    def test_rejects_unpinned_revision_and_wrong_stage(self):
        for revision in ['main', '', 'abc']:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                combine_install.combine(self.inputs(), revision)
        apps = self.inputs()
        apps[3]['metadata']['name'] = 'wrong'
        with self.assertRaises(ValueError):
            combine_install.combine(apps, 'a' * 40)

    def test_reboot_only_changes_selected_hardware_policy(self):
        apps = self.inputs()
        hosts = [{'name': 'europe', 'dpuNode': 'dpu-node-example', 'idracIP': '192.0.2.1',
                  'serial': 'SERVICE1', 'managementNode': 'node1', 'verifyTLS': True}]
        apps[1]['spec']['source']['helm']['valuesObject']['bootstrap'] = {'hosts': hosts}
        patches = apps[3]['spec']['source']['kustomize']['patches']
        for kind, name, spec in [
                ('DPUNode', 'dpu-node-example', {'dpus': [{'name': 'device1'}], 'nodeRebootMethod': {'external': {}}}),
                ('DPUSet', 'europe', {'dpuTemplate': {'spec': {'nodeEffect': {'hold': True, 'force': False}}}})]:
            patches.append({'target': {'kind': kind, 'name': name}, 'patch': yaml.safe_dump([
                {'op': 'replace', 'path': '/spec', 'value': spec}])})
        result = combine_install.combine(apps, 'a' * 40, reboot=True)
        changed = [yaml.safe_load(p['patch'])[0]['value'] for p in result['spec']['sources'][3]['kustomize']['patches']]
        self.assertEqual(changed[0]['nodeRebootMethod'], {'script': {'name': 'dpf-reboot-europe'}})
        self.assertEqual(changed[0]['dpus'], [{'name': 'device1'}])
        self.assertEqual(changed[1]['dpuTemplate']['spec']['nodeEffect'], {'hold': False, 'force': False})
        hosts[0]['dpuNode'] = 'missing-node'
        with self.assertRaises(ValueError):
            combine_install.combine(apps, 'a' * 40, reboot=True)
