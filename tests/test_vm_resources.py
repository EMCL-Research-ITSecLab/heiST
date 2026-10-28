import json
import unittest
from unittest.mock import patch

from setup.vm_resources import vm_resources, enable_ova_storage


class VMResourcesTests(unittest.TestCase):
    def test_defaults_and_small_pilot(self):
        self.assertEqual(vm_resources({})['database'], {'memory': 32768, 'cores': 4})
        self.assertEqual(vm_resources({'DATABASE_VM_MEMORY': '4096', 'DATABASE_VM_CORES': '2'})['database'],
                         {'memory': 4096, 'cores': 2})

    def test_invalid_resources_fail_before_setup(self):
        for value in ('0', '-1', '1.5', 'abc', '', None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'positive integer'):
                vm_resources({'WEBSERVER_VM_MEMORY': value})

    @patch('setup.vm_resources.subprocess.run')
    @patch('setup.vm_resources.subprocess.check_output')
    def test_default_storage_preserves_existing_content_and_options(self, read, run):
        read.side_effect = [json.dumps({'content': 'images,rootdir'}).encode(),
                            json.dumps({'content': 'iso,backup,snippets', 'path': '/custom', 'shared': 1}).encode()]
        enable_ova_storage('local-lvm')
        run.assert_called_once_with(['pvesm', 'set', 'local', '--content', 'backup,import,iso,snippets'], check=True)

    @patch('setup.vm_resources.subprocess.run')
    @patch('setup.vm_resources.subprocess.check_output')
    def test_directory_storage_pilot(self, read, run):
        read.return_value = json.dumps({'content': 'iso,backup'}).encode()
        enable_ova_storage('local')
        run.assert_called_once_with(['pvesm', 'set', 'local', '--content', 'backup,images,import,iso'], check=True)

    @patch('setup.vm_resources.subprocess.run')
    @patch('setup.vm_resources.subprocess.check_output')
    def test_unsuitable_or_missing_storage_has_no_mutations(self, read, run):
        read.return_value = json.dumps({'content': 'backup'}).encode()
        with self.assertRaises(ValueError):
            enable_ova_storage('backup-only')
        run.assert_not_called()
        read.side_effect = OSError('storage does not exist')
        with self.assertRaises(OSError):
            enable_ova_storage('missing')
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
