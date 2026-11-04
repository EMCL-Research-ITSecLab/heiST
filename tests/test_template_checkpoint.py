"""VM snapshots require stable ownership identity and complete disk coverage."""
import unittest
from heist.rollout.template_checkpoint import identity, require_same_vm, disk_capacity


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
