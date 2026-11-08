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
    def test_legacy_template_capacity_comes_from_authenticated_storage_inventory(self):
        adapter=PVE.__new__(PVE);adapter.node='pve'
        adapter.configuration=Mock(return_value={'sata0':'local:123/base.qcow2'})
        adapter.request=Mock(return_value=[{'volid':'local:123/base.qcow2','size':10*1024**3}])
        value=adapter.template_configuration(SimpleNamespace(vmid=123))
        self.assertEqual(value['sata0'],'local:123/base.qcow2,size=10485760K')
        self.assertEqual(adapter.request.call_args.args,('GET','/nodes/pve/storage/local/content',{'vmid':123}))
        adapter.request.return_value=[]
        with self.assertRaisesRegex(RuntimeError,'virtual capacity'):
            adapter.template_configuration(SimpleNamespace(vmid=123))

    def test_foreign_template_uuid_is_refused_before_any_restore_or_service_change(self):
        from heist.rollout.template_checkpoint import identity
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'vm.vma.zst';archive.write_bytes(b'archive')
            saved={'template':'1','name':'template','smbios1':'uuid=5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6'}
            item={'path':str(archive),'bytes':7,'sha256':hashlib.sha256(b'archive').hexdigest()}
            roles=('web','database','monitoring')
            transaction=Transaction(root/'journal',{'snapshots':{role:item for role in (*roles,'template-123')},
                'template_catalogue':{'123':identity(saved)}})
            adapter=PVE.__new__(PVE);adapter.node='pve'
            adapter.config=SimpleNamespace(vms=[SimpleNamespace(role=role) for role in roles])
            adapter.tasks=Mock();adapter._host_guard=Mock();adapter.command=Mock()
            adapter.request=Mock(return_value=[{'vmid':123}]);adapter.is_running=Mock(return_value=False)
            adapter.configuration=Mock(return_value={**saved,'smbios1':'uuid=ac4f2ff8-8edc-4876-bff2-23b64874d29c'})
            with self.assertRaisesRegex(RuntimeError,'foreign template'):
                adapter.restore(transaction)
            adapter._host_guard.assert_not_called();adapter.command.assert_not_called();adapter.tasks.run.assert_not_called()

    def test_unfinished_runtime_adapter_is_refused_before_any_host_mutation(self):
        adapter=PVE.__new__(PVE)
        adapter.command=Mock();adapter.remote=Mock()
        with self.assertRaisesRegex(RuntimeError,'no maintenance was entered'):
            adapter.preflight(SimpleNamespace(schema=3))
        adapter.command.assert_not_called();adapter.remote.assert_not_called()

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


class TemplateExportSelectionTests(unittest.TestCase):
    def test_readonly_template_export_is_verified_without_starting_a_backup_worker(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            transaction=Transaction(root/'journal',{});transaction.path.mkdir()
            adapter=PVE.__new__(PVE);adapter.node='pilot';adapter.tasks=Mock()
            adapter.readonly_template_backups={'123':'5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6'}
            adapter._verify_archive=Mock()
            def export(identifier,expected,path):
                self.assertEqual(identifier,123)
                self.assertEqual(expected,adapter.readonly_template_backups['123'])
                self.assertEqual(transaction.data['readonly_template_exports']['123']['state'],'EXPORTING')
                path.write_bytes(b'synthetic archive')
                return {'file':path.name,'bytes':17}
            with patch('heist.maintenance.template_archive.create',side_effect=export):
                archive=adapter.checkpoint_vm(transaction,SimpleNamespace(vmid=123,role='template-123'),root)
            adapter.tasks.run.assert_not_called()
            adapter._verify_archive.assert_called_once_with(transaction,archive)
            self.assertEqual(transaction.data['readonly_template_exports']['123']['state'],'ARCHIVE_VERIFIED')

    def test_failed_validation_never_marks_the_export_verified(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);transaction=Transaction(root/'journal',{});transaction.path.mkdir()
            adapter=PVE.__new__(PVE);adapter.node='pilot';adapter.tasks=Mock()
            adapter.readonly_template_backups={'123':'5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6'}
            adapter._verify_archive=Mock(side_effect=RuntimeError('corrupt archive'))
            def export(identifier,expected,path):path.write_bytes(b'corrupt');return {'file':path.name}
            with patch('heist.maintenance.template_archive.create',side_effect=export),self.assertRaisesRegex(RuntimeError,'corrupt'):
                adapter.checkpoint_vm(transaction,SimpleNamespace(vmid=123,role='template-123'),root)
            adapter.tasks.run.assert_not_called()
            self.assertEqual(transaction.data['readonly_template_exports']['123']['state'],'EXPORTED_UNVERIFIED')

    def test_core_vm_cannot_be_sent_to_the_readonly_template_exporter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);transaction=Transaction(root/'journal',{});transaction.path.mkdir()
            adapter=PVE.__new__(PVE);adapter.readonly_template_backups={'123':'fixture'};adapter.tasks=Mock()
            with self.assertRaisesRegex(RuntimeError,'template identities'):
                adapter.checkpoint_vm(transaction,SimpleNamespace(vmid=123,role='web'),root)
            adapter.tasks.run.assert_not_called()
            self.assertEqual(transaction.data,{})
