import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'bootstrap-credentials.sh'
FAKE = '''#!/usr/bin/env python3
import json,os,sys,pathlib
a=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(a)+'\\n')
a=[x for x in a if not x.startswith('--request-timeout=')]
if a[:2]==['config','current-context']:print('test-cluster');sys.exit(0)
if 'config' in a and 'view' in a:print('{"current-context":"test-cluster"}');sys.exit(0)
if 'wait' in a:sys.exit(0)
if 'exec' in a:
 targets=json.load(sys.stdin)
 print(json.dumps([{'name':t['name'],'ok':not bool(os.environ.get('PREFLIGHT_FAIL')),'detail':'authentication result'} for t in targets]));sys.exit(0)
if a[:2]==['delete','namespace']:sys.exit(0)
if a[:2]==['create','-f']:sys.stdin.read();sys.exit(0)
if a[:3]==['get','crd','applications.argoproj.io']:sys.exit(0)
if 'get' in a and 'applications' in a:
 if os.environ.get('CONFLICT'): print('application.argoproj.io/dpf-site')
 sys.exit(0)
if a[:2]==['create','namespace']:
 print('{}');sys.exit(0)
if a[:3]==['create','secret','generic']:
 data={}
 for x in a:
  if x.startswith('--from-file='):
   k,p=x[len('--from-file='):].split('=',1);data[k]=pathlib.Path(p).read_text()
 print(json.dumps({'kind':'Secret','name':a[3],'stringData':data}));sys.exit(0)
if a[0]=='apply':
 data=sys.stdin.read()
 with open(os.environ['PAYLOADS'],'a') as f:f.write(data+'\\n')
 if os.environ.get('FAIL') and 'dpf-host-reboot-credentials' in data:
  print(data,file=sys.stderr);sys.exit(1)
 print('saved');sys.exit(0)
sys.exit(2)
'''


class CredentialsTests(unittest.TestCase):
    def config(self, path):
        import sys
        sys.path.insert(0, str(SCRIPT.parent/'tools'))
        from installer import SOURCE_PATHS
        sources = [{'path': p, 'repoURL': 'https://github.com/kirson-git/dsx-os.git',
                    'targetRevision': 'a'*40} for p in SOURCE_PATHS]
        sources[1]['helm'] = {'valuesObject': {'bootstrap': {'hosts': [
            {'name': 'europe', 'dpuNode': 'dpu1', 'managementNode': 'worker1',
             'idracIP': '192.0.2.1', 'serial': 'HOST1', 'verifyTLS': True}]}}}
        sources[3]['kustomize'] = {'patches': [{'target': {'kind': 'DPUDevice'}, 'patch': yaml.safe_dump([
            {'op': 'replace', 'path': '/spec', 'value': {'bmcIp': '192.0.2.2', 'serialNumber': 'DPU1'}},
            {'op': 'add', 'path': '/metadata/labels', 'value': {'provisioning.dpu.nvidia.com/dpunode-name': 'dpu1'}}])}]}
        path.write_text(yaml.safe_dump({'kind':'Application', 'metadata':{'name':'dpf','namespace':'argocd'},
            'spec':{'destination':{'name':'in-cluster','namespace':'dpf-operator-system'}, 'sources':sources,
                    'syncPolicy':{'syncOptions':['FailOnSharedResource=true']}}}))

    def test_redaction_cleanup_and_conflict_guard(self):
        for scenario in ['ok', 'conflict', 'failure', 'bad-password', 'check-only']:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p/'calls').touch()
                (p/'kubectl').write_text(FAKE); (p/'kubectl').chmod(0o700)
                for name in ['bmc', 'idrac']:
                    (p/name).write_text('synthetic-' + name); (p/name).chmod(0o600)
                self.config(p/'config.yaml')
                env = dict(os.environ, PATH=str(p)+':'+os.environ['PATH'], CALLS=str(p/'calls'), PAYLOADS=str(p/'payloads'))
                if scenario in ('conflict', 'check-only'): env['CONFLICT'] = '1'
                if scenario == 'failure': env['FAIL'] = '1'
                if scenario == 'bad-password': env['PREFLIGHT_FAIL'] = '1'
                extra = ['--check-only'] if scenario == 'check-only' else []
                result = subprocess.run(['bash', str(SCRIPT), '--config', str(p/'config.yaml'), '--bmc-password-file', str(p/'bmc'), '--idrac-password-file', str(p/'idrac'), *extra], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if scenario in ('ok', 'check-only') else 1, result.stderr)
                public = result.stdout + result.stderr + (p/'calls').read_text()
                self.assertNotIn('synthetic-bmc', public)
                self.assertNotIn('synthetic-idrac', public)
                calls = [json.loads(line) for line in (p/'calls').read_text().splitlines()]
                if scenario == 'conflict':
                    self.assertFalse(any(a[0] in ['apply', 'create'] for a in calls))
                elif scenario in ('bad-password', 'check-only'):
                    self.assertFalse(any('secret' in a for a in calls))
                    self.assertTrue(any('delete' in a and 'namespace' in a for a in calls))
                else:
                    self.assertIn('synthetic-idrac', (p/'payloads').read_text())
                    for a in calls:
                        for arg in a:
                            if arg.startswith('--from-file='):
                                self.assertFalse(Path(arg.split('=', 2)[2]).exists())
