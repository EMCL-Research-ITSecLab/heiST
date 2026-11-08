"""VM snapshots require stable ownership identity and complete disk coverage."""
import unittest
from heist.rollout.template_checkpoint import identity, require_same_vm, disk_capacity, require_backup_support


class TemplateCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.value={'template':'1','name':'exercise-template','smbios1':'uuid=5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6',
                    'sata0':'local:vm-123-disk-0,size=10G','tags':'course'}

    def test_stable_uuid_and_notes_are_recorded_without_changing_template_settings(self):
        before=dict(self.value)
        result=identity(self.value)
        self.assertEqual(disk_capacity(self.value),10*1024**3)
        require_same_vm(self.value,result)
        self.assertEqual(self.value,before)
        with self.assertRaisesRegex(RuntimeError,'foreign template'):
            require_same_vm({**self.value,'smbios1':'uuid=ac4f2ff8-8edc-4876-bff2-23b64874d29c'},result)

    def test_uncovered_disks_external_state_and_incomplete_imports_are_refused(self):
        for extra in ({'template':'0'},{'lock':'clone'},{'net30':'bridge=cloud'},
                      {'hostpci0':'0000:00:00.0'},{'unused0':'local:disk'},
                      {'sata0':'local:disk,size=10G,backup=0'},{'sata0':'local:disk,size=10G,shared=1'},
                      {'sata0':'/dev/foreign,size=10G'},{'sata0':'local:disk'},{'smbios1':''}):
            with self.subTest(extra=extra),self.assertRaises(RuntimeError):identity({**self.value,**extra})

    def test_production_template_backup_regression_is_refused_without_disk_changes(self):
        original=dict(self.value)
        for version in ('9.0.0','9.0.6','9.0.16','9.0.17','9.0.18~rc1','1:9.0.16'):
            with self.subTest(version=version),self.assertRaisesRegex(RuntimeError,'#6675'):
                require_backup_support([self.value],version)
        for version in ('8.4.4','9.0.18','9.0.18-1','9.2.15','1:9.0.18'):
            with self.subTest(version=version):require_backup_support([self.value],version)
        self.assertEqual(self.value,original)

    def test_scsi_and_empty_templates_are_unaffected_and_unknown_versions_fail_closed(self):
        require_backup_support([{'scsi0':'local:base,size=10G'}],'9.0.16')
        require_backup_support([{'ide2':'local:installer.iso,media=cdrom'}],'9.0.16')
        require_backup_support([],None)
        for version in (None,'','unknown','9.0.16\n','9.0.18; echo unsafe'):
            with self.subTest(version=version),self.assertRaisesRegex(RuntimeError,'confirm'):
                require_backup_support([self.value],version)
