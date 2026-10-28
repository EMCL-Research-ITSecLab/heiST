import subprocess
import unittest
from unittest.mock import Mock

from monitoring.monitor_host_firewall import CHAIN, install_host_input_filter


class FirewallModel:
    def __init__(self):
        self.chains = {(binary, 'INPUT'): [] for binary in ('iptables', 'ip6tables')}
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        binary, _, _, operation, chain, *rule = args
        key = binary, chain
        status = 0
        if operation == '-N':
            status = int(key in self.chains)
            self.chains.setdefault(key, [])
        elif operation == '-S':
            status = int(key not in self.chains)
        elif operation == '-C':
            status = int(rule not in self.chains.get(key, []))
        elif operation == '-A':
            self.chains[key].append(rule)
        elif operation == '-I':
            self.chains[key].insert(int(rule[0]) - 1, rule[1:])
        else:
            raise AssertionError('Unexpected global firewall mutation')
        if status and kwargs.get('check'):
            raise subprocess.CalledProcessError(status, args)
        return subprocess.CompletedProcess(args, status)


class MonitorHostFirewallTests(unittest.TestCase):
    def test_both_families_deny_host_services_without_changing_forwarding(self):
        model = FirewallModel()
        install_host_input_filter('vrtmon', run=model)
        for binary in ('iptables', 'ip6tables'):
            self.assertEqual(model.chains[binary, 'INPUT'][0], ['-i', 'vrtmon', '-j', CHAIN])
            rules = model.chains[binary, CHAIN]
            self.assertEqual(rules[-1], ['-j', 'DROP'])
            self.assertFalse(any('tcp' in rule or 'udp' in rule for rule in rules))
            for rule in rules[:-1]:
                self.assertEqual(binary, 'ip6tables')
                self.assertIn('255', rule)
                self.assertTrue('neighbor-solicitation' in rule or 'neighbor-advertisement' in rule)
        self.assertFalse(any('FORWARD' in call or '-F' in call or '-P' in call for call in model.calls))

    def test_repeated_bridge_up_is_idempotent(self):
        model = FirewallModel()
        install_host_input_filter('vrtmon', run=model)
        original = {key: list(value) for key, value in model.chains.items()}
        install_host_input_filter('vrtmon', run=model)
        self.assertEqual(model.chains, original)

    def test_rule_inspection_failure_is_not_ignored(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 2))
        with self.assertRaises(RuntimeError):
            install_host_input_filter('vrtmon', run=run)

    def test_invalid_bridge_is_rejected_before_running_commands(self):
        run = Mock()
        for name in ('', '-bad', 'vrtmon;true', 'a' * 16):
            with self.assertRaises(ValueError):
                install_host_input_filter(name, run=run)
        run.assert_not_called()
