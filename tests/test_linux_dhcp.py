import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from heist.backend.linux_dhcp import add_user_route, renew_entrypoint
from heist.backend.qemu_ga_wrapper import ExecResult


class LinuxDHCPTests(unittest.TestCase):
    def test_user_route_preserves_dmz_default_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dnsmasq.conf'
            path.write_text('no-resolv\ndhcp-option=tag:123,option:classless-static-route,0.0.0.0/0,10.128.0.1\n')
            add_user_route(path, 123, '10.8.0.2', '10.128.0.1')
            first = path.read_text()
            add_user_route(path, 123, '10.8.0.2', '10.128.0.1')
            self.assertEqual(path.read_text(), first)
            self.assertIn('0.0.0.0/0,10.128.0.1,10.8.0.2/32,10.128.0.1', first)
            self.assertEqual(first.count('classless-static-route'), 1)

    def test_invalid_route_never_changes_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dnsmasq.conf';path.write_text('no-resolv\n')
            with self.assertRaises(ValueError):
                add_user_route(path, 1, '10.8.0.2', 'bad;route')
            self.assertEqual(path.read_text(), 'no-resolv\n')

    def agent(self, correct=True):
        connection = SimpleNamespace(client_mac='02:00:00:00:00:01', network=SimpleNamespace(router_ip='10.128.0.1'))
        calls, polls = [], []
        def execute(argv, **kwargs):
            calls.append(argv)
            if argv == ['ip', '-j', 'link', 'show']:
                output = [{'ifname': 'entry0', 'address': connection.client_mac},
                          {'ifname': 'monitor0', 'address': '0a:01:00:00:00:01'}]
            elif argv[-1:] == ['NetworkManager']:
                return ExecResult(pid=1, exit_code=3)
            elif argv == ['ip', '-j', '-4', 'route', 'show']:
                polls.append(1)
                output = [] if len(polls) == 1 else [{'dst': '10.8.0.2', 'gateway': '10.128.0.1',
                                                     'dev': 'entry0' if correct else 'monitor0'}]
            else:
                return ExecResult(pid=1, exit_code=0)
            return ExecResult(pid=1, exit_code=0, stdout=json.dumps(output))
        return SimpleNamespace(exec=execute), connection, calls

    def test_networkd_refresh_waits_for_the_actual_return_route(self):
        ga, connection, calls = self.agent()
        sleep = Mock()
        renew_entrypoint(ga, connection, '10.8.0.2', sleep=sleep)
        self.assertIn(['networkctl', 'renew', 'entry0'], calls)
        self.assertFalse(any('monitor0' in call for call in calls))
        sleep.assert_called_once()

    def test_wrong_interface_cannot_satisfy_return_route_readiness(self):
        ga, connection, calls = self.agent(correct=False)
        with self.assertRaises(TimeoutError):
            renew_entrypoint(ga, connection, '10.8.0.2', timeout=1,
                             clock=Mock(side_effect=[0, 0, 1]), sleep=Mock())
