import os
import subprocess
import unittest
import uuid
from unittest.mock import Mock

from heist.infrastructure.network.firewall import (
    chain_name, install_network_input_filter, remove_network_input_filter,
    install_user_dns_filter, remove_user_dns_filter, user_dns_chain_name,
)


class NetworkInputTests(unittest.TestCase):
    def test_vpn_dns_permission_is_exact_owner_and_resolver_only(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1))
        install_user_dns_filter('vrt0001741', '10.128.0.49', '10.64.0.2', run=run)
        restores = [call for call in run.call_args_list if call.args[0][0].endswith('-restore')]
        self.assertEqual(len(restores), 1)
        call = restores[0]
        policy = call.kwargs['input']
        chain = user_dns_chain_name('vrt0001741')
        self.assertIn(f'-F {chain}', policy)
        self.assertIn(f'-I INPUT 1 -i tun0 -j {chain}', policy)
        for protocol in ('udp', 'tcp'):
            self.assertIn(f'-s 10.64.0.2/32 -d 10.128.0.49/32 -p {protocol} --dport 53 -j ACCEPT', policy)
        self.assertEqual(policy.count('-j ACCEPT'), 2)
        self.assertIn('-j RETURN', policy)
        self.assertIn('--noflush', call.args[0])
        self.assertNotIn('FORWARD', policy)
        self.assertNotIn('--dport 22', policy)
        self.assertNotIn('10.64.0.0/16', policy)

    def test_vpn_dns_invalid_bridge_or_addresses_fail_before_commands(self):
        run = Mock()
        for bridge, router, owner in (
            ('vmbr0', '10.128.0.49', '10.64.0.2'),
            ('vrt0001741', '10.128.0.49;cmd', '10.64.0.2'),
            ('vrt0001741', '10.128.0.49', '10.64.0.0/16'),
            ('vrt0001741', '10.128.0.49', '::1'),
        ):
            with self.subTest(bridge=bridge, router=router, owner=owner), self.assertRaises(ValueError):
                install_user_dns_filter(bridge, router, owner, run=run)
        run.assert_not_called()

    def test_vpn_dns_owned_chain_removal_is_idempotent(self):
        absent = Mock(return_value=subprocess.CompletedProcess([], 1))
        remove_user_dns_filter('vrt0001741', run=absent)
        self.assertEqual(absent.call_count, 1)
        present = Mock(return_value=subprocess.CompletedProcess([], 0))
        remove_user_dns_filter('vrt0001741', run=present)
        policy = present.call_args.kwargs['input']
        chain = user_dns_chain_name('vrt0001741')
        self.assertIn(f'-D INPUT -i tun0 -j {chain}', policy)
        self.assertIn(f'-X {chain}', policy)
        self.assertNotIn('-F INPUT', policy)

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
            install_user_dns_filter('vrt0000011', '10.128.0.1', '10.64.0.2', run=run)
            install_user_dns_filter('vrt0000011', '10.128.1.1', '10.64.0.3', run=run)
            dns_chain = user_dns_chain_name('vrt0000011')
            dns_rules = run(['iptables', '-S', dns_chain], capture_output=True, text=True, check=True).stdout
            self.assertIn('10.64.0.3/32', dns_rules)
            self.assertNotIn('10.64.0.2/32', dns_rules)
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
                self.assertNotIn(dns_chain, rules)
        finally:
            subprocess.run(['ip', 'netns', 'delete', namespace], check=True)
