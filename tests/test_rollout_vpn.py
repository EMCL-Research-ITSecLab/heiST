"""Legacy VPN migration preserves identity and journals before changing config."""
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from heist.files import sha256
from heist.platform.users.vpn_files import Settings
from heist.rollout.controller import Transaction
from heist.rollout import vpn


class VPNRolloutTests(TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        self.settings=Settings(root=root/'openvpn',lock=root/'ca.lock',management=root/'management.sock')
        for name in ('pki/private','pki/issued'):
            (self.settings.ca/name).mkdir(parents=True)
        for name in ('pki/ca.crt','pki/private/ca.key','pki/issued/server.crt','pki/private/server.key','ta.key'):
            (self.settings.ca/name).write_text('unchanged-'+name)
        self.config=self.settings.root/'server.conf'
        self.config.write_bytes(b'proto udp\n# keep operator settings\n')
        state=root/'transaction';state.mkdir(mode=0o700)
        self.transaction=Transaction(state,{'vpn_identity':vpn.inspect(self.settings)})

    def test_configuration_is_idempotent_and_refuses_conflicts_includes_and_inline_keys(self):
        body=self.config.read_bytes()
        target=vpn.configuration(body,self.settings)
        self.assertEqual(vpn.configuration(target,self.settings),target)
        self.assertTrue(target.startswith(body))
        for line in ('management 127.0.0.1 7505','management-client-user nobody',
                     'crl-verify /unknown/crl.pem','config /unreviewed.conf','<key>'):
            with self.subTest(line=line),self.assertRaises(RuntimeError):
                vpn.configuration(body+line.encode()+b'\n',self.settings)
        with self.assertRaises(RuntimeError):
            vpn.configuration(target+b'management-client-user root\n',self.settings)

    def test_generation_failure_never_changes_server_config_or_published_crl(self):
        before=self.config.read_bytes()
        crl=self.settings.root/'crl.pem';crl.write_bytes(b'old-crl')
        with patch.object(vpn,'easy_rsa',side_effect=RuntimeError('CA unavailable')):
            with self.assertRaisesRegex(RuntimeError,'CA unavailable'):
                vpn.prepare(self.transaction,settings=self.settings)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(crl.read_bytes(),b'old-crl')
        self.assertNotIn('target_configuration_hashes',self.transaction.data)

    def test_identity_changes_refuse_before_any_ca_command_or_host_write(self):
        (self.settings.ca/'pki/private/ca.key').write_text('different CA')
        with patch.object(vpn,'easy_rsa') as rsa:
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                vpn.prepare(self.transaction,settings=self.settings)
            rsa.assert_not_called()

    def test_public_writes_are_journaled_first_and_private_identity_is_untouched(self):
        original=self.transaction.data['vpn_identity'].copy()
        def generate(settings,*args):
            self.assertEqual(args,('gen-crl',))
            (settings.ca/'pki/crl.pem').write_bytes(b'signed-public-crl')
        original_write=vpn.write_file
        def write(path,body,**kwargs):
            from hashlib import sha256 as digest
            self.assertEqual(self.transaction.data['target_configuration_hashes'][str(path)],digest(body).hexdigest())
            original_write(path,body,**kwargs)
        with patch.object(vpn,'easy_rsa',side_effect=generate), \
             patch.object(vpn.subprocess,'run'),patch.object(vpn,'write_file',side_effect=write):
            vpn.prepare(self.transaction,settings=self.settings)
        vpn.verify_identity(original)
        self.assertEqual(self.transaction.data['vpn_identity'],original)
        self.assertEqual((self.settings.root/'crl.pem').stat().st_mode & 0o777,0o644)
        for name,digest in self.transaction.data['target_configuration_hashes'].items():
            self.assertEqual(sha256(name),digest)
