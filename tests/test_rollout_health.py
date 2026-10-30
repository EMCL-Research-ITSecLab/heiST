"""Certificate mismatch must fail before authentication material is transmitted."""
import hashlib
import tempfile
from pathlib import Path
import ssl
import unittest
from unittest.mock import Mock, patch

from heist.rollout.health import probe


class HealthTests(unittest.TestCase):
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
