import os
import subprocess
import unittest
import uuid
from unittest.mock import Mock

from heist.backend.network_input import chain_name, install_network_input_filter, remove_network_input_filter


class NetworkInputTests(unittest.TestCase):
    def test_host_input_is_limited_to_dhcp_dns_and_neighbor_discovery(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1))
        install_network_input_filter('vrt0000011', '10.128.0.1', run=run)
        restores = [call for call in run.call_args_list if call.args[0][0].endswith('-restore')]
        self.assertEqual(len(restores), 2)
        ipv4, ipv6 = [call.kwargs['input'] for call in restores]
        self.assertIn('--sport 68 --dport 67 -j ACCEPT', ipv4)
        self.assertIn('-d 10.128.0.1/32 -p tcp --dport 53 -j ACCEPT', ipv4)
        self.assertNotIn('--dport 22', ipv4)
        self.assertIn('--hl-eq 255', ipv6)
        for call in restores:
            self.assertIn('--noflush', call.args[0])
            self.assertNotIn('FORWARD', call.kwargs['input'])
            self.assertIn('-j DROP', call.kwargs['input'])
            self.assertIn('-I INPUT 1 -i vrt0000011', call.kwargs['input'])

    def test_infrastructure_bridges_are_rejected_before_commands(self):
        run = Mock()
        for name in ('vmbr0', 'vrt_backend', 'vrtmon', 'vrt1;cmd'):
            with self.assertRaises(ValueError):
                install_network_input_filter(name, '10.128.0.1', run=run)
        run.assert_not_called()

    @unittest.skipUnless(os.getenv('HEIST_PRIVILEGED_TESTS') == '1', 'Explicit private-netns test opt-in required')
    def test_real_atomic_replace_and_cleanup_preserve_unrelated_policy(self):
        namespace = 'heist-fw-' + uuid.uuid4().hex[:10]
        subprocess.run(['ip', 'netns', 'add', namespace], check=True)
        def run(argv, **kwargs):
            return subprocess.run(['ip', 'netns', 'exec', namespace, *argv], **kwargs)
        try:
            for binary in ('iptables', 'ip6tables'):
                run([binary, '-A', 'INPUT', '-i', 'lo', '-j', 'ACCEPT'], check=True)
            install_network_input_filter('vrt0000011', '10.128.0.1', run=run)
            install_network_input_filter('vrt0000011', '10.128.1.1', run=run)
            chain = chain_name('vrt0000011')
            rules = run(['iptables', '-S', chain], capture_output=True, text=True, check=True).stdout
            self.assertIn('10.128.1.1/32', rules)
            self.assertNotIn('10.128.0.1/32', rules)
            before = run(['iptables', '-S'], capture_output=True, text=True, check=True).stdout
            install_network_input_filter('vrt0000011', '10.128.1.1', run=run)
            self.assertEqual(before, run(['iptables', '-S'], capture_output=True, text=True, check=True).stdout)
            remove_network_input_filter('vrt0000011', run=run)
            remove_network_input_filter('vrt0000011', run=run)
            for binary in ('iptables', 'ip6tables'):
                rules = run([binary, '-S'], capture_output=True, text=True, check=True).stdout
                self.assertIn('-A INPUT -i lo -j ACCEPT', rules)
                self.assertNotIn(chain, rules)
        finally:
            subprocess.run(['ip', 'netns', 'delete', namespace], check=True)
