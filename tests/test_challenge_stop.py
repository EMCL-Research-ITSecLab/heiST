"""Stopping one lab must preserve other users' firewall rules and fail closed."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from heist.platform.challenges import stop


class ChallengeFirewallTests(unittest.TestCase):
    def test_exact_host_rules_are_removed_without_substring_or_comment_matches(self):
        rules = '\n'.join(('-P INPUT ACCEPT', '-A FORWARD -s 10.64.0.2/32 -j ACCEPT',
                           '-A FORWARD -d 10.64.0.20/32 -j ACCEPT', '-A FORWARD -s 10.64.0.0/24 -j ACCEPT',
                           '-A INPUT -m comment --comment "10.64.0.2 -A keep" -j ACCEPT',
                           '-A FORWARD ! -s 10.64.0.2/32 -j DROP', '-A FORWARD -d 10.64.0.2/32 -j ACCEPT'))
        run = Mock(return_value=Mock(stdout=rules))
        with patch.object(stop.subprocess, 'run', run):
            stop.remove_user_iptables_rules('10.64.0.2')
        calls = [item.args[0] for item in run.call_args_list]
        self.assertEqual(calls, [['sudo', 'iptables', '-S'],
                               ['sudo', 'iptables', '-D', 'FORWARD', '-s', '10.64.0.2/32', '-j', 'ACCEPT'],
                               ['sudo', 'iptables', '-D', 'FORWARD', '-d', '10.64.0.2/32', '-j', 'ACCEPT']])
        self.assertTrue(all(item.kwargs['check'] and item.kwargs['timeout'] == 15 for item in run.call_args_list))

    def test_failed_listing_and_invalid_address_cannot_be_treated_as_success(self):
        run = Mock(side_effect=subprocess.CalledProcessError(1, ['iptables']))
        with patch.object(stop.subprocess, 'run', run), self.assertRaises(subprocess.CalledProcessError):
            stop.remove_user_iptables_rules('10.64.0.2')
        self.assertEqual(run.call_count, 1)
        run.reset_mock()
        with patch.object(stop.subprocess, 'run', run), self.assertRaises(ValueError):
            stop.remove_user_iptables_rules('10.64.0.2;shutdown')
        run.assert_not_called()
