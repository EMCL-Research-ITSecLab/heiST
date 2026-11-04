"""Recovery validates all configuration bytes and paths before restoring any."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from heist.rollout.host_configuration import inspect_checkpoint, restore_files
from heist.files import sha256


class HostConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.configuration = self.root/'backend.env'
        self.configuration.write_bytes(b'checkpoint private configuration')
        self.archive = self.root/'checkpoint.tar.gz'
        self.expected = {str(self.configuration): sha256(self.configuration)}
        self.pack([(str(self.configuration).lstrip('/'), self.configuration.read_bytes())])

    def pack(self, members):
        with tarfile.open(self.archive, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in members:
                item = tarfile.TarInfo(name);item.size = len(data)
                archive.addfile(item, io.BytesIO(data))

    def inspect(self, **kwargs):
        return inspect_checkpoint(self.archive, self.expected, [self.configuration], **kwargs)

    def test_restore_replaces_changed_private_configuration_with_checkpoint_bytes(self):
        values = self.inspect(archive_sha256=sha256(self.archive))
        self.configuration.write_bytes(b'new rollout configuration')
        restore_files(values)
        self.assertEqual(self.configuration.read_bytes(), b'checkpoint private configuration')
        self.assertEqual(self.configuration.stat().st_mode & 0o777, 0o600)

    def test_incomplete_duplicate_unexpected_and_corrupt_archives_are_refused(self):
        name = str(self.configuration).lstrip('/')
        for members in ([], [(name, b'changed')], [(name, b'checkpoint private configuration')]*2,
                        [('../escape', b'private')], [('etc/shadow', b'private')]):
            self.pack(members)
            with self.subTest(members=members), self.assertRaises(RuntimeError):
                self.inspect()
        with self.assertRaisesRegex(RuntimeError, 'archive checksum'):
            self.inspect(archive_sha256='0'*64)
        with self.assertRaisesRegex(RuntimeError, 'undeclared'):
            inspect_checkpoint(self.archive, self.expected, [])

    def test_all_destinations_are_checked_before_any_file_is_replaced(self):
        target = self.root/'untouched';target.write_text('foreign')
        link = self.root/'link';link.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'Symlink'):
            restore_files({str(self.configuration): b'new data', str(link): b'private'})
        self.assertEqual(self.configuration.read_bytes(), b'checkpoint private configuration')
        self.assertEqual(target.read_text(), 'foreign')
        with self.assertRaisesRegex(RuntimeError, 'Proxmox manages'):
            restore_files({'/etc/pve/heist-fixture-do-not-write': b'new data'})
