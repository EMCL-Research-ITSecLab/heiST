import json
import subprocess
import unittest
from unittest.mock import Mock

from heist.backend.monitoring_boot import restore


class MonitoringBootTests(unittest.TestCase):
    def test_boot_restores_exact_mac_after_interface_rename_and_waits_for_dad(self):
        address = 'fd12:3456:789a:1::1234'
        config = {'mac': '0a:01:00:00:12:34', 'address': address, 'gateway': 'fd12:3456:789a:1::1'}
        states = iter([True, False])
        commands = []

        def run(argv, **kwargs):
            commands.append(argv)
            if argv == ['ip', '-j', 'link', 'show']:
                return json.dumps([{'ifname': 'ens18', 'address': '0a:01:00:00:00:01'},
                                   {'ifname': 'renamed0', 'address': config['mac']}])
            if argv[:5] == ['ip', '-j', '-6', 'addr', 'show']:
                return json.dumps([{'addr_info': [{'family': 'inet6', 'local': address,
                                                    'tentative': next(states)}]}])
            return ''

        sleep = Mock()
        self.assertEqual(restore(config, run=run, sleep=sleep, find=lambda name: None), 'renamed0')
        self.assertEqual(commands[-1], ['ip', '-6', 'route', 'replace', 'default', 'via', config['gateway'], 'dev', 'renamed0'])
        self.assertFalse(any('ens18' in command for command in commands))
        sleep.assert_called_once()

    def test_missing_link_fails_before_network_mutation(self):
        run = Mock(return_value='[]')
        with self.assertRaises(RuntimeError):
            restore({'mac': '0a:01:00:00:12:34', 'address': 'fd12::2', 'gateway': 'fd12::1'}, run=run)
        run.assert_called_once_with(['ip', '-j', 'link', 'show'], text=True)

    def test_network_manager_releases_only_exact_monitoring_link_before_address_assignment(self):
        config = {'mac': '0a:01:00:00:12:34', 'address': 'fd12::2', 'gateway': 'fd12::1'}
        commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            if argv == ['ip', '-j', 'link', 'show']:
                return json.dumps([{'ifname': 'data0', 'address': '02:00:00:00:00:01'},
                                   {'ifname': 'monitor0', 'address': config['mac']}])
            if argv[:5] == ['ip', '-j', '-6', 'addr', 'show']:
                return json.dumps([{'addr_info': [{'family': 'inet6', 'local': config['address']}]}])
            return 'active\n'
        restore(config, run=run, find=lambda name: '/usr/bin/nmcli')
        release = ['nmcli', 'device', 'set', 'monitor0', 'managed', 'no']
        self.assertLess(commands.index(release), commands.index(['ip', 'link', 'set', 'dev', 'monitor0', 'up']))
        self.assertFalse(any('data0' in command for command in commands))

    def test_network_manager_release_failure_prevents_address_mutation(self):
        config = {'mac': '0a:01:00:00:12:34', 'address': 'fd12::2', 'gateway': 'fd12::1'}
        commands = []
        def run(argv, **kwargs):
            commands.append(argv)
            if argv == ['ip', '-j', 'link', 'show']:
                return json.dumps([{'ifname': 'monitor0', 'address': config['mac']}])
            if argv[0] == 'nmcli':
                raise subprocess.CalledProcessError(1, argv)
            return 'active\n'
        with self.assertRaises(subprocess.CalledProcessError):
            restore(config, run=run, find=lambda name: '/usr/bin/nmcli')
        self.assertFalse(any(command[:3] == ['ip', 'link', 'set'] for command in commands))
