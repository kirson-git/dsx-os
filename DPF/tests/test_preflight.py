import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))


class PreflightTests(unittest.TestCase):
    def module(self, name):
        self.assertTrue((ROOT/'tools'/f'{name}.py').exists(), 'credential preflight is missing')
        spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_redfish_checks_auth_identity_and_never_exposes_response(self):
        probe = self.module('preflight_probe')
        target = {'name': 'europe iDRAC', 'ip': '192.0.2.1', 'port': 443,
                  'path': '/redfish/v1/Systems/System.Embedded.1', 'serial': 'EXPECTED',
                  'username': 'root', 'password': 'private-test-password', 'verifyTLS': True}
        cases = [(0, '{"SerialNumber":"EXPECTED"}\n200', True),
                 (0, '{"SerialNumber":"OTHER"}\n200', False),
                 (0, 'private-test-password\n401', False),
                 (0, '{}\n302', False), (60, '', False), (28, '', False),
                 (0, 'not-json\n200', False)]
        for code, body, ok in cases:
            with self.subTest(code=code, body=body), patch.object(probe.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], code, body, 'private-test-password')) as run:
                result = probe.redfish(target)
                self.assertEqual(result['ok'], ok)
                self.assertNotIn('private-test-password', json.dumps(result))
                argv = run.call_args.args[0]
                self.assertNotIn('private-test-password', ' '.join(argv))
                self.assertNotIn('--location', argv)
                self.assertNotIn('--insecure', argv)
                self.assertIn('--config', argv)

    def test_config_maps_each_bmc_to_its_management_node_and_rejects_incomplete(self):
        preflight = self.module('preflight')
        import installer
        sources = [{'path': p, 'repoURL': 'https://github.com/kirson-git/dsx-os.git',
                    'targetRevision': 'a'*40} for p in installer.SOURCE_PATHS]
        sources[1]['helm'] = {'valuesObject': {'bootstrap': {'hosts': [
            {'name': 'europe', 'dpuNode': 'node-eu', 'idracIP': '192.0.2.1',
             'serial': 'SERVER1', 'managementNode': 'worker1', 'verifyTLS': True}]}}}
        import yaml
        sources[3]['kustomize'] = {'patches': [{'target': {'kind': 'DPUDevice'}, 'patch': yaml.safe_dump([
            {'op': 'replace', 'path': '/spec', 'value': {'bmcIp': '192.0.2.2', 'serialNumber': 'DPU1'}},
            {'op': 'add', 'path': '/metadata/labels', 'value': {'provisioning.dpu.nvidia.com/dpunode-name': 'node-eu'}}])}]}
        app = {'kind': 'Application', 'metadata': {'name': 'dpf', 'namespace': 'argocd'},
               'spec': {'destination': {'name': 'in-cluster', 'namespace': 'dpf-operator-system'},
                        'sources': sources, 'syncPolicy': {'syncOptions': ['FailOnSharedResource=true']}}}
        targets = preflight.targets_from_config(app, insecure_bmc=False)
        self.assertEqual([(t['ip'], t['serial'], t['node']) for t in targets],
                         [('192.0.2.1', 'SERVER1', 'worker1'), ('192.0.2.2', 'DPU1', 'worker1')])
        device_patch = sources[3]['kustomize']['patches'][0]
        original = device_patch['patch']
        device_patch['patch'] = yaml.safe_dump(yaml.safe_load(original) + [
            {'op': 'replace', 'path': '/spec/bmcIp', 'value': '192.0.2.99'}])
        with self.assertRaises(ValueError): preflight.targets_from_config(app, insecure_bmc=False)
        device_patch['patch'] = original
        sources[3]['kustomize']['patches'] = []
        with self.assertRaises(ValueError): preflight.targets_from_config(app, insecure_bmc=False)

    def test_helper_failure_always_cleans_up_and_returns_failure(self):
        preflight = self.module('preflight')
        target = {'name': 'europe iDRAC', 'node': 'worker1', 'password': 'private-test-password'}
        calls = []
        def kube(args, payload=None, timeout=60):
            calls.append(args)
            if 'exec' in args: raise RuntimeError('probe failed')
            return ''
        with patch.object(preflight, 'kube', side_effect=kube):
            with self.assertRaises(RuntimeError): preflight.run_checks([target])
        self.assertEqual(calls[-1][0:2], ['delete', 'namespace'])
        self.assertNotIn('private-test-password', str(calls))

    def test_ambiguous_namespace_create_timeout_attempts_cleanup(self):
        preflight = self.module('preflight')
        calls = []
        def kube(args, payload=None, timeout=60):
            calls.append(args)
            if args[0] == 'create':
                raise subprocess.TimeoutExpired('kubectl', 60)
            return ''
        with patch.object(preflight, 'kube', side_effect=kube):
            with self.assertRaises(subprocess.TimeoutExpired):
                preflight.run_checks([{'name':'device', 'node':'worker1'}])
        self.assertEqual(calls[-1][:2], ['delete', 'namespace'])
        self.assertIn('--ignore-not-found', calls[-1])

    def test_ssh_requires_successful_authenticated_command(self):
        probe = self.module('preflight_probe')
        target = {'name': 'DPU SSH', 'ip': '192.0.2.2', 'username': 'ubuntu',
                  'password': 'private-test-password', 'knownHosts': '192.0.2.2 ssh-ed25519 AAAA\n'}
        for code, ok in [(0, True), (255, False)]:
            with patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, '', 'private-test-password')) as run:
                result = probe.ssh(target)
                self.assertEqual(result['ok'], ok)
                self.assertNotIn('private-test-password', json.dumps(result))
                argv = run.call_args.args[0]
                self.assertNotIn('private-test-password', ' '.join(argv))
                self.assertIn('StrictHostKeyChecking=yes', argv)
                self.assertEqual(argv[-1], 'true')
