"""VPN failures preserve account material; concurrent profile generation is serialized."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from heist.platform.users import delete_vpn, vpn_config, vpn_files


class VPNAccountsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = vpn_files.Settings(root=self.root/'openvpn', lock=self.root/'ca.lock', management=self.root/'management.sock')
        self.pki = self.settings.ca/'pki'
        for directory in ('issued', 'private', 'reqs'):
            (self.pki/directory).mkdir(parents=True)
        (self.pki/'ca.crt').write_text('test-ca')
        (self.settings.ca/'ta.key').write_text('test-tls-key')
        (self.pki/'index.txt').write_text('')
        self.db = MagicMock()
        self.db.cursor.return_value.__enter__.return_value.fetchone.return_value = ('10.64.0.2',)
        self.environment = patch.dict(os.environ, {'VPN_SERVER_IP': 'vpn.example.invalid'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.events = []

    def certificate(self, name='12'):
        (self.pki/'index.txt').write_text('V\t300101000000Z\t\t01\tunknown\t/CN='+name+'\n')
        (self.pki/'issued'/(name+'.crt')).write_text('test-client-certificate')
        (self.pki/'private'/(name+'.key')).write_text('private-test-key')

    def rsa(self, settings, *args):
        self.assertEqual(settings, self.settings)
        self.events.append(args[0])
        if args[0] == 'build-client-full':
            self.certificate(args[1])
        if args[0] == 'revoke':
            (self.pki/'index.txt').write_text((self.pki/'index.txt').read_text().replace('V\t', 'R\t'))
        if args[0] == 'gen-crl':
            (self.pki/'crl.pem').write_text('test-signed-crl')

    def configured(self):
        (self.settings.root/'server.conf').write_text('crl-verify '+str(self.settings.root/'crl.pem')+'\nmanagement '+str(self.settings.management)+' unix\nmanagement-client-user root\n')

    def test_concurrent_generation_publishes_one_complete_private_profile_without_revocation(self):
        with patch.object(vpn_config, 'easy_rsa', side_effect=self.rsa):
            with ThreadPoolExecutor(max_workers=2) as workers:
                paths = list(workers.map(lambda _: vpn_config.get_user_config(12, self.db, settings=self.settings), (1, 2)))
        self.assertEqual(paths[0], paths[1])
        self.assertEqual(self.events, ['build-client-full'])
        path = Path(paths[0])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn('remote vpn.example.invalid 1194', path.read_text())
        self.assertIn('remote-cert-tls server', path.read_text())
        self.assertIn('private-test-key', path.read_text())
        self.assertEqual((self.settings.root/'ccd/12').read_text(), 'ifconfig-push 10.64.0.2 255.255.255.0\n')

    def test_generation_failure_keeps_reusable_certificate_and_never_revokes_another_request(self):
        with patch.object(vpn_config, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_config, 'atomic_file', side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError):
                vpn_config.get_user_config(12, self.db, settings=self.settings)
        self.assertTrue((self.pki/'private/12.key').is_file())
        self.assertFalse((self.settings.root/'client-configs/12.ovpn').exists())
        with patch.object(vpn_config, 'easy_rsa', side_effect=self.rsa):
            path = vpn_config.get_user_config(12, self.db, settings=self.settings)
        self.assertTrue(Path(path).is_file())
        self.assertEqual(self.events, ['build-client-full'])

    def test_revocation_publication_and_disconnect_precede_leaf_file_removal(self):
        self.certificate()
        self.configured()
        def disconnect(settings, name):
            self.assertTrue((self.pki/'private/12.key').exists())
            self.assertEqual((self.settings.root/'crl.pem').read_text(), 'test-signed-crl')
            self.assertEqual((self.settings.root/'crl.pem').stat().st_mode & 0o777, 0o644)
            self.events.append('disconnect')
        with patch.object(vpn_files, 'easy_rsa', side_effect=self.rsa), patch.object(delete_vpn, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_files.subprocess, 'run') as verify, patch.object(delete_vpn, 'disconnect', side_effect=disconnect):
            delete_vpn.delete_user_config(12, settings=self.settings)
        self.assertEqual(self.events, ['revoke', 'gen-crl', 'disconnect'])
        self.assertTrue(verify.call_args.kwargs['check'])
        self.assertFalse((self.pki/'private/12.key').exists())
        self.assertTrue((self.pki/'index.txt').exists())
        self.assertFalse(vpn_files.valid_certificate(self.settings, '12'))

    def test_revocation_failure_or_missing_configuration_preserves_all_keys(self):
        self.certificate()
        with patch.object(delete_vpn, 'easy_rsa') as rsa, self.assertRaises((OSError, RuntimeError)):
            delete_vpn.delete_user_config(12, settings=self.settings)
        rsa.assert_not_called()
        self.configured()
        with patch.object(delete_vpn, 'easy_rsa', side_effect=subprocess.CalledProcessError(1, ['easyrsa'])), self.assertRaises(subprocess.CalledProcessError):
            delete_vpn.delete_user_config(12, settings=self.settings)
        self.assertTrue((self.pki/'private/12.key').exists())
        self.assertTrue(vpn_files.valid_certificate(self.settings, '12'))

    def test_failed_disconnect_is_retryable_and_never_reports_success(self):
        self.certificate()
        self.configured()
        with patch.object(vpn_files, 'easy_rsa', side_effect=self.rsa), patch.object(delete_vpn, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_files.subprocess, 'run'), patch.object(delete_vpn, 'disconnect', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                delete_vpn.delete_user_config(12, settings=self.settings)
        self.assertTrue((self.pki/'private/12.key').exists())
        self.events.clear()
        with patch.object(vpn_files, 'easy_rsa', side_effect=self.rsa), patch.object(delete_vpn, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_files.subprocess, 'run'), patch.object(delete_vpn, 'disconnect'):
            delete_vpn.delete_user_config(12, settings=self.settings)
        self.assertEqual(self.events, ['gen-crl'])
        self.assertFalse((self.pki/'private/12.key').exists())

    def test_invalid_identifiers_endpoint_symlinks_missing_index_and_busy_lock_fail_closed(self):
        for value in (True, 0, -1, '12', '../etc', 2**63):
            with self.assertRaises(ValueError):
                vpn_config.get_user_config(value, self.db, settings=self.settings)
        for value in (None, 'host\nremote attacker', 'bad/path', 'host:1194'):
            with patch.dict(os.environ, {'VPN_SERVER_IP': value or ''}), self.assertRaises(ValueError):
                vpn_config.get_user_config(12, self.db, settings=self.settings)
        with vpn_files.ca_lock(self.settings), self.assertRaises(TimeoutError):
            with vpn_files.ca_lock(self.settings, timeout=.01):
                self.fail('Competing CA lock was acquired')
        (self.pki/'index.txt').unlink()
        with self.assertRaises(FileNotFoundError):
            delete_vpn.delete_user_config(12, settings=self.settings)
        secret = self.root/'secret'
        secret.write_text('test')
        (self.root/'link').symlink_to(secret)
        with self.assertRaises(OSError):
            vpn_files.read_private(self.root/'link')

    def test_management_uses_local_socket_and_verifies_only_target_client_disconnected(self):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(self.settings.management))
        server.listen(1)
        server.settimeout(3)
        errors = []
        def serve():
            try:
                with server.accept()[0] as connection, connection.makefile('rb') as stream:
                    connection.sendall(b'>INFO:OpenVPN Management Interface Version 5\r\n')
                    self.assertEqual(stream.readline(), b'kill 12\n')
                    connection.sendall(b"SUCCESS: common name '12' found, 1 client(s) killed\r\n")
                    self.assertEqual(stream.readline(), b'status 3\n')
                    connection.sendall(b'HEADER\tCLIENT_LIST\tCommon Name\tReal Address\nCLIENT_LIST\t123\t192.0.2.1:1194\nEND\n')
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        vpn_files.disconnect(self.settings, '12')
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        if errors:
            raise errors[0]

    def test_inherited_ca_common_name_is_overridden_with_the_account_identity(self):
        with patch.dict(os.environ, {'EASYRSA_REQ_CN': 'CA name must not be reused'}), patch.object(vpn_files.subprocess, 'run') as run:
            vpn_files.easy_rsa(self.settings, 'build-client-full', '12', 'nopass')
        self.assertEqual(run.call_args.kwargs['env']['EASYRSA_REQ_CN'], '12')
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertTrue(run.call_args.kwargs['check'])

    def test_wrong_common_name_is_rejected_before_publishing_a_profile(self):
        with patch.object(vpn_config, 'easy_rsa', side_effect=lambda settings, *args: self.certificate('13')):
            with self.assertRaises(RuntimeError):
                vpn_config.get_user_config(12, self.db, settings=self.settings)
        self.assertFalse((self.settings.root/'client-configs/12.ovpn').exists())

    def test_renewal_replaces_only_verified_crl_and_preserves_old_copy_on_failure(self):
        from heist.platform.users.renew_crl import renew
        self.configured()
        (self.settings.root/'crl.pem').write_text('old-signed-crl')
        with patch.object(vpn_files, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_files.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['openssl'])):
            with self.assertRaises(subprocess.CalledProcessError):
                renew(self.settings)
        self.assertEqual((self.settings.root/'crl.pem').read_text(), 'old-signed-crl')
        with patch.object(vpn_files, 'easy_rsa', side_effect=self.rsa), patch.object(vpn_files.subprocess, 'run'):
            renew(self.settings)
        self.assertEqual((self.settings.root/'crl.pem').read_text(), 'test-signed-crl')
