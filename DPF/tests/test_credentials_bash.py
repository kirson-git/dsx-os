import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_credentials_checked import FAKE

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'credentials.sh'

class BashCredentialsTests(unittest.TestCase):
    def run_helper(self,p,secret,extra_env=None):
        (p/'kubectl').write_text(FAKE);(p/'kubectl').chmod(0o700)
        env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],CALLS=str(p/'calls'),PAYLOAD=str(p/'payload'))
        env.update(extra_env or {})
        return subprocess.run(['bash',str(SCRIPT),'--skip-check','--password-file',str(secret)],env=env,capture_output=True,text=True)

    def test_legacy_validated_file_redaction_and_private_cleanup(self):
        for fail in [False,True]:
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as temp:
                p=Path(temp); secret=p/'private';secret.write_text('synthetic-test-credential');secret.chmod(0o600)
                r=self.run_helper(p,secret,{'APPLY_FAIL':'1'} if fail else {})
                self.assertEqual(r.returncode,1 if fail else 0,r.stderr)
                public=r.stdout+r.stderr+(p/'calls').read_text()
                encoded=base64.b64encode(b'synthetic-test-credential').decode()
                self.assertNotIn('synthetic-test-credential',public);self.assertNotIn(encoded,public)
                self.assertIn(encoded,(p/'payload').read_text())

    def test_empty_public_and_newline_password_files_rejected(self):
        for content,mode in [('',0o600),('sample\n',0o600),('sample',0o644)]:
            with self.subTest(content=content,mode=mode),tempfile.TemporaryDirectory() as temp:
                p=Path(temp);secret=p/'private';secret.write_text(content);secret.chmod(mode)
                self.assertNotEqual(self.run_helper(p,secret).returncode,0)
                self.assertFalse((p/'calls').exists())

    def test_repository_temp_directory_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);secret=p/'private';secret.write_text('synthetic-test-credential');secret.chmod(0o600)
            alias=p/'repo-link';alias.symlink_to(ROOT.parent,target_is_directory=True)
            for root in [ROOT.parent,ROOT,alias]:
                with self.subTest(root=root):
                    self.assertNotEqual(self.run_helper(p,secret,{'TMPDIR':str(root)}).returncode,0)
                    self.assertFalse((p/'calls').exists())
