"""Real UDP/TCP ownership checks in disposable local network namespaces."""
import os
import subprocess
import sys
import time
import unittest
import uuid

from heist.infrastructure.network.firewall import install_user_dns_filter, remove_user_dns_filter


@unittest.skipUnless(os.getenv('HEIST_PRIVILEGED_TESTS') == '1', 'Explicit private-netns test opt-in required')
class VpnDnsPacketTests(unittest.TestCase):
    def test_owner_dns_works_without_cross_user_or_host_access(self):
        token = uuid.uuid4().hex[:6]
        server, client = 'hdns-' + token, 'hcli-' + token
        for namespace in (server, client):
            subprocess.run(['ip', 'netns', 'add', namespace], check=True)
            self.addCleanup(subprocess.run, ['ip', 'netns', 'delete', namespace], check=True)

        def execute(namespace, argv, **kwargs):
            return subprocess.run(['ip', 'netns', 'exec', namespace, *argv], **kwargs)

        def firewall(argv, **kwargs):
            return execute(server, argv, **kwargs)

        left, right = 'hds' + token, 'hdc' + token
        subprocess.run(['ip', 'link', 'add', left, 'type', 'veth', 'peer', 'name', right], check=True)
        subprocess.run(['ip', 'link', 'set', left, 'netns', server], check=True)
        subprocess.run(['ip', 'link', 'set', right, 'netns', client], check=True)
        execute(server, ['ip', 'link', 'set', left, 'name', 'tun0'], check=True)
        for namespace, interface in ((server, 'tun0'), (client, right)):
            execute(namespace, ['ip', 'link', 'set', 'lo', 'up'], check=True)
            execute(namespace, ['ip', 'link', 'set', interface, 'up'], check=True)
        execute(server, ['ip', 'address', 'add', '10.64.0.1/24', 'dev', 'tun0'], check=True)
        for address in ('10.64.0.2/24', '10.64.0.3/24'):
            execute(client, ['ip', 'address', 'add', address, 'dev', right], check=True)
        for address in ('10.128.0.49/32', '10.128.0.65/32'):
            execute(server, ['ip', 'address', 'add', address, 'dev', 'lo'], check=True)
        execute(client, ['ip', 'route', 'add', '10.128.0.0/24', 'via', '10.64.0.1'], check=True)
        firewall(['iptables', '-A', 'INPUT', '-i', 'tun0', '-j', 'DROP'], check=True)
        daemon = subprocess.Popen(
            ['ip', 'netns', 'exec', server, 'dnsmasq', '--conf-file=/dev/null', '--no-daemon',
             '--user=root', '--group=root', '--no-hosts', '--no-resolv', '--bind-interfaces',
             '--listen-address=10.128.0.49,10.128.0.65',
             '--address=/portal.ldap.heist.test/10.128.0.58', '--pid-file='],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        def stop_daemon():
            daemon.terminate()
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
        self.addCleanup(stop_daemon)

        def query(address='10.64.0.2', resolver='10.128.0.49', tcp=False, namespace=client):
            argv = ['dig', '+time=1', '+tries=1', '+short', '-b', address, '@' + resolver,
                    'portal.ldap.heist.test', 'A']
            if tcp:
                argv.append('+tcp')
            return execute(namespace, argv, capture_output=True, text=True, timeout=5)

        deadline = time.monotonic() + 5
        while True:
            self.assertIsNone(daemon.poll(), 'Isolated DNS service failed to start')
            if query(address='10.128.0.49', namespace=server).returncode == 0:
                break
            if time.monotonic() >= deadline:
                self.fail('Isolated DNS service did not become ready')
            time.sleep(.05)
        self.assertNotEqual(query().returncode, 0, 'Reproduction requires the existing VPN drop')
        install_user_dns_filter('vrt0001741', '10.128.0.49', '10.64.0.2', run=firewall)
        for tcp in (False, True):
            answer = query(tcp=tcp)
            self.assertEqual(answer.returncode, 0, answer.stdout + answer.stderr)
            self.assertEqual(answer.stdout.strip(), '10.128.0.58')
        self.assertNotEqual(query(address='10.64.0.3').returncode, 0)
        self.assertNotEqual(query(resolver='10.128.0.65').returncode, 0)
        probe = execute(client, [sys.executable, '-c',
            "import socket,sys\ntry:\n socket.create_connection(('10.128.0.49',22),1)\n"
            "except TimeoutError:\n sys.exit(2)\nexcept OSError:\n sys.exit(3)\n"],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(probe.returncode, 2, 'Host management traffic must still be dropped')
        install_user_dns_filter('vrt0001741', '10.128.0.49', '10.64.0.3', run=firewall)
        self.assertNotEqual(query().returncode, 0, 'Reassignment must revoke the previous owner')
        self.assertEqual(query(address='10.64.0.3', tcp=True).returncode, 0)
        remove_user_dns_filter('vrt0001741', run=firewall)
        self.assertNotEqual(query(address='10.64.0.3').returncode, 0)
