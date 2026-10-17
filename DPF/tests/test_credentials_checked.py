import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'credentials.sh'
FAKE = '''#!/usr/bin/env python3
import json,os,pathlib,sys
a=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(a)+'\\n')
if 'config' in a: print('{"current-context":"test"}');sys.exit(0)
if 'exec' in a:
 targets=json.load(sys.stdin)
 print(json.dumps([{'name':t['name'],'ok':t['ip'] != os.environ.get('BAD_IP'), 'detail':'checked'} for t in targets]));sys.exit(0)
if 'create' in a and '-f' in a: sys.stdin.read();sys.exit(0)
if 'apply' in a:
 payload=sys.stdin.read();pathlib.Path(os.environ['PAYLOAD']).write_text(payload)
 if os.environ.get('APPLY_FAIL'): print(payload,file=sys.stderr);sys.exit(1)
 print('saved');sys.exit(0)
if 'get' in a or 'wait' in a or 'delete' in a:sys.exit(0)
sys.exit(2)
'''

class CheckedCredentialsTests(unittest.TestCase):
    def run_case(self, extra=(), bad_ip='', content='username=root\npassword=synthetic-secret\n', mode=0o600, apply_fail=False):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            (p/'kubectl').write_text(FAKE);(p/'kubectl').chmod(0o700)
            (p/'bmc').write_text(content);(p/'bmc').chmod(mode)
            (p/'dpu').write_text('username=ubuntu\npassword=synthetic-ssh-secret\n');(p/'dpu').chmod(0o600)
            (p/'known').write_text('192.0.2.3 ssh-ed25519 example-key\n')
            env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],CALLS=str(p/'calls'),PAYLOAD=str(p/'payload'),BAD_IP=bad_ip)
            if apply_fail:env['APPLY_FAIL']='1'
            extra=[str(p/'dpu') if x=='DPU_FILE' else str(p/'known') if x=='KNOWN_FILE' else x for x in extra]
            args=['bash',str(SCRIPT),'--bmc-pass',str(p/'bmc'),'--ip','192.0.2.1,192.0.2.2',*extra]
            result=subprocess.run(args,env=env,capture_output=True,text=True)
            calls=(p/'calls').read_text() if (p/'calls').exists() else ''
            payload=(p/'payload').read_text() if (p/'payload').exists() else ''
            self.assertNotIn('synthetic-secret', result.stdout+result.stderr+calls)
            self.assertNotIn('synthetic-ssh-secret', result.stdout+result.stderr+calls)
            return result,calls,payload

    def test_checks_every_bmc_before_secret_write(self):
        r,c,p=self.run_case()
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('192.0.2.1',r.stdout); self.assertIn('192.0.2.2',r.stdout)
        self.assertIn('c3ludGhldGljLXNlY3JldA==',p)
        calls=[json.loads(x) for x in c.splitlines()]
        self.assertLess(next(i for i,a in enumerate(calls) if 'exec' in a), next(i for i,a in enumerate(calls) if 'apply' in a))
        self.assertTrue(any('delete' in a and 'pod' in a for a in calls))

    def test_failed_bmc_never_updates_secret(self):
        r,c,p=self.run_case(bad_ip='192.0.2.2')
        self.assertNotEqual(r.returncode,0); self.assertEqual(p,''); self.assertIn('delete',c)

    def test_check_only_never_updates_secret(self):
        r,c,p=self.run_case(extra=['--check-only'])
        self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(p,'')

    def test_rejects_bad_inputs_without_cluster_calls(self):
        for kwargs in [{'content':'username=root\n'}, {'mode':0o644}, {'content':'username=root\npassword=x\npassword=y\n'}, {'extra':['--ip','192.0.2.1,']}, {'extra':['--ip','not-an-ip']}, {'extra':['--dpu-pass','missing']}]:
            with self.subTest(kwargs=kwargs):
                r,c,p=self.run_case(**kwargs)
                self.assertNotEqual(r.returncode,0);self.assertEqual(c,'')

    def test_apply_error_does_not_leak_secret(self):
        r,c,p=self.run_case(apply_fail=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('c3ludGhldGljLXNlY3JldA==',p)

    def test_optional_ssh_also_gates_secret_write(self):
        options=['--dpu-pass','DPU_FILE','--dpu-ip','192.0.2.3','--ssh-known-hosts','KNOWN_FILE']
        for fail in (False,True):
            with self.subTest(fail=fail):
                r,c,p=self.run_case(extra=options,bad_ip='192.0.2.3' if fail else '')
                self.assertEqual(r.returncode,1 if fail else 0,r.stderr)
                self.assertIn('DPU SSH 192.0.2.3',r.stdout)
                self.assertEqual(bool(p),not fail)
                self.assertNotIn('synthetic-ssh-secret',p)
