"""Hypervisor absence and deletion completion require positive evidence."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.infrastructure.proxmox import client
from heist.platform.images import delete_templates


class ResourceRemovalTests(unittest.TestCase):
    def setUp(self):
        self.vm = SimpleNamespace(id=123)

    def test_inventory_failure_or_malformed_response_never_means_vm_absence(self):
        with patch.object(client, 'make_api_call', side_effect=TimeoutError('API unavailable')):
            with self.assertRaises(TimeoutError):
                client.vm_exists_api_call(self.vm)
        for response in ({}, {'data': None}, {'data': [{'vmid': True}]}, {'data': ['unknown']}):
            with patch.object(client, 'make_api_call', return_value=response), self.assertRaises(RuntimeError):
                client.vm_exists_api_call(self.vm)
        with patch.object(client, 'make_api_call', return_value={'data': [{'vmid': 1234}]}):
            self.assertFalse(client.vm_exists_api_call(self.vm))
        with patch.object(client, 'make_api_call', return_value={'data': [{'vmid': 123}]}):
            self.assertTrue(client.vm_exists_api_call(self.vm))

    def test_delete_waits_for_success_and_confirms_absence_before_returning(self):
        events = []
        with patch.object(client, 'vm_exists_api_call', side_effect=[True, False]), \
             patch.object(client, 'make_api_call', side_effect=lambda *args: events.append('delete') or {'data': 'UPID:test'}), \
             patch.object(client, 'wait_for_task', side_effect=lambda *args, **kwargs: events.append('wait')):
            result = client.delete_vm_api_call(self.vm)
        self.assertEqual(events, ['delete', 'wait'])
        self.assertEqual(result, {'data': 'UPID:test'})
        with patch.object(client, 'vm_exists_api_call', return_value=False), patch.object(client, 'make_api_call') as call:
            self.assertTrue(client.delete_vm_api_call(self.vm)['already_absent'])
            call.assert_not_called()
        with patch.object(client, 'vm_exists_api_call', return_value=True), patch.object(client, 'make_api_call', return_value={'data': 'UPID:test'}), patch.object(client, 'wait_for_task'):
            with self.assertRaises(RuntimeError):
                client.delete_vm_api_call(self.vm)

    def test_failed_or_unknown_delete_does_not_force_unlock_or_retry(self):
        with patch.object(client, 'vm_exists_api_call', return_value=True), patch.object(client, 'make_api_call', return_value={'data': 'UPID:test'}) as call, \
             patch.object(client, 'wait_for_task', side_effect=TimeoutError('outcome unknown')):
            with self.assertRaises(TimeoutError):
                client.delete_vm_api_call(self.vm)
            self.assertEqual(call.call_count, 1)
        challenge = SimpleNamespace(machine_templates={123: self.vm})
        with patch.object(delete_templates, 'vm_exists_api_call', return_value=True), patch.object(delete_templates, 'vm_is_stopped_api_call', return_value=True), \
             patch.object(delete_templates, 'delete_vm_api_call', side_effect=RuntimeError('locked task')) as remove:
            with self.assertRaises(RuntimeError):
                delete_templates.delete_machine_template_vms(challenge)
            remove.assert_called_once_with(self.vm)

    def test_running_template_must_finish_clean_shutdown_before_deletion(self):
        challenge = SimpleNamespace(machine_templates={123: self.vm})
        events = []
        with patch.object(delete_templates, 'vm_exists_api_call', return_value=True), patch.object(delete_templates, 'vm_is_stopped_api_call', side_effect=[False, True]), \
             patch.object(delete_templates, 'shutdown_vm_api_call', side_effect=lambda vm: events.append('shutdown')), \
             patch.object(delete_templates, 'delete_vm_api_call', side_effect=lambda vm: events.append('delete')):
            delete_templates.delete_machine_template_vms(challenge)
        self.assertEqual(events, ['shutdown', 'delete'])
        with patch.object(delete_templates, 'vm_exists_api_call', return_value=True), patch.object(delete_templates, 'vm_is_stopped_api_call', return_value=False), \
             patch.object(delete_templates, 'shutdown_vm_api_call'), patch.object(delete_templates, 'delete_vm_api_call') as remove:
            with self.assertRaises(RuntimeError):
                delete_templates.delete_machine_template_vms(challenge)
            remove.assert_not_called()

    def test_stop_waits_for_task_and_confirmed_state_and_template_flag_has_correct_polarity(self):
        with patch.object(client, 'vm_is_stopped_api_call', side_effect=[False, True]), patch.object(client, 'make_api_call', return_value={'data': 'UPID:stop'}) as api, patch.object(client, 'wait_for_task') as wait:
            client.stop_vm_api_call(self.vm)
            self.assertEqual(api.call_args.args[0], 'POST')
            self.assertEqual(wait.call_args.kwargs['timeout'], 180)
        with patch.object(client, 'make_api_call', return_value={'data': {'template': 1}}):
            self.assertTrue(client.vm_is_template_api_call(self.vm))
        with patch.object(client, 'make_api_call', return_value={'data': {'template': 0}}):
            self.assertFalse(client.vm_is_template_api_call(self.vm))
        with patch.object(client, 'make_api_call', return_value={'data': {'status': 'unknown'}}), self.assertRaises(RuntimeError):
            client.vm_is_stopped_api_call(self.vm)

    def test_network_absence_and_reload_failures_are_not_silently_ignored(self):
        network = SimpleNamespace(host_device='vrt123')
        with patch.object(client, 'make_api_call', side_effect=TimeoutError('unavailable')), self.assertRaises(TimeoutError):
            client.network_device_exists_api_call(network)
        with patch.object(client, 'make_api_call', return_value={'data': [{'iface': 'vrt1234'}]}):
            self.assertFalse(client.network_device_exists_api_call(network))
        with patch.object(client, 'make_api_call', return_value={'data': [{'iface': 'vrt123'}]}):
            self.assertTrue(client.network_device_exists_api_call(network))
        with patch.object(client, 'operation_guard', return_value=nullcontext()), patch.object(client, 'make_api_call', return_value={'data': 'UPID:reload'}), \
             patch.object(client, 'wait_for_task', side_effect=TimeoutError('reload pending')):
            with self.assertRaises(TimeoutError):
                client.reload_network_api_call()
