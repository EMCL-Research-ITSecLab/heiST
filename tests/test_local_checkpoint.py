import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest import TestCase
from unittest.mock import patch
from nested_pilot import checkpoint


class CheckpointTests(TestCase):
    def test_running_socket_is_rejected_without_creating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)
            (work/'qmp.sock').touch()
            output=work/'checkpoint'
            with self.assertRaisesRegex(ValueError,'shutdown'):
                checkpoint(work,output)
            self.assertFalse(output.exists())

    def test_failed_content_comparison_cannot_create_valid_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'work';work.mkdir()
            output=work.parent/'checkpoint'
            with patch('nested_pilot.subprocess.check_output',return_value=b'{"format":"qcow2","virtual-size":1024}'), patch('nested_pilot.shutil.disk_usage',return_value=SimpleNamespace(free=2**40)), patch('nested_pilot.run',side_effect=[None,RuntimeError('different')]):
                with self.assertRaisesRegex(RuntimeError,'different'):
                    checkpoint(work,output)
            self.assertFalse((output/'checkpoint.json').exists())

    def test_real_checkpoint_restores_original_content_after_source_changes(self):
        import shutil
        import subprocess
        if not all(shutil.which(name) for name in ('qemu-img', 'qemu-io')):
            self.skipTest('qemu-utils required for real disk comparison')
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'work';work.mkdir()
            output=work.parent/'checkpoint'
            restored=work.parent/'restored'
            (work/'pilot.json').write_text('{"memory_mib":2048,"cpus":2}')
            subprocess.run(['qemu-img','create','-q','-f','qcow2',str(work/'disk.qcow2'),'8M'],check=True)
            subprocess.run(['qemu-io','-f','qcow2','-c','write -P 0x5a 0 4096',str(work/'disk.qcow2')],check=True,stdout=subprocess.DEVNULL)
            checkpoint(work,output)
            subprocess.run(['qemu-io','-f','qcow2','-c','write -P 0xa5 0 4096',str(work/'disk.qcow2')],check=True,stdout=subprocess.DEVNULL)
            checkpoint(output,restored)
            subprocess.run(['qemu-io','-f','qcow2','-c','read -P 0x5a 0 4096',str(restored/'disk.qcow2')],check=True,stdout=subprocess.DEVNULL)
            self.assertEqual((restored/'pilot.json').read_bytes(),(work/'pilot.json').read_bytes())
            self.assertEqual((restored/'disk.qcow2').stat().st_mode & 0o777,0o600)

    def test_attached_backup_volume_cannot_be_silently_omitted(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'work';work.mkdir()
            (work/'pilot.json').write_text('{"attach_backup_disk":true}')
            output=work.parent/'checkpoint'
            with self.assertRaisesRegex(ValueError,'attached backup disk'):
                checkpoint(work,output)
            self.assertFalse(output.exists())
