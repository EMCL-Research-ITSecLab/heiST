"""Legacy cleanup gets explicit configuration; early recovery preserves warm VMs."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.rollout.controller import Transaction
from heist.rollout.pve import PVE


class LegacyRecoveryTests(unittest.TestCase):
    def test_teardown_child_receives_backend_configuration_before_importing_legacy_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.venv/bin').mkdir(parents=True)
            (root/'.venv/bin/python').symlink_to(sys.executable)
            (root/'backend').mkdir();(root/'backend/__init__.py').write_text('')
            (root/'backend/teardown_challenge.py').write_text('''import os,json
from pathlib import Path
assert os.environ['DB_HOST']=='192.0.2.2'
assert os.environ['DB_PASSWORD']=='configured-test-value'
assert 'HEIST_OPTIONAL_UNSET' not in os.environ
def teardown_challenge(identifier):
 with (Path(__file__).parent/'calls.jsonl').open('a') as stream:stream.write(json.dumps(identifier)+'\\n')
''')
            adapter=PVE.__new__(PVE);adapter.installation=root
            adapter.environment={'DB_HOST':'192.0.2.2','DB_PASSWORD':'configured-test-value','HEIST_OPTIONAL_UNSET':None}
            adapter.config=SimpleNamespace(timeout=10)
            with patch.dict('os.environ',{'DB_HOST':'incorrect-caller-host'}):
                adapter._teardown_ready([17,18])
            self.assertEqual([json.loads(line) for line in (root/'backend/calls.jsonl').read_text().splitlines()],[17,18])

    def test_recovery_before_checkpoint_preserves_ready_pool_and_original_service_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction=Transaction(Path(directory),{'checkpoint_ready':False,'committed':False})
            adapter=PVE.__new__(PVE);adapter.assert_idle=Mock();adapter.command=Mock()
            adapter._resume_writers(transaction)
            adapter.assert_idle.assert_called_once_with(allow_ready=True)
            adapter.command.assert_called_once_with(['systemctl','start','backend'],timeout=180)
            self.assertTrue(transaction.data['writers_may_have_resumed'])
            adapter._resume_writers(transaction)
            self.assertEqual(adapter.command.call_count,1)

    def test_completed_checkpoint_requires_idle_instances_and_runs_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            transaction=Transaction(Path(directory),{'checkpoint_ready':True,'committed':True})
            adapter=PVE.__new__(PVE);adapter.assert_idle=Mock();adapter.command=Mock()
            adapter._resume_writers(transaction)
            adapter.assert_idle.assert_called_once_with(allow_ready=False)
            adapter.command.assert_called_once_with(['systemctl','start','backend','cleanup'],timeout=180)
