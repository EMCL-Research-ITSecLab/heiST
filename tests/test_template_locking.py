import tempfile
from pathlib import Path
import unittest

from heist.infrastructure.locking import OperationBusy, operation_guard


class TemplateLockTests(unittest.TestCase):
    def test_concurrent_launch_readers_can_coexist_but_exclude_import_or_delete(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/'locks'
            with operation_guard(directory, 12, shared=True):
                with operation_guard(directory, 12, shared=True):
                    with self.assertRaises(OperationBusy):
                        with operation_guard(directory, 12):
                            self.fail('Deletion overlapped an active launch')
            with operation_guard(directory, 12):
                with self.assertRaises(OperationBusy):
                    with operation_guard(directory, 12, shared=True):
                        self.fail('Launch overlapped an import/delete operation')

    def test_same_exercise_conflicts_other_exercise_can_run_and_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/'locks'
            with operation_guard(directory, 12):
                with self.assertRaises(OperationBusy):
                    with operation_guard(directory, 12):
                        self.fail('Concurrent operation was accepted')
                with operation_guard(directory, 13):
                    pass
            with self.assertRaises(RuntimeError):
                with operation_guard(directory, 12):
                    raise RuntimeError('interrupted operation')
            with operation_guard(directory, 12):
                pass
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual((directory/'12.lock').stat().st_mode & 0o777, 0o600)

    def test_invalid_ids_and_symbolic_lock_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/'locks'
            for value in (True, 0, -1, '../lock', 2**63):
                with self.assertRaises(ValueError):
                    with operation_guard(directory, value):
                        pass
            directory.mkdir(mode=0o700)
            external = Path(root)/'external'
            external.write_text('preserve')
            (directory/'12.lock').symlink_to(external)
            with self.assertRaises(OSError):
                with operation_guard(directory, 12):
                    pass
            self.assertEqual(external.read_text(), 'preserve')
