"""Remote logs are retained unless a complete verified copy permits explicit removal."""
import hashlib
from pathlib import Path
from stat import S_IFREG
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tools.maintenance.replicate import archive


class ArchiveTests(unittest.TestCase):
    def fixture(self, data=b'closed gzip archive'):
        entry = SimpleNamespace(filename='closed.log.gz', st_mode=S_IFREG | 0o600, st_size=len(data), st_mtime=1)
        sftp = MagicMock()
        sftp.listdir_attr.return_value = [entry]
        sftp.lstat.return_value = entry
        sftp.get.side_effect = lambda remote, local: Path(local).write_bytes(data)
        ssh = MagicMock()
        ssh.open_sftp.return_value.__enter__.return_value = sftp
        return ssh, sftp

    def test_default_copy_preserves_remote_log(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
            archive(ssh, '/var/log/archives', directory)
            self.assertEqual((Path(directory)/'closed.log.gz').read_bytes(), b'closed gzip archive')
        sftp.remove.assert_not_called()

    def test_bad_checksum_never_removes_remote_even_when_requested(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value='0'*64):
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                archive(ssh, '/var/log/archives', directory, remove_remote=True)
            self.assertEqual(list(Path(directory).iterdir()), [])
        sftp.remove.assert_not_called()

    def test_explicit_removal_occurs_after_verified_unchanged_copy(self):
        ssh, sftp = self.fixture()
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
            archive(ssh, '/var/log/archives', directory, remove_remote=True)
        sftp.remove.assert_called_once_with('/var/log/archives/closed.log.gz')


if __name__ == '__main__':
    unittest.main()


class ArchiveServiceTests(unittest.TestCase):
    def config(self, destination):
        return {'schema': 1, 'source': 'web', 'host': 'web.example.invalid', 'user': 'log-reader',
                'remote_directory': '/var/log/closed', 'destination': str(destination),
                'remove_remote': False, 'minimum_free_bytes': 0}

    def test_failed_run_preserves_last_success_and_hides_exception_details(self):
        import json
        from tools.maintenance.replicate import run_configuration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'status.json').write_text(json.dumps({'source': 'web', 'last_success_at': '2026-10-30T10:00:00+00:00'}))
            connect = MagicMock(side_effect=RuntimeError('private-key-material'))
            with self.assertRaises(RuntimeError):
                run_configuration(self.config(root), 'identity', 'known_hosts', connect=connect)
            report = json.loads((root/'status.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['last_success_at'], '2026-10-30T10:00:00+00:00')
            self.assertNotIn('private-key-material', json.dumps(report))
            self.assertEqual((root/'status.json').stat().st_mode & 0o777, 0o600)

    def test_capacity_failure_never_opens_ssh(self):
        from tools.maintenance.replicate import run_configuration
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            config['minimum_free_bytes'] = 2**100
            connect = MagicMock()
            with self.assertRaises(OSError):
                run_configuration(config, 'identity', 'known_hosts', connect=connect)
            connect.assert_not_called()

    def test_concurrent_run_cannot_overwrite_receipt_or_connect(self):
        import fcntl
        from tools.maintenance.replicate import run_configuration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root/'.archive.lock').open('w') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                connect = MagicMock()
                with self.assertRaises(BlockingIOError):
                    run_configuration(self.config(root), 'identity', 'known_hosts', connect=connect)
                connect.assert_not_called()
                self.assertFalse((root/'status.json').exists())

    def test_untrusted_paths_and_unknown_configuration_fields_are_rejected(self):
        import json
        from tools.maintenance.replicate import load_configuration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for changes in ({'destination': '../outside'}, {'remote_directory': '/logs/../private'},
                            {'remove_remote': 'yes'}, {'minimum_free_bytes': True}, {'unknown': 1}):
                config = self.config(root)
                config.update(changes)
                path = root/'config.json'
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    load_configuration(path)

    def test_remote_file_changed_or_replaced_is_never_removed(self):
        for mode in ('changed', 'link'):
            ssh, sftp = ArchiveTests().fixture()
            entry = sftp.lstat.return_value
            sftp.lstat.return_value = SimpleNamespace(st_size=entry.st_size + (mode == 'changed'), st_mtime=entry.st_mtime,
                                                     st_mode=0o120777 if mode == 'link' else entry.st_mode)
            with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
                with self.assertRaises(RuntimeError):
                    archive(ssh, '/logs', directory, remove_remote=True)
                self.assertFalse((Path(directory)/'closed.log.gz').exists())
            sftp.remove.assert_not_called()

    def test_successful_service_run_records_verified_counts_and_timestamp(self):
        from tools.maintenance.replicate import run_configuration
        ssh, sftp = ArchiveTests().fixture()
        ssh.__enter__.return_value = ssh
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.remote_digest', return_value=hashlib.sha256(b'closed gzip archive').hexdigest()):
            result = run_configuration(self.config(Path(directory)), 'identity', 'known_hosts', connect=lambda: ssh,
                                       clock=lambda: '2026-10-30T10:00:00+00:00')
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['counters']['verified'], 1)
            self.assertEqual(result['counters']['copied'], 1)
            self.assertEqual(result['last_success_at'], result['completed_at'])
        sftp.remove.assert_not_called()

    def test_remote_digest_quotes_paths_and_rejects_command_failure(self):
        from tools.maintenance.replicate import remote_digest
        ssh = MagicMock()
        output = MagicMock()
        output.read.return_value = (hashlib.sha256(b'closed').hexdigest()+'  file\n').encode()
        output.channel.recv_exit_status.return_value = 0
        ssh.exec_command.return_value = (None, output, None)
        self.assertEqual(remote_digest(ssh, '/logs/a; shell.gz'), hashlib.sha256(b'closed').hexdigest())
        self.assertIn("'/logs/a; shell.gz'", ssh.exec_command.call_args.args[0])
        output.channel.recv_exit_status.return_value = 1
        with self.assertRaises(RuntimeError):
            remote_digest(ssh, '/logs/file.gz')

    def test_dated_directories_are_traversed_but_links_are_not(self):
        from stat import S_IFDIR, S_IFLNK
        from tools.maintenance.replicate import archive_tree
        ssh, sftp = ArchiveTests().fixture()
        sftp.listdir_attr.side_effect = lambda path: [
            SimpleNamespace(filename='2026-11-10', st_mode=S_IFDIR),
            SimpleNamespace(filename='outside', st_mode=S_IFLNK),
        ] if path == '/logs' else []
        counts = dict(copied=1, verified=1, bytes=10, removed_remote=0)
        with tempfile.TemporaryDirectory() as directory, patch('tools.maintenance.replicate.archive', return_value=counts) as copy:
            result = archive_tree(ssh, '/logs', directory)
        self.assertEqual([call.args[1] for call in copy.call_args_list], ['/logs', '/logs/2026-11-10'])
        self.assertEqual(result['verified'], 2)

    def test_public_receipt_contains_no_credentials_and_private_receipt_stays_private(self):
        import json
        from tools.maintenance.replicate import run_configuration
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root/'private'
            private.mkdir(mode=0o700)
            public = root/'status.json'
            config = self.config(private)
            config['public_status'] = str(public)
            with self.assertRaises(RuntimeError):
                run_configuration(config, 'identity', 'known_hosts', connect=MagicMock(side_effect=RuntimeError('private-key-material')))
            self.assertEqual(json.loads(public.read_text())['status'], 'failed')
            self.assertNotIn('private-key-material', public.read_text())
            self.assertEqual(public.stat().st_mode & 0o777, 0o644)
            self.assertEqual((private/'status.json').stat().st_mode & 0o777, 0o600)
