"""Certificate mismatch must fail before authentication material is transmitted."""
import hashlib
import tempfile
from pathlib import Path
import ssl
import unittest
from unittest.mock import Mock, patch

from heist.rollout.health import probe, certificate_fingerprint


class HealthTests(unittest.TestCase):
    def test_chain_pins_only_first_certificate_even_without_base64_padding(self):
        # Framing is independent of X.509 parsing, which the TLS handshake owns.
        leaf=b'abcdef'
        chain=ssl.DER_cert_to_PEM_cert(leaf)+ssl.DER_cert_to_PEM_cert(b'issuer')
        self.assertEqual(certificate_fingerprint(chain),hashlib.sha256(leaf).hexdigest())
        with self.assertRaisesRegex(ValueError,'complete PEM leaf'):
            certificate_fingerprint('-----BEGIN CERTIFICATE-----\nYWJj')

    def test_remote_web_probe_pins_first_leaf_before_requesting_login(self):
        from heist.rollout import guest_agent
        leaf=b'abcdef'
        self.certificate.write_text(ssl.DER_cert_to_PEM_cert(leaf)+ssl.DER_cert_to_PEM_cert(b'issuer'))
        self.connection.sock.getpeercert.return_value=leaf
        self.connection.getresponse.return_value.read.return_value=b'login'
        with patch.object(guest_agent.http.client,'HTTPSConnection',return_value=self.connection):
            guest_agent.health({'certificate':str(self.certificate)})
            self.connection.request.assert_called_once_with('GET','/login')
            self.connection.reset_mock()
            self.connection.sock.getpeercert.return_value=b'issuer'
            with self.assertRaisesRegex(RuntimeError,'certificate differs'):
                guest_agent.health({'certificate':str(self.certificate)})
            self.connection.request.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.certificate = Path(self.temp.name)/'public.crt'
        self.certificate.write_text('public fixture')
        self.connection = Mock()
        self.connection.sock.getpeercert.return_value = b'peer certificate'
        self.connection.getresponse.return_value.status = 200
        self.connection.getresponse.return_value.read.return_value = b'{"success":true,"status":"ready"}'

    def test_wrong_pin_rejects_before_sending_authentication(self):
        with patch('heist.rollout.health.certificate_fingerprint', return_value='wrong'), \
             patch('heist.rollout.health.http.client.HTTPSConnection', return_value=self.connection):
            with self.assertRaises(ssl.SSLError):
                probe('https://backend.invalid/health/ready', self.certificate,
                      headers={'Authentication-Token': 'fixture-secret'})
        self.connection.request.assert_not_called()
        self.connection.close.assert_called_once()

    def test_status_alone_does_not_imply_ready(self):
        pin = hashlib.sha256(b'peer certificate').hexdigest()
        with patch('heist.rollout.health.certificate_fingerprint', return_value=pin), \
             patch('heist.rollout.health.http.client.HTTPSConnection', return_value=self.connection):
            self.connection.getresponse.return_value.read.return_value = b'{"success":false,"status":"ready"}'
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                probe('https://backend.invalid/health/ready', self.certificate, ready_json=True)
            self.connection.getresponse.return_value.read.return_value = b'{"success":true,"status":"ready"}'
            self.assertEqual(probe('https://backend.invalid/health/ready', self.certificate, ready_json=True), 200)
