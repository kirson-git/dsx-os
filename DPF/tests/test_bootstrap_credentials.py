import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'bootstrap-credentials.sh'
FAKE = '''#!/usr/bin/env python3
import json,os,sys,pathlib
a=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(a)+'\\n')
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
    def test_redaction_cleanup_and_conflict_guard(self):
        for scenario in ['ok', 'conflict', 'failure']:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p/'kubectl').write_text(FAKE); (p/'kubectl').chmod(0o700)
                for name in ['bmc', 'idrac']:
                    (p/name).write_text('synthetic-' + name); (p/name).chmod(0o600)
                env = dict(os.environ, PATH=str(p)+':'+os.environ['PATH'], CALLS=str(p/'calls'), PAYLOADS=str(p/'payloads'))
                if scenario == 'conflict': env['CONFLICT'] = '1'
                if scenario == 'failure': env['FAIL'] = '1'
                result = subprocess.run(['bash', str(SCRIPT), '--bmc-password-file', str(p/'bmc'), '--idrac-password-file', str(p/'idrac')], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if scenario == 'ok' else 1, result.stderr)
                public = result.stdout + result.stderr + (p/'calls').read_text()
                self.assertNotIn('synthetic-bmc', public)
                self.assertNotIn('synthetic-idrac', public)
                calls = [json.loads(line) for line in (p/'calls').read_text().splitlines()]
                if scenario == 'conflict':
                    self.assertFalse(any(a[0] in ['apply', 'create'] for a in calls))
                else:
                    self.assertIn('synthetic-idrac', (p/'payloads').read_text())
                    for a in calls:
                        for arg in a:
                            if arg.startswith('--from-file='):
                                self.assertFalse(Path(arg.split('=', 2)[2]).exists())
