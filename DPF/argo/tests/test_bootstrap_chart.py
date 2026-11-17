import json
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BootstrapChartTests(unittest.TestCase):
    def render(self, hosts):
        values = {'apiServerIP': '192.0.2.20', 'europeVIP': '192.0.2.200', 'asiaVIP': '192.0.2.203',
                  'vipInterface': 'eth0', 'bootstrap': {'hosts': hosts}}
        with tempfile.NamedTemporaryFile(mode='w') as f:
            yaml.safe_dump(values, f); f.flush()
            return subprocess.run(['helm', 'template', 'dpf-site', str(ROOT/'charts/site'), '-f', f.name], capture_output=True, text=True)

    def test_host_templates_use_secret_and_scoped_journal_permissions(self):
        hosts = [{'name': 'europe', 'dpuNode': 'dpu-node-example', 'idracIP': '192.0.2.1',
                  'serial': 'SERVICE1', 'managementNode': 'node1', 'verifyTLS': True}]
        result = self.render(hosts)
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = [o for o in yaml.safe_load_all(result.stdout) if o]
        templates = [o for o in objects if o['kind'] == 'ConfigMap' and 'pod-template' in o.get('data', {})]
        self.assertEqual(len(templates), 1)
        pod = yaml.safe_load(templates[0]['data']['pod-template'])
        self.assertEqual(pod['spec']['nodeName'], 'node1')
        self.assertEqual(pod['spec']['restartPolicy'], 'Never')
        self.assertIn('dpf-host-reboot-credentials', str(pod))
        role = next(o for o in objects if o['kind'] == 'Role' and o['metadata']['name'] == 'dpf-reboot-europe')
        self.assertEqual(role['rules'][0]['resourceNames'], ['dpu-node-example'])
        self.assertEqual(role['rules'][0]['verbs'], ['get', 'patch'])
        probes = [o for o in objects if o['kind'] == 'Job' and o['metadata']['name'].startswith('dpf-probe-')]
        self.assertEqual(len(probes), 1)
        self.assertIn('--probe', str(probes[0]))
        ready = next(o for o in objects if o['kind'] == 'Job' and o['metadata']['name'] == 'dpf-bootstrap-ready')
        script = ready['spec']['template']['spec']['containers'][0]['command'][-1]
        self.assertIn('operationalConditions', script)
        self.assertIn('OperationalReady', script)
        self.assertNotIn('--for=condition=Operational ', script)
        self.assertIn('app.kubernetes.io/name=hbn', script)

    def test_empty_hosts_does_not_install_reboot_resources(self):
        result = self.render([])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('dpf-reboot-', result.stdout)

    def test_duplicate_node_and_invalid_address_rejected(self):
        host = {'name': 'europe', 'dpuNode': 'node1', 'idracIP': '192.0.2.1',
                'serial': 'SERVICE1', 'managementNode': 'node1', 'verifyTLS': True}
        self.assertNotEqual(self.render([host, dict(host, name='asia')]).returncode, 0)
        self.assertNotEqual(self.render([dict(host, idracIP='https://untrusted/path')]).returncode, 0)
