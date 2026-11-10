"""Only complete, checksum-bound database generations may be published."""
import hashlib
import io
import json
from pathlib import Path
from stat import S_IFDIR, S_IFREG, S_IFLNK
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tools.maintenance.replicate import archive_database, load_configuration


class DatabaseReplicationTests(unittest.TestCase):
    generation = '20261110T014501Z-backup-23e9134e1c47'

    def fixture(self, body=b'PGDMPverified database'):
        metadata = {'schema': 1, 'database': 'heist', 'bytes': len(body),
                    'sha256': hashlib.sha256(body).hexdigest()}
        encoded = json.dumps(metadata).encode()
        ssh, sftp = MagicMock(), MagicMock()
        ssh.open_sftp.return_value.__enter__.return_value = sftp
        sftp.listdir_attr.return_value = [SimpleNamespace(filename=self.generation, st_mode=S_IFDIR)]
        sftp.lstat.side_effect = lambda path: SimpleNamespace(st_mode=S_IFREG, st_size=len(encoded) if path.endswith('.json') else len(body))
        sftp.open.side_effect = lambda *args: io.BytesIO(encoded)
        sftp.get.side_effect = lambda remote, local: Path(local).write_bytes(body)
        return ssh, sftp, metadata

    def test_verified_generation_is_atomic_and_repeatable_without_source_removal(self):
        ssh, sftp, metadata = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=metadata['sha256']):
            result = archive_database(ssh, '/backups', directory)
            self.assertEqual(result['copied'], 1)
            target = Path(directory)/self.generation
            self.assertEqual((target/'database.backup').read_bytes(), b'PGDMPverified database')
            self.assertEqual(json.loads((target/'metadata.json').read_text()), metadata)
            self.assertEqual(archive_database(ssh, '/backups', directory)['copied'], 0)
            self.assertEqual(sftp.get.call_count, 1)
            self.assertFalse(list(Path(directory).glob('.pending-*')))
        sftp.remove.assert_not_called()

    def test_corrupt_transfer_or_changed_source_never_publishes_a_generation(self):
        for corrupt in (True, False):
            ssh, sftp, metadata = self.fixture()
            if corrupt:
                sftp.get.side_effect = lambda remote, local: Path(local).write_bytes(b'PGDMPcorrupt')
            with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value='0'*64):
                with self.assertRaises(RuntimeError):
                    archive_database(ssh, '/backups', directory)
                self.assertFalse(list(Path(directory).iterdir()))
            sftp.remove.assert_not_called()

    def test_corrupt_existing_copy_cannot_be_reported_successful(self):
        ssh, sftp, metadata = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=metadata['sha256']):
            archive_database(ssh, '/backups', directory)
            (Path(directory)/self.generation/'database.backup').write_bytes(b'PGDMPcorrupt')
            with self.assertRaises(RuntimeError):
                archive_database(ssh, '/backups', directory)
        self.assertEqual(sftp.get.call_count, 1)

    def test_pending_directories_and_remote_symlinks_are_not_copied(self):
        ssh, sftp, _ = self.fixture()
        sftp.listdir_attr.return_value = [SimpleNamespace(filename='.pending-test', st_mode=S_IFDIR),
                                        SimpleNamespace(filename=self.generation, st_mode=S_IFLNK)]
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(archive_database(ssh, '/backups', directory)['verified'], 0)
        sftp.get.assert_not_called()

    def test_capacity_and_removal_guards_prevent_transfer(self):
        ssh, sftp, _ = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                archive_database(ssh, '/backups', directory, minimum_free_bytes=2**100)
            with self.assertRaises(ValueError):
                archive_database(ssh, '/backups', directory, remove_remote=True)
        sftp.get.assert_not_called()
