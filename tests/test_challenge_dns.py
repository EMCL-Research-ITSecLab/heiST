import getpass
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

from heist.backend.challenge_dns import connection_dns_servers, fallback_servers, hostname_records


class ChallengeDNSTests(unittest.TestCase):
    def test_dns_is_scoped_to_the_current_connection_and_role(self):
        connection = SimpleNamespace(client_ip='10.128.1.20', network=SimpleNamespace(router_ip='10.128.1.17'),
                                     machine=SimpleNamespace(template=SimpleNamespace(ad_role='none')))
        self.assertEqual(connection_dns_servers(connection, []), '10.128.1.17')
        connection.machine.template.ad_role = 'dc'
        self.assertEqual(connection_dns_servers(connection, []), '10.128.1.20')

    def test_operator_can_disable_public_fallback_and_invalid_addresses_fail(self):
        self.assertEqual(fallback_servers(''), [])
        self.assertEqual(fallback_servers('1.1.1.1, 1.0.0.1'), ['1.1.1.1', '1.0.0.1'])
        with self.assertRaises(ValueError):
            fallback_servers('1.1.1.1; command')

    def test_invalid_hostname_cannot_inject_configuration(self):
        for hostname in ('bad/name', 'bad\nserver=1.1.1.1', '-bad'):
            with self.assertRaises(ValueError):
                hostname_records(hostname, '192.0.2.8')

    @unittest.skipUnless(shutil.which('dnsmasq'), 'dnsmasq is required for live DNS protocol regression')
    def test_ipv4_only_hostname_answers_aaaa_without_forwarding_or_refusal(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
            reservation.close()
            config = Path(folder) / 'dnsmasq.conf'
            config.write_text(hostname_records('directory.exercise.test', '192.0.2.8'))
            process = subprocess.Popen(['dnsmasq', '--no-daemon', '--no-resolv', '--no-hosts', '--bind-interfaces',
                                        '--listen-address=127.0.0.1', '--port=' + str(port),
                                        '--user=' + getpass.getuser(), '--pid-file=' + str(Path(folder) / 'pid'),
                                        '--conf-file=' + str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                qname = b''.join(bytes([len(label)]) + label.encode() for label in 'directory.exercise.test'.split('.')) + bytes(1)
                for record_type, expected_answers in ((1, 1), (28, 0)):
                    packet = struct.pack('!6H', 1234, 256, 1, 0, 0, 0) + qname + struct.pack('!2H', record_type, 1)
                    deadline = time.monotonic() + 5
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                        client.settimeout(0.2)
                        while True:
                            if process.poll() is not None:
                                self.fail(process.stderr.read().decode())
                            client.sendto(packet, ('127.0.0.1', port))
                            try:
                                reply = client.recv(4096)
                                break
                            except TimeoutError:
                                if time.monotonic() >= deadline:
                                    raise
                        header = struct.unpack('!6H', reply[:12])
                        self.assertEqual(header[1] & 15, 0)
                        self.assertEqual(header[3], expected_answers)
            finally:
                process.terminate()
                process.communicate(timeout=5)
