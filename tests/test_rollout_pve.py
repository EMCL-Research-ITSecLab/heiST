"""Adapter invariants use real archive digests and isolated fake host boundaries."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from heist.rollout.controller import Transaction
from heist.rollout.manifest import Plan
from heist.rollout.pve import PVE


class RestoreIdentityTests(unittest.TestCase):
    def test_old_restore_and_newer_safety_recovery_have_distinct_task_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'archive.vma.zst'
            archive.write_bytes(b'archive fixture')
            plan = Plan(1, '/fixture', 'old', 'new', '0.2.0', 'manifest', 'sha', 'config', (), (), ())
            snapshots = {role: {'path': str(archive), 'bytes': archive.stat().st_size,
                               'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
                         for role in ('web', 'database', 'monitoring')}
            data = {'plan': plan.to_dict(), 'snapshots': snapshots, 'protected_hashes': {},
                    'host_services': {}, 'web_services': {}}
            older = Transaction(root/'older-checkpoint', dict(data))
            newer = Transaction(root/'safety-checkpoint', dict(data))
            newer.path.mkdir()
            adapter = PVE.__new__(PVE)
            adapter.node = 'pve'
            vms = [SimpleNamespace(role=role, vmid=1000+i) for i, role in enumerate(snapshots)]
            adapter.config = SimpleNamespace(vms=vms, vm=lambda role: next(v for v in vms if v.role==role))
            adapter.tasks = Mock()
            adapter._host_guard = Mock()
            adapter.command = Mock()
            adapter.is_running = Mock(return_value=False)
            adapter._checkout = Mock()
            adapter.start_vms = Mock()
            adapter.remote = Mock()
            adapter.restore(newer, checkpoint=older)
            old_keys = {call.args[1] for call in adapter.tasks.run.call_args_list}
            adapter.tasks.run.reset_mock()
            adapter.restore(newer)
            safety_keys = {call.args[1] for call in adapter.tasks.run.call_args_list}
            self.assertEqual(len(old_keys), 3)
            self.assertEqual(len(safety_keys), 3)
            self.assertFalse(old_keys & safety_keys)

    def test_corrupt_archive_refuses_before_any_vm_or_service_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'archive';archive.write_bytes(b'corrupt')
            snapshots = {role: {'path': str(archive), 'bytes': 7, 'sha256': 'incorrect'}
                         for role in ('web', 'database', 'monitoring')}
            transaction = Transaction(root/'journal', {'snapshots': snapshots})
            adapter = PVE.__new__(PVE)
            adapter.config = SimpleNamespace(vms=[SimpleNamespace(role=role) for role in snapshots])
            adapter.tasks = Mock()
            adapter._host_guard = Mock()
            adapter.command = Mock()
            with self.assertRaisesRegex(RuntimeError, 'checksum differs'):
                adapter.restore(transaction)
            adapter._host_guard.assert_not_called()
            adapter.command.assert_not_called()
            adapter.tasks.run.assert_not_called()

    def test_source_drift_is_rejected_before_reopening_service(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            adapter = PVE.__new__(PVE);adapter.installation = Path(directory)
            transaction = Transaction(Path(directory)/'state', {'plan': Plan(
                1, directory, 'old', 'new', '0.2.0', 'manifest', 'sha', 'config', (), (), ()).to_dict()})
            with patch('heist.rollout.pve.revision', return_value='wrong'):
                with self.assertRaisesRegex(RuntimeError, 'commit differs'):
                    adapter.verify_source(transaction, target=True)
            with patch('heist.rollout.pve.revision', return_value='new'), \
                 patch('heist.rollout.pve.git', return_value=b'backend/api.py\n'):
                with self.assertRaisesRegex(RuntimeError, 'source differs'):
                    adapter.verify_source(transaction, target=True)

    def test_checkout_does_not_treat_new_tracked_service_wrapper_as_old_generated_script(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);(root/'bin').mkdir()
            wrapper = root/'bin/api';wrapper.write_text('new maintained wrapper')
            adapter = PVE.__new__(PVE);adapter.installation = root;adapter.command = Mock()
            transaction = Transaction(root/'state', {'legacy_shims': {'bin/api': b'old generated'.hex()}})
            with patch('heist.rollout.pve.git', return_value=b'bin/api\0'):
                adapter._checkout(transaction, 'baseline')
            self.assertEqual(wrapper.read_text(), 'new maintained wrapper')
            adapter.command.assert_called_once()
