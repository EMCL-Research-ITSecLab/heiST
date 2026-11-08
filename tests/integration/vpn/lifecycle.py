#!/usr/bin/env python3
"""Explicit isolated-host VPN rehearsal with a new CA and loopback-only server.

Run as root only on a disposable test host with OpenVPN, Easy-RSA and a TUN
interface available. No installed CA, service or client configuration is used.
Launch through `unshare --net`; the test refuses the host's network namespace.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from heist.platform.users.vpn_config import get_user_config
from heist.platform.users.delete_vpn import delete_user_config
from heist.platform.users.renew_crl import renew
from heist.platform.users.vpn_files import Settings, certificate_states, read_private


class VPNLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.stat('/proc/self/ns/net').st_ino == os.stat('/proc/1/ns/net').st_ino:
            raise RuntimeError('Run this test in a fresh network namespace with unshare --net')
        subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True, capture_output=True, timeout=5)

    def wait_for(self, predicate, description, timeout=25):
        deadline = time.monotonic()+timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail(description+' timed out')
            time.sleep(.1)

    def clients(self, settings):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(settings.management))
            with client.makefile('rb') as stream:
                self.assertTrue(stream.readline(65537).startswith(b'>INFO:'))
                client.sendall(b'status 3\n')
                names = set()
                for _ in range(1000):
                    line = stream.readline(65537)
                    self.assertTrue(line and len(line) <= 65536)
                    if line.strip() == b'END':
                        return names
                    if line.startswith(b'CLIENT_LIST\t'):
                        names.add(line.split(b'\t')[1].decode())
                self.fail('Management status exceeded its line limit')

    def test_connected_client_revocation_denies_reconnect_and_preserves_other_client(self):
        processes = []
        with tempfile.TemporaryDirectory(prefix='heist-vpn-') as temporary, ExitStack() as resources:
            root = Path(temporary)
            settings = Settings(root=root/'openvpn', lock=root/'ca.lock', management=root/'management.sock')
            settings.ca.mkdir(parents=True)
            for name in ('easyrsa', 'openssl-easyrsa.cnf', 'x509-types'):
                (settings.ca/name).symlink_to(Path('/usr/share/easy-rsa')/name)
            environment = dict(os.environ, EASYRSA=str(settings.ca), EASYRSA_PKI=str(settings.ca/'pki'),
                               EASYRSA_BATCH='1', EASYRSA_ALGO='ec', EASYRSA_CURVE='prime256v1', EASYRSA_REQ_CN='heiST disposable VPN test')
            def command(arguments):
                return subprocess.run(arguments, cwd=settings.ca, env=environment, capture_output=True, check=True, timeout=120)
            rsa = str(settings.ca/'easyrsa')
            command([rsa, '--batch', 'init-pki'])
            command([rsa, '--batch', 'build-ca', 'nopass'])
            command([rsa, '--batch', 'build-server-full', 'server', 'nopass'])
            command([rsa, '--batch', 'gen-crl'])
            command(['openvpn', '--genkey', 'secret', str(settings.ca/'ta.key')])
            shutil.copyfile(settings.ca/'pki/crl.pem', settings.root/'crl.pem')
            (settings.root/'ccd').mkdir()
            # Reserve a distinct local UDP listener; the installed VPN is unused.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            configuration = f'''dev tunhv-s
local 127.0.0.1
port {port}
proto udp
server 192.0.2.0 255.255.255.0
topology subnet
ca {settings.ca}/pki/ca.crt
cert {settings.ca}/pki/issued/server.crt
key {settings.ca}/pki/private/server.key
dh none
tls-auth {settings.ca}/ta.key 0
crl-verify {settings.root}/crl.pem
management {settings.management} unix
management-client-user root
client-config-dir {settings.root}/ccd
tun-mtu 1338
keepalive 1 10
verb 3
'''
            server_config = settings.root/'server.conf'
            # Start from the legacy production shape, then exercise the actual
            # migration against this new CA before connecting real VPN clients.
            from heist.rollout import vpn as rollout_vpn
            from heist.rollout.controller import Transaction
            legacy='\n'.join(line for line in configuration.splitlines()
                             if not line.startswith(('crl-verify ','management ','management-client-user ')))+'\n'
            server_config.write_text(legacy)
            journal=root/'rollout';journal.mkdir(mode=0o700)
            transaction=Transaction(journal,{'vpn_identity':rollout_vpn.inspect(settings)})
            rollout_vpn.prepare(transaction,settings=settings)
            self.assertEqual(server_config.read_text(),rollout_vpn.configuration(legacy.encode(),settings).decode())
            def start(config, label):
                log = resources.enter_context((root/(label+'.log')).open('wb'))
                process = subprocess.Popen(['openvpn', '--config', str(config)], cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                return process
            try:
                server = start(server_config, 'server')
                self.wait_for(lambda: settings.management.exists() or server.poll() is not None, 'VPN server startup')
                self.assertIsNone(server.poll(), 'Isolated VPN server failed to start')
                with patch.dict(os.environ, environment | {'VPN_SERVER_IP': '127.0.0.1'}):
                    for number, address in ((420001, '192.0.2.2'), (420002, '192.0.2.3')):
                        database = MagicMock()
                        database.cursor.return_value.__enter__.return_value.fetchone.return_value = (address,)
                        generated = Path(get_user_config(number, database, settings=settings))
                        copied = root/(str(number)+'.ovpn')
                        copied.write_text(generated.read_text().replace('remote 127.0.0.1 1194', 'remote 127.0.0.1 '+str(port)).replace('dev tun\n', 'dev tunhv-c'+str(number % 10)+'\n')+'\nroute-noexec\nifconfig-noexec\n')
                        copied.chmod(0o600)
                        start(copied, str(number))
                self.wait_for(lambda: self.clients(settings) == {'420001', '420002'}, 'Both VPN client handshakes')
                renew(settings)
                self.assertEqual(self.clients(settings), {'420001', '420002'})
                original_certificate = root/'revoked.crt'
                original_certificate.write_bytes(read_private(settings.ca/'pki/issued/420001.crt'))
                delete_user_config(420001, settings=settings)
                self.assertEqual(certificate_states(settings, '420001'), ['R'])
                self.assertFalse((settings.ca/'pki/private/420001.key').exists())
                self.assertFalse((settings.root/'client-configs/420001.ovpn').exists())
                self.assertEqual(self.clients(settings), {'420002'})
                result = subprocess.run(['openssl', 'verify', '-crl_check', '-CAfile', str(settings.ca/'pki/ca.crt'),
                                         '-CRLfile', str(settings.root/'crl.pem'), str(original_certificate)], capture_output=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'certificate revoked', result.stderr)
                self.wait_for(lambda: 'certificate revoked' in (root/'server.log').read_text(), 'Revoked client reconnect denial')
                self.assertEqual(self.clients(settings), {'420002'})
                # Idempotent retry must handle the real management "not found" response.
                delete_user_config(420001, settings=settings)
                self.assertEqual(self.clients(settings), {'420002'})
            except BaseException:
                for label in ('server', '420001', '420002'):
                    path = root/(label+'.log')
                    if path.exists():
                        print(label+' test daemon diagnostics:\n'+'\n'.join(path.read_text().splitlines()[-18:]), flush=True)
                raise
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                for process in reversed(processes):
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                self.assertTrue(all(process.poll() is not None for process in processes))


if __name__ == '__main__':
    if os.geteuid() != 0 or os.environ.get('HEIST_ISOLATED_NETWORK_TESTS') != '1':
        raise SystemExit('Requires root and HEIST_ISOLATED_NETWORK_TESTS=1 on a disposable host')
    if not shutil.which('openvpn') or not Path('/usr/share/easy-rsa/easyrsa').is_file() or not Path('/dev/net/tun').exists():
        raise SystemExit('OpenVPN, Easy-RSA and a usable TUN device must already be available')
    unittest.main(verbosity=2)
