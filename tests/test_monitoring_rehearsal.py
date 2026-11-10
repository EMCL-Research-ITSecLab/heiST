"""Rehearsal transport refuses non-fixture hosts and malformed canary identities."""
import json
import subprocess
import sys
import unittest

from tools.local.rehearse_monitoring import STAGE, QUERY


class MonitoringRehearsalTests(unittest.TestCase):
    def test_nonfixture_host_is_refused_before_any_runtime_write(self):
        program="import socket;socket.gethostname=lambda:'not-a-disposable-fixture'\n"+STAGE
        result=subprocess.run([sys.executable,'-c',program,'a'*40,'0'*64],input=b'not-a-runtime',capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Require the disposable pilot',result.stderr)
        self.assertEqual(result.stdout,b'')

    def test_invalid_canary_is_refused_before_reading_server_config_or_querying(self):
        value={'nonce':"bad'; SELECT *",'password':'fixture-private-password'}
        result=subprocess.run([sys.executable,'-c',QUERY],input=json.dumps(value).encode(),capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Invalid canary identity',result.stderr)
        self.assertNotIn(value['password'].encode(),result.stderr+result.stdout)
