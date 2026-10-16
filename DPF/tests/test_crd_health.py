"""Exercise the external Argo CRD health rule with a real Lua interpreter."""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import external

KEY = 'resource.customizations.health.apiextensions.k8s.io_CustomResourceDefinition'
LUA = next((shutil.which(name) for name in ('lua', 'luajit', 'rpmlua') if shutil.which(name)), None)


class CRDHealthTests(unittest.TestCase):
    def test_external_values_include_startup_health_rule(self):
        cfg = yaml.safe_load((ROOT / 'site.yaml').read_text())
        platform, service = external.argo_values(cfg)
        self.assertIn(KEY, platform['configs']['cm'])
        source = yaml.safe_load((ROOT / 'values/external-argo.yaml').read_text())
        self.assertEqual(platform['configs']['cm'][KEY], source['configs']['cm'][KEY])
        self.assertNotIn(KEY, service['configs']['cm'])

    def test_documented_kubectl_operations_include_retry_and_sync_options(self):
        cfg = yaml.safe_load((ROOT / 'site.yaml').read_text())
        policy = external.application(cfg, 'dpf-platform', cfg['git']['path'])['spec']['syncPolicy']
        count = 0
        for path in ROOT.rglob('*.md'):
            for payload in re.findall(r"-p '(\{\"operation\":.*?\})'", path.read_text()):
                with self.subTest(path=str(path)):
                    operation = json.loads(payload)['operation']
                    self.assertEqual(operation['retry'], policy['retry'])
                    self.assertEqual(operation['sync']['syncOptions'], policy['syncOptions'])
                    self.assertFalse(operation['sync']['prune'])
                    count += 1
        self.assertGreater(count, 0)

    @unittest.skipUnless(LUA, 'Install lua, luajit or rpmlua to exercise health transitions')
    def test_crd_health_transitions(self):
        values = yaml.safe_load((ROOT / 'values/external-argo.yaml').read_text())
        rule = values['configs']['cm'][KEY]
        cases = [
            ('missing status', '{}', 'Progressing'),
            ('empty conditions', '{status={conditions={}}}', 'Progressing'),
            ('names accepted, not yet established', '{status={conditions={{type="NamesAccepted",status="True"}}}}', 'Progressing'),
            ('installing', '{status={conditions={{type="Established",status="False",reason="Installing"}}}}', 'Progressing'),
            ('established', '{status={conditions={{type="Established",status="True"}}}}', 'Healthy'),
            ('name conflict', '{status={conditions={{type="NamesAccepted",status="False",message="conflict"}}}}', 'Degraded'),
            ('invalid schema after establishment', '{status={conditions={{type="Established",status="True"},{type="NonStructuralSchema",status="True",message="invalid"}}}}', 'Degraded'),
            ('deleting', '{metadata={deletionTimestamp="2026-10-16T00:00:00Z"},status={conditions={{type="Established",status="True"}}}}', 'Progressing'),
            ('terminating', '{status={conditions={{type="Established",status="True"},{type="Terminating",status="True"}}}}', 'Progressing'),
        ]
        for name, obj, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                script = pathlib.Path(tmp) / 'check.lua'
                script.write_text('obj=' + obj + '\nlocal function health()\n' + rule + '\nend\nlocal hs=health()\nassert(hs.status==' + json.dumps(expected) + ', hs.status)\nassert(type(hs.message)=="string" and #hs.message>0)\n')
                result = subprocess.run([LUA, str(script)], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
