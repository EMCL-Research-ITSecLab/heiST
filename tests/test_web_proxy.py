"""Reject configuration injection before any Apache/service mutation."""
from pathlib import Path
import unittest

from heist.rollout.web_proxy import render


class ProxyConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.template = (Path(__file__).resolve().parents[1]/'deploy/web/apache/heist.conf').read_text()
        self.settings = dict(web_root='/var/www/heist', certificate='/etc/heist/tls.pem',
                             certificate_key='/etc/heist/tls.key', hostname='heist.example.invalid')

    def test_render_binds_only_the_loopback_api_and_replaces_forwarding_headers(self):
        result = render(self.template, **self.settings)
        self.assertIn('http://127.0.0.1:8001/api/', result)
        self.assertIn('ProxyAddHeaders Off', result)
        self.assertIn('RequestHeader set X-Forwarded-For "expr=%{REMOTE_ADDR}"', result)
        self.assertIn('RequestHeader set X-Forwarded-Proto "https"', result)
        self.assertNotIn('@WEB_ROOT@', result)

    def test_paths_host_port_listener_and_unknown_placeholders_cannot_inject_directives(self):
        for key, value in (('web_root', '/var/www/../private'), ('web_root', '/var/www/"\nInclude /private'),
                           ('certificate', 'relative.pem'), ('hostname', 'host\nListen 80'),
                           ('api_port', True), ('api_port', 80), ('bind', '*:443\nListen 80'), ('bind', '*:65536')):
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                render(self.template, **{**self.settings,key:value})
        with self.assertRaises(ValueError):
            render(self.template+'\n@UNKNOWN@', **self.settings)

    def test_existing_certificate_chain_filename_can_contain_plus(self):
        certificate = '/etc/ssl/certs/emcl-ctf.iwr.uni-heidelberg.de+Chain.pem'
        result = render(self.template, **{**self.settings, 'certificate': certificate})
        self.assertIn('SSLCertificateFile "'+certificate+'"', result)
        for suffix in ('"', '\nInclude /private', '${SECRET}', '|command', '/../key.pem'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                render(self.template, **{**self.settings, 'certificate': certificate+suffix})
