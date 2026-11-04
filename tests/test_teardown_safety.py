"""Failed physical cleanup cannot release database IDs or report completion."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.platform.challenges import teardown


class TeardownSafetyTests(unittest.TestCase):
    def setUp(self):
        self.challenge = SimpleNamespace(id=12, machines={1: SimpleNamespace(id=123)}, networks={})

    def test_any_failed_stage_prevents_database_reclamation(self):
        stages = ('fetch_machines', 'stop_machines', 'delete_machines', 'fetch_networks', 'stop_dnsmasq_instances',
                  'delete_iptables_rules', 'delete_network_devices', 'remove_challenge_from_wazuh', 'remove_database_entries')
        for failed in stages[:-1]:
            callbacks = {name: Mock() for name in stages}
            callbacks[failed].side_effect = RuntimeError('unconfirmed '+failed)
            with self.subTest(stage=failed), patch.object(teardown, 'db_connection_context', return_value=nullcontext(object())), \
                 patch.object(teardown, 'fetch_challenge', return_value=self.challenge), patch.multiple(teardown, **callbacks):
                with self.assertRaises(RuntimeError):
                    teardown._teardown_challenge(12)
            callbacks['remove_database_entries'].assert_not_called()

    def test_stop_and_delete_failures_propagate_without_forced_unlock(self):
        with patch.object(teardown, 'vm_exists_api_call', return_value=True), patch.object(teardown, 'stop_vm_api_call', side_effect=RuntimeError('locked task')):
            with self.assertRaises(RuntimeError):
                teardown.stop_machines(self.challenge)
        with patch.object(teardown, 'delete_vm_api_call', side_effect=TimeoutError('outcome unknown')):
            with self.assertRaises(TimeoutError):
                teardown.delete_machines(self.challenge)
        with patch.object(teardown, 'delete_wazuh_agent', return_value=False):
            with self.assertRaises(RuntimeError):
                teardown.remove_challenge_from_wazuh(self.challenge)

    def test_firewall_inspection_error_is_distinct_from_absence(self):
        with patch.object(teardown.subprocess, 'run', return_value=SimpleNamespace(returncode=4)), self.assertRaises(RuntimeError):
            teardown.remove_iptables_rule('filter', 'FORWARD', ['-i', 'vrt123', '-j', 'ACCEPT'])
        with patch.object(teardown.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            teardown.remove_iptables_rule('filter', 'FORWARD', ['-i', 'vrt123', '-j', 'ACCEPT'])
            self.assertEqual(run.call_count, 1)
        with patch.object(teardown.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            teardown.remove_iptables_rule('filter', 'FORWARD', ['-i', 'vrt123', '-j', 'ACCEPT'])
            self.assertEqual(run.call_count, 2)
            self.assertIn('-D', run.call_args.args[0])
            self.assertTrue(run.call_args.kwargs['check'])

    def test_bridge_timeout_and_inventory_failure_propagate(self):
        self.challenge.networks = {1: SimpleNamespace(host_device='vrt123')}
        with patch.object(teardown.os.path, 'exists', return_value=True), patch.object(teardown.time, 'monotonic', side_effect=[0, 31]):
            with self.assertRaises(TimeoutError):
                teardown.wait_for_network_devices_deletion(self.challenge)
        with patch.object(teardown, 'network_device_exists_api_call', side_effect=TimeoutError('unknown')), self.assertRaises(TimeoutError):
            teardown.delete_network_devices(self.challenge)
