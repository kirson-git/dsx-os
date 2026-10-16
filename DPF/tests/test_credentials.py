import contextlib
import io
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import credentials

class CredentialTests(unittest.TestCase):
    def test_secret_is_only_on_stdin_and_never_printed(self):
        sentinel='synthetic-test-credential'
        with patch.object(credentials.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as run,contextlib.redirect_stdout(io.StringIO()) as out:
            credentials.install(sentinel)
        args,kwargs=run.call_args
        self.assertNotIn(sentinel,' '.join(args[0]))
        self.assertEqual(json.loads(kwargs['input'])['stringData'],{'password':sentinel})
        self.assertNotIn(sentinel,out.getvalue())
        self.assertIn('--server-side',args[0])

    def test_failure_cannot_echo_server_payload(self):
        sentinel='synthetic-test-credential'
        with patch.object(credentials.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=sentinel,stderr=sentinel)),self.assertRaises(ValueError) as error:
            credentials.install(sentinel)
        self.assertNotIn(sentinel,str(error.exception))

    def test_empty_and_newline_passwords_are_rejected_without_writes(self):
        for value in ['', 'example\n', 'example\r']:
            with self.subTest(value=value),patch.object(credentials.subprocess,'run') as run,self.assertRaises(ValueError):
                credentials.install(value)
            run.assert_not_called()
