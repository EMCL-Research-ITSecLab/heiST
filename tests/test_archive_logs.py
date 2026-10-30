"""Remote logs are retained unless a complete verified copy permits explicit removal."""
import hashlib
from pathlib import Path
from stat import S_IFREG
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tools.maintenance.archive_logs import archive


class ArchiveTests(unittest.TestCase):
    def fixture(self, data=b'closed gzip archive'):
        entry = SimpleNamespace(filename='closed.log.gz', st_mode=S_IFREG | 0o600, st_size=len(data), st_mtime=1)
        sftp = MagicMock()
        sftp.listdir_attr.return_value = [entry]
        sftp.stat.return_value = entry
        sftp.get.side_effect = lambda remote, local: Path(local).write_bytes(data)
        ssh = MagicMock()
        ssh.open_sftp.return_value.__enter__.return_value = sftp
        return ssh, sftp

    def test_default_copy_preserves_remote_log(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.archive_logs.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
            archive(ssh, '/var/log/archives', directory)
            self.assertEqual((Path(directory)/'closed.log.gz').read_bytes(), b'closed gzip archive')
        sftp.remove.assert_not_called()

    def test_bad_checksum_never_removes_remote_even_when_requested(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.archive_logs.remote_digest', return_value='0'*64):
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                archive(ssh, '/var/log/archives', directory, remove_remote=True)
            self.assertEqual(list(Path(directory).iterdir()), [])
        sftp.remove.assert_not_called()

    def test_explicit_removal_occurs_after_verified_unchanged_copy(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.archive_logs.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
            archive(ssh, '/var/log/archives', directory, remove_remote=True)
        sftp.remove.assert_called_once_with('/var/log/archives/closed.log.gz')


if __name__ == '__main__':
    unittest.main()
