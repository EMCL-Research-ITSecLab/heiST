import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from backend.linux_monitoring import prepare_monitoring_network
from backend.qemu_ga_wrapper import ExecResult, GuestAgentError

ADDRESS = 'fd12:3456:789a:1::1234'
GATEWAY = 'fd12:3456:789a:1::1'


class LinuxMonitoringTests(unittest.TestCase):
    def agent(self, links=None, tentative=False):
        links = links if links is not None else [{'ifname': 'data0', 'address': '02:00:00:00:00:01'},
                                                {'ifname': 'mon0', 'address': '0a:01:00:00:00:01'}]
        def execute(argv, **kwargs):
            if argv == ['ip', '-j', 'link', 'show']:
                value = links
            elif argv[:4] == ['ip', '-j', '-6', 'addr']:
                value = [{'addr_info': [{'family': 'inet6', 'local': ADDRESS, 'tentative': tentative}]}]
            else:
                return ExecResult(pid=1, exit_code=0)
            return ExecResult(pid=1, exit_code=0, stdout=json.dumps(value))
        return Mock(exec=Mock(side_effect=execute))

    def test_dedicated_nic_is_enabled_before_usable_address_and_route(self):
        ga = self.agent()
        self.assertEqual(prepare_monitoring_network(ga, ADDRESS, GATEWAY), 'mon0')
        commands = [call.args[0] for call in ga.exec.call_args_list]
        self.assertEqual(commands[1], ['ip', 'link', 'set', 'dev', 'mon0', 'up'])
        self.assertIn('net/ipv6/conf/mon0/disable_ipv6=0', commands[2])
        self.assertEqual(commands[-1], ['ip', '-6', 'route', 'replace', 'default', 'via', GATEWAY, 'dev', 'mon0'])
        self.assertTrue(all(isinstance(command, list) for command in commands))
        self.assertFalse(any('data0' in command for command in commands[1:]))

    def test_missing_or_ambiguous_monitoring_nic_stops_configuration(self):
        for links in ([], [{'ifname': name, 'address': '0a:01:00:00:00:01'} for name in ('one', 'two')]):
            ga = self.agent(links=links)
            with self.assertRaisesRegex(RuntimeError, 'exactly one'):
                prepare_monitoring_network(ga, ADDRESS, GATEWAY)
            self.assertEqual(ga.exec.call_count, 1)

    def test_network_failure_is_never_ignored(self):
        ga = self.agent()
        original = ga.exec.side_effect
        ga.exec.side_effect = lambda argv, **kwargs: ExecResult(pid=1, exit_code=1) if argv[1:3] == ['link', 'set'] else original(argv, **kwargs)
        with self.assertRaisesRegex(RuntimeError, 'enable NIC'):
            prepare_monitoring_network(ga, ADDRESS, GATEWAY)
        self.assertEqual(ga.exec.call_count, 2)

    def test_tentative_address_cannot_be_treated_as_ready(self):
        ga = self.agent(tentative=True)
        with self.assertRaises(TimeoutError):
            prepare_monitoring_network(ga, ADDRESS, GATEWAY, timeout=1, clock=Mock(side_effect=[0, 1]), sleep=Mock())
        self.assertFalse(any(call.args[0][:3] == ['ip', '-6', 'route'] for call in ga.exec.call_args_list))

    def test_enrollment_secret_remains_a_literal_argument(self):
        source = Path(__file__).resolve().parents[1] / 'backend/warmup_challenge.py'
        function = next(node for node in ast.parse(source.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'configure_ipv6_and_wazuh_linux')
        ga = Mock()
        ga.exec.return_value = ExecResult(pid=1, exit_code=0, stdout='active\n')
        factory = Mock()
        factory.return_value.__enter__ = Mock(return_value=ga)
        factory.return_value.__exit__ = Mock(return_value=False)
        secret = 'literal $() ; password'
        scope = {'GuestAgent': factory, 'GuestAgentError': GuestAgentError,
                 'prepare_monitoring_network': Mock(), 'persist_monitoring_network': Mock(), 'time': Mock(),
                 'vmid_to_ipv6': lambda value: ADDRESS, 'WAZUH_ENROLLMENT_PASSWORD': secret,
                 'launch_timing_logger': Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
        machine = SimpleNamespace(id=123, challenge=SimpleNamespace(template=SimpleNamespace(id=4)))
        scope['configure_ipv6_and_wazuh_linux'](machine)
        enrollment = ga.exec.call_args_list[1].args[0]
        self.assertIsInstance(enrollment, list)
        self.assertIn('--password=' + secret, enrollment)
