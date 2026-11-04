"""Uncertain creation or foreign VM identity cannot trigger destructive fallback."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from heist.platform.images import provision


class ImageProvisionTests(unittest.TestCase):
    def test_occupied_vm_is_refused_before_normalization_or_native_mutation(self):
        with patch.object(provision.client, 'vm_exists_api_call', return_value=True), patch.object(provision, 'normalize') as normalizer, patch.object(provision.subprocess, 'run') as native:
            with self.assertRaises(RuntimeError):
                provision.import_normalized('test.ova', 990002, 'local-lvm')
            normalizer.assert_not_called()
            native.assert_not_called()

    def test_ambiguous_create_preserves_native_state_and_never_unlocks_or_destroys(self):
        with patch.object(provision.client, 'vm_exists_api_call', return_value=False), patch.object(provision, 'normalize', return_value=(Path('/private'), {'disks': []})), patch.object(provision.client, 'make_api_call', side_effect=TimeoutError('lost response')), patch.object(provision.subprocess, 'run') as native:
            with self.assertRaises(TimeoutError):
                provision.import_normalized('test.ova', 990002, 'local-lvm')
            native.assert_not_called()

    def test_foreign_identity_blocks_disk_attachment_after_create_response(self):
        api = Mock(side_effect=[{'data': 'UPID:test'}, {'data': {'description': 'foreign VM'}}])
        with patch.object(provision.client, 'vm_exists_api_call', return_value=False), patch.object(provision, 'normalize', return_value=(Path('/private'), {'disks': [{'name': 'disk0.qcow2'}]})), patch.object(provision.client, 'make_api_call', api), patch.object(provision, 'wait_for_task'), patch.object(provision.subprocess, 'run') as native:
            with self.assertRaises(RuntimeError):
                provision.import_normalized('test.ova', 990002, 'local-lvm')
            native.assert_not_called()
        self.assertEqual([item.args[0] for item in api.call_args_list], ['POST','GET'])
