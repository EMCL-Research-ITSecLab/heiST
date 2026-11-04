"""Recovery keeps original and newer image bytes without extracting guest disks."""
from pathlib import Path
import tempfile
import unittest

from heist.files import sha256
from heist.rollout.image_checkpoint import create, inspect, restore


class ImageCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.library=self.root/'library';self.library.mkdir()
        (self.library/'original.ova').write_bytes(b'opaque original bytes')
        (self.library/'.retired-7-image.ova').write_bytes(b'retired recovery bytes')
        self.checkpoint=create(self.library,self.root/'backup')

    def test_recovery_restores_exact_old_library_and_keeps_newer_bytes_for_safety_recovery(self):
        (self.library/'original.ova').write_bytes(b'newer replacement')
        (self.library/'new.ova').write_bytes(b'new image')
        newer=create(self.library,self.root/'newer-backup')
        quarantine=self.root/'quarantine'
        restore(self.checkpoint,self.library,quarantine)
        self.assertEqual((self.library/'original.ova').read_bytes(),b'opaque original bytes')
        self.assertFalse((self.library/'new.ova').exists())
        self.assertEqual({path.read_bytes() for path in quarantine.iterdir()},{b'newer replacement',b'new image'})
        restore(self.checkpoint,self.library,quarantine)
        restore(newer,self.library,self.root/'older-quarantine')
        self.assertEqual((self.library/'original.ova').read_bytes(),b'newer replacement')
        self.assertEqual((self.library/'new.ova').read_bytes(),b'new image')

    def test_corruption_unknown_files_and_destination_symlinks_refuse_before_library_changes(self):
        backup=Path(self.checkpoint['path'])
        (backup/'files/original.ova').write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):
            restore(self.checkpoint,self.library,self.root/'quarantine')
        self.assertEqual((self.library/'original.ova').read_bytes(),b'opaque original bytes')
        (self.library/'link.ova').symlink_to(self.root/'private')
        with self.assertRaises(RuntimeError):create(self.library,self.root/'second-backup')

    def test_manifest_tampering_missing_payload_and_wrong_library_are_refused(self):
        with self.assertRaises(RuntimeError):inspect(self.checkpoint,self.root/'other-library')
        (Path(self.checkpoint['path'])/'files/original.ova').unlink()
        with self.assertRaises(RuntimeError):inspect(self.checkpoint,self.library)
        (Path(self.checkpoint['path'])/'manifest.json').write_text('{}')
        with self.assertRaises(RuntimeError):inspect(self.checkpoint,self.library)
