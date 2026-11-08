"""Only browser capabilities enter the public service's environment file."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from heist.files import sha256
from heist.rollout.browser_configuration import preserved_registration_settings
from heist.rollout.browser_configuration import configuration, serialize


class BrowserConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.host={'DB_HOST':'10.0.0.102','DB_NAME':'heist','DB_USER':'privileged_admin',
                   'DB_PASSWORD':'private-host-password','PROXMOX_API_TOKEN':'private-pve-token',
                   'SSH_PRIVATE_KEY':'private-ssh-key','BACKEND_AUTHENTICATION_TOKEN':'shared-internal-test-token'}
        self.arguments=dict(role='heist_web_test',password='a'*64,session_secret='b'*64,backend_server_name='heist-pilot')

    def test_public_configuration_contains_only_restricted_credentials_and_verified_peer_identity(self):
        values=configuration(self.host,**self.arguments)
        self.assertEqual(values['DB_USER'],'heist_web_test')
        self.assertEqual(values['DB_PASSWORD'],'a'*64)
        self.assertEqual(values['HEIST_BACKEND_SERVER_NAME'],'heist-pilot')
        self.assertEqual(values['HEIST_BACKEND_CA_FILE'],'/etc/heist/backend-ca.crt')
        result=serialize(values)
        for private in ('privileged_admin','private-host-password','private-pve-token','private-ssh-key'):
            self.assertNotIn(private,result)
        self.assertNotIn('PROXMOX_API_TOKEN',values)
        with self.assertRaises(ValueError):
            serialize({**values,'PROXMOX_API_TOKEN':'private'})

    def test_newlines_control_characters_invalid_hosts_and_invalid_ports_cannot_inject_environment(self):
        for key,value in (('DB_NAME','heist\nPROXMOX_API_TOKEN=bad'),('BACKEND_HOST','host/path'),
                          ('DB_PORT','-1'),('BACKEND_PORT','65536'),('DB_NAME','bad\x00name')):
            with self.subTest(key=key),self.assertRaises(ValueError):
                configuration({**self.host,key:value},**self.arguments)
        for extra in ({'session_secret':'short'},{'ca_file':'../ca.pem'},{'backend_server_name':'host\nother'}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                configuration(self.host,**{**self.arguments,**extra})

    def test_checkpointed_installer_preserves_registration_settings_without_host_credentials(self):
        with TemporaryDirectory() as directory:
            root = Path(directory);(root/'setup').mkdir()
            source = root/'setup/.env'
            source.write_text('LECTURE_SIGNUP_TOKEN=legacy-lecture-token\nHEIST_PRIVACY_URL=https://example.invalid/privacy\nDB_PASSWORD=never-transfer\nPROXMOX_API_TOKEN=never-transfer\n')
            saved = {str(source): sha256(source)}
            values = preserved_registration_settings(root, self.host, saved)
            self.assertEqual(values, {'LECTURE_SIGNUP_TOKEN': 'legacy-lecture-token', 'HEIST_PRIVACY_URL': 'https://example.invalid/privacy'})
            public = configuration({**self.host, **values}, **self.arguments)
            self.assertEqual(public['LECTURE_SIGNUP_TOKEN'], 'legacy-lecture-token')
            self.assertNotIn('never-transfer', serialize(public))
            explicit = {**self.host, 'LECTURE_SIGNUP_TOKEN': '', 'HEIST_PRIVACY_URL': 'https://operator.invalid/privacy'}
            self.assertEqual(preserved_registration_settings(root, explicit, saved), {})
            source.write_text(source.read_text() + 'LECTURE_SIGNUP_TOKEN=changed-after-checkpoint\n')
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                preserved_registration_settings(root, self.host, saved)

    def test_canonical_settings_do_not_fall_back_to_stale_secrets_or_expand_environment(self):
        with TemporaryDirectory() as directory:
            root = Path(directory);(root/'setup').mkdir();(root/'config').mkdir()
            legacy = root/'setup/.env';legacy.write_text('LECTURE_SIGNUP_TOKEN=old-secret\n')
            canonical = root/'config/installer.env';canonical.write_text('LECTURE_SIGNUP_TOKEN=literal-${DO_NOT_EXPAND}\n')
            saved = {str(path): sha256(path) for path in (legacy, canonical)}
            self.assertEqual(preserved_registration_settings(root, {}, saved)['LECTURE_SIGNUP_TOKEN'], 'literal-${DO_NOT_EXPAND}')
            canonical.unlink();canonical.symlink_to(legacy)
            with self.assertRaisesRegex(RuntimeError, 'symlinks'):
                preserved_registration_settings(root, {}, saved)
