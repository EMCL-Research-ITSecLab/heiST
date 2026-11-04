"""Only browser capabilities enter the public service's environment file."""
import unittest
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
