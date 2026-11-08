"""The local PVE adapter authenticates only after pinning and never replays POST."""
import ssl
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from heist.rollout.proxmox_api import LocalAPI


class LocalAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = LocalAPI()
        self.api.certificate = Path(self.temp.name)/'certificate.pem'
        self.api.certificate.write_text('certificate fixture')
        self.connection = Mock()
        self.connection.sock.getpeercert.return_value = b'certificate'
        self.connection.getresponse.return_value.status = 200
        self.connection.getresponse.return_value.read.return_value = b'{"data":"UPID:fixture"}'
        self.credentials = {'ticket': 'private-fixture-ticket', 'csrf': 'private-fixture-csrf'}

    def test_signer_uses_literal_pam_username(self):
        result = Mock(stdout=b'{"ticket":"fixture","csrf":"fixture"}')
        with patch('heist.rollout.proxmox_api.subprocess.run', return_value=result) as run:
            self.api.credentials()
        program = run.call_args.args[0][-1]
        self.assertIn('assemble_ticket(q{root@pam})', program)
        self.assertNotIn('"root@pam"', program)

    def test_wrong_certificate_never_transmits_ticket(self):
        with patch.object(self.api, 'credentials', return_value=self.credentials), \
             patch('heist.rollout.proxmox_api.ssl.PEM_cert_to_DER_cert', return_value=b'wrong'), \
             patch('heist.rollout.proxmox_api.http.client.HTTPSConnection', return_value=self.connection):
            with self.assertRaises(ssl.SSLError):
                self.api.request('POST', '/nodes/pve/vzdump', {'vmid': 1000})
        self.connection.request.assert_not_called()
        self.connection.close.assert_called_once()

    def test_polling_reuses_memory_only_ticket_and_refreshes_before_expiry(self):
        first = Mock(stdout=b'{"ticket":"first","csrf":"first"}')
        second = Mock(stdout=b'{"ticket":"second","csrf":"second"}')
        with patch('heist.rollout.proxmox_api.time.monotonic', side_effect=[100, 399, 400]), \
             patch('heist.rollout.proxmox_api.subprocess.run', side_effect=[first, second]) as run:
            self.assertEqual(self.api.credentials()['ticket'], 'first')
            self.assertEqual(self.api.credentials()['ticket'], 'first')
            self.assertEqual(self.api.credentials()['ticket'], 'second')
        self.assertEqual(run.call_count, 2)

    def test_failed_refresh_does_not_reuse_expired_credentials_or_submit_request(self):
        self.api._credentials = self.credentials
        self.api._credentials_until = 100
        with patch('heist.rollout.proxmox_api.time.monotonic', return_value=101), \
             patch('heist.rollout.proxmox_api.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('signer', 60)), \
             patch('heist.rollout.proxmox_api.http.client.HTTPSConnection') as connection:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.api.request('POST', '/nodes/pve/vzdump', {'vmid': 1000})
        connection.assert_not_called()

    def test_invalid_signer_result_is_never_cached(self):
        with patch('heist.rollout.proxmox_api.subprocess.run', return_value=Mock(stdout=b'{"ticket":""}')):
            with self.assertRaisesRegex(RuntimeError, 'invalid credentials'):
                self.api.credentials()
        self.assertIsNone(self.api._credentials)

    def test_uncertain_post_is_never_retried(self):
        self.connection.request.side_effect = TimeoutError('lost response')
        with patch.object(self.api, 'credentials', return_value=self.credentials), \
             patch('heist.rollout.proxmox_api.ssl.PEM_cert_to_DER_cert', return_value=b'certificate'), \
             patch('heist.rollout.proxmox_api.http.client.HTTPSConnection', return_value=self.connection):
            with self.assertRaises(TimeoutError):
                self.api.request('POST', '/nodes/pve/vzdump', {'vmid': 1000})
        self.connection.request.assert_called_once()

    def test_background_task_identity_is_returned(self):
        with patch.object(self.api, 'credentials', return_value=self.credentials), \
             patch('heist.rollout.proxmox_api.ssl.PEM_cert_to_DER_cert', return_value=b'certificate'), \
             patch('heist.rollout.proxmox_api.http.client.HTTPSConnection', return_value=self.connection):
            self.assertEqual(self.api.request('POST', '/nodes/pve/vzdump', {'vmid': 1000}), 'UPID:fixture')
        args, kwargs = self.connection.request.call_args
        self.assertEqual(args, ('POST', '/api2/json/nodes/pve/vzdump'))
        self.assertEqual(kwargs['body'], 'vmid=1000')
