import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'credentials.sh'
FAKE='''#!/usr/bin/env python3
import sys,pathlib,json,os
args=sys.argv[1:]
with open(os.environ['DSX_TEST_CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[:3]==['create','secret','generic']:
 source=next(x.split('=',2)[2] for x in args if x.startswith('--from-file=password='))
 print(json.dumps({'kind':'Secret','stringData':{'password':pathlib.Path(source).read_text()}}))
elif args[0]=='apply':
 payload=sys.stdin.read();pathlib.Path(os.environ['DSX_TEST_PAYLOAD']).write_text(payload)
 if os.environ.get('DSX_TEST_FAIL'):
  print(payload,file=sys.stderr);sys.exit(1)
 print('secret saved')
else:sys.exit(2)
'''

class BashCredentialsTests(unittest.TestCase):
    def test_password_stays_out_of_arguments_and_output(self):
        self.assertTrue(SCRIPT.exists(),'Bash credential helper required')
        for fail in [False,True]:
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as tmp:
                p=pathlib.Path(tmp);(p/'kubectl').write_text(FAKE);(p/'kubectl').chmod(0o700)
                secret=p/'private';secret.write_text('synthetic-test-credential');secret.chmod(0o600)
                env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],DSX_TEST_CALLS=str(p/'calls'),DSX_TEST_PAYLOAD=str(p/'payload'))
                if fail:env['DSX_TEST_FAIL']='1'
                result=subprocess.run(['bash',str(SCRIPT),'--password-file',str(secret)],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,1 if fail else 0,result.stderr)
                self.assertNotIn('synthetic-test-credential',result.stdout+result.stderr+(p/'calls').read_text())
                self.assertIn('synthetic-test-credential',(p/'payload').read_text())
                self.assertIn('--server-side',(p/'calls').read_text())
                import json
                create_args=json.loads((p/'calls').read_text().splitlines()[0])
                temporary=next(a.split('=',2)[2] for a in create_args if a.startswith('--from-file=password='))
                self.assertFalse(pathlib.Path(temporary).parent.exists(),'Private temporary directory must be removed')

    def test_empty_or_public_file_is_rejected_before_kubectl(self):
        self.assertTrue(SCRIPT.exists(),'Bash credential helper required')
        for content,mode in [('',0o600),('sample\n',0o600),('sample',0o644)]:
            with self.subTest(content=content,mode=mode),tempfile.TemporaryDirectory() as tmp:
                p=pathlib.Path(tmp);secret=p/'private';secret.write_text(content);secret.chmod(mode)
                (p/'kubectl').write_text(FAKE);(p/'kubectl').chmod(0o700)
                env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],DSX_TEST_CALLS=str(p/'calls'),DSX_TEST_PAYLOAD=str(p/'payload'))
                result=subprocess.run(['bash',str(SCRIPT),'--password-file',str(secret)],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse((p/'calls').exists())

    def test_repository_temp_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)
            secret=p/'private';secret.write_text('synthetic-test-credential');secret.chmod(0o600)
            (p/'kubectl').write_text(FAKE);(p/'kubectl').chmod(0o700)
            alias=p/'repo-link';alias.symlink_to(ROOT.parent,target_is_directory=True)
            for temp_root in [ROOT.parent,ROOT,alias]:
                with self.subTest(temp_root=temp_root):
                    env=dict(os.environ,TMPDIR=str(temp_root),PATH=str(p)+':'+os.environ['PATH'],DSX_TEST_CALLS=str(p/'calls'),DSX_TEST_PAYLOAD=str(p/'payload'))
                    result=subprocess.run(['bash',str(SCRIPT),'--password-file',str(secret)],env=env,capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0)
                    self.assertFalse((p/'calls').exists())
