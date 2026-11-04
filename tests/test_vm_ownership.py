"""A foreign VM at a stale numeric ID must never be stopped or deleted."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.infrastructure.proxmox import client


class VMOwnershipTests(unittest.TestCase):
    def test_foreign_marker_blocks_native_stop_and_delete(self):
        machine=SimpleNamespace(id=900000001)
        for action in (client.stop_vm_api_call,client.delete_vm_api_call):
            api=Mock(return_value={'data':{'description':'Unrelated administrator VM'}})
            with patch.object(client,'vm_exists_api_call',return_value=True),patch.object(client,'make_api_call',api),self.assertRaises(RuntimeError):
                action(machine)
            self.assertEqual([call.args[0] for call in api.call_args_list],['GET'])

    def test_marker_is_bound_to_the_exact_machine_or_template_id(self):
        machine=SimpleNamespace(id=123)
        for value in (client.ownership_tags(123),client.ownership_tags(123,'course-exercise')):
            with patch.object(client,'make_api_call',return_value={'data':{'tags':value}}):
                self.assertEqual(client.require_vm_ownership(machine)['tags'],value)
        for value in (client.ownership_tags(1230),None,client.ownership_tags(123)+';heist-vm-456'):
            with patch.object(client,'make_api_call',return_value={'data':{'tags':value}}),self.assertRaises(RuntimeError):
                client.require_vm_ownership(machine)
