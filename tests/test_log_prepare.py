import gzip
from pathlib import Path
import tempfile
import unittest

from tools.maintenance.prepare_logs import prepare


class PrepareLogsTests(unittest.TestCase):
    def fixture(self, directory):
        path = Path(directory)/'eve_vpn.json-2026-11-09-1794181503'
        path.write_bytes(b'closed log\n'*1000)
        return path

    def test_verified_gzip_replaces_only_the_closed_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.fixture(directory)
            active = Path(directory)/'eve_vpn.json'
            active.write_bytes(b'active log')
            result = prepare(directory, minimum_free_bytes=0, minimum_age=0, is_open=lambda _: False)
            self.assertEqual(result['compressed'], 1)
            self.assertFalse(source.exists())
            with gzip.open(str(source)+'.gz', 'rb') as compressed:
                self.assertEqual(compressed.read(), b'closed log\n'*1000)
            self.assertEqual(active.read_bytes(), b'active log')

    def test_open_young_and_capacity_limited_files_remain_untouched(self):
        for options, key in [({'is_open': lambda _: True}, 'skipped_open'),
                             ({'is_open': lambda _: False, 'minimum_age': 10**12}, 'skipped_young'),
                             ({'is_open': lambda _: False, 'minimum_age': 0, 'minimum_free_bytes': 2**100}, 'skipped_capacity')]:
            with tempfile.TemporaryDirectory() as directory:
                source = self.fixture(directory)
                self.assertEqual(prepare(directory, **options)[key], 1)
                self.assertTrue(source.exists())
                self.assertFalse(Path(str(source)+'.gz').exists())

    def test_changed_source_is_retained_and_no_gzip_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.fixture(directory)
            def changed(identity):
                if list(Path(directory).glob('.prepare-*')):
                    source.write_bytes(b'changed log')
                return False
            with self.assertRaises(RuntimeError):
                prepare(directory, minimum_age=0, minimum_free_bytes=0, is_open=changed)
            self.assertTrue(source.exists())
            self.assertFalse(Path(str(source)+'.gz').exists())

    def test_corrupt_existing_gzip_does_not_remove_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.fixture(directory)
            with gzip.open(str(source)+'.gz', 'wb') as compressed:
                compressed.write(b'wrong contents')
            with self.assertRaises(RuntimeError):
                prepare(directory, minimum_age=0, is_open=lambda _: False)
            self.assertTrue(source.exists())
