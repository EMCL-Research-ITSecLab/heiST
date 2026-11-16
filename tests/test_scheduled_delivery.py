"""Scheduled probes must execute real verification and preserve failed evidence."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.monitoring.scheduled_delivery import verify


class ScheduledDeliveryTests(unittest.TestCase):
    def test_success_removes_only_this_runs_sql_copy_and_keeps_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root/'previous.backup'
            previous.write_bytes(b'previous')
            def run(command, **kwargs):
                self.assertTrue(kwargs['check'])
                self.assertIn('--publish', command)
                output = Path(command[command.index('--output')+1])
                (output/'database-restore').mkdir(parents=True)
                (output/'database-restore/database.backup').write_bytes(b'secret')
                (output/'database.json').write_text('{}')
            output = verify(root, ['--host', 'fixture'], run=run)
            self.assertFalse((output/'database-restore/database.backup').exists())
            self.assertTrue((output/'database.json').is_file())
            self.assertEqual(previous.read_bytes(), b'previous')

    def test_failure_preserves_diagnostics_and_propagates_to_systemd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def run(command, **kwargs):
                output = Path(command[command.index('--output')+1])
                (output/'database-restore').mkdir(parents=True)
                (output/'database-restore/database.backup').write_bytes(b'diagnostic')
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                verify(root, ['--host', 'fixture'], run=run)
            self.assertEqual(len(list(root.glob('*/database-restore/database.backup'))), 1)

    def test_shared_directory_and_output_override_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for args in (['--output=/tmp/other'], ['--publish']):
                with self.assertRaises(ValueError):
                    verify(root, args)
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                verify(root, [])
