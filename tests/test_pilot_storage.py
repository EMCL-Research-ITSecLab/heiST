"""Scratch data and bulk backup disks must never alias or escape private paths."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nested_pilot import supplemental_storage, check_storage_capacity
from types import SimpleNamespace


class PilotStorageTests(unittest.TestCase):
    def test_sparse_disks_share_one_backing_filesystem_capacity_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            for name in ('disk.qcow2','data.qcow2'):(work/name).touch()
            with patch('nested_pilot.subprocess.check_output',return_value=json.dumps({'virtual-size':80*1024**3}).encode()), \
                    patch('nested_pilot.shutil.disk_usage',return_value=SimpleNamespace(free=150*1024**3)):
                with self.assertRaisesRegex(ValueError,'Insufficient backing storage'):
                    check_storage_capacity(work,{'attach_data_disk':True})

    def test_large_persistent_filesystem_accepts_sparse_disks_with_headroom(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);(work/'disk.qcow2').touch()
            with patch('nested_pilot.subprocess.check_output',return_value=b'{"virtual-size":85899345920}'), \
                    patch('nested_pilot.shutil.disk_usage',return_value=SimpleNamespace(free=200*1024**3)):
                check_storage_capacity(work,{})

    def test_unknown_virtual_capacity_is_not_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);(work/'disk.qcow2').touch()
            with patch('nested_pilot.subprocess.check_output',return_value=b'{}'):
                with self.assertRaisesRegex(ValueError,'virtual capacity'):check_storage_capacity(work,{})

    def test_data_and_external_backup_use_distinct_devices_and_serials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);work=root/'work';bulk=root/'bulk';work.mkdir(mode=0o700);bulk.mkdir(mode=0o700)
            for path in (work/'disk.qcow2',work/'data.qcow2',bulk/'backup.qcow2'):path.touch()
            with patch('nested_pilot.subprocess.check_output',return_value=b'{"format":"qcow2"}'):
                result=supplemental_storage(work,{'attach_data_disk':True,'attach_backup_disk':True,'backup_disk_path':str(bulk/'backup.qcow2')})
            self.assertIn('virtio-blk-pci,drive=heistbackup,serial=HEIST-ROLLOUT-BACKUP',result)
            self.assertIn('virtio-blk-pci,drive=heistdata,serial=HEIST-PLATFORM-DATA',result)
            self.assertTrue(any(str(bulk/'backup.qcow2') in value for value in result))

    def test_same_file_symlinks_and_backing_chains_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);(work/'disk.qcow2').touch()
            with self.assertRaisesRegex(ValueError,'distinct'):
                supplemental_storage(work,{'attach_backup_disk':True,'backup_disk_path':str(work/'disk.qcow2')})
            (work/'backup.qcow2').symlink_to(work/'disk.qcow2')
            with self.assertRaises(ValueError):supplemental_storage(work,{'attach_backup_disk':True})
            (work/'backup.qcow2').unlink();(work/'backup.qcow2').touch()
            with patch('nested_pilot.subprocess.check_output',return_value=b'{"format":"qcow2","backing-filename":"base"}'),self.assertRaisesRegex(ValueError,'standalone'):
                supplemental_storage(work,{'attach_backup_disk':True})

    def test_unsafe_paths_and_incorrect_attachment_types_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary)
            for value in ('relative.qcow2','/tmp/a,format=raw','/tmp/a\n','/tmp/../disk.qcow2',42):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    supplemental_storage(work,{'attach_backup_disk':True,'backup_disk_path':value})
            with self.assertRaises(ValueError):supplemental_storage(work,{'attach_data_disk':1})
            self.assertEqual(supplemental_storage(work,{}),[])
