import unittest
import json
from unittest.mock import Mock
import requests
from heist.api.public.errors import ApiError
from heist.api.public.internal_client import InternalClient
from heist.api.public.validation import choice, email, positive_id, text, username, website


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.response = Mock(status_code=200, headers={'Content-Type': 'application/json'})
        self.response.json.return_value = {'success': True, 'data': {'status': 'ready'}}
        self.response.iter_content.side_effect = lambda **kwargs: iter([json.dumps(self.response.json.return_value).encode() if 'application/json' in self.response.headers.get('Content-Type', '') else self.response.content])
        self.session.request.return_value = self.response
        self.client = InternalClient('https://platform.invalid:8000', 'test-token', session=self.session)

    def test_only_fixed_https_operations_use_private_headers_no_redirects_or_retries(self):
        self.assertTrue(self.client.request('operations')['success'])
        args, options = self.session.request.call_args
        self.assertEqual(args, ('GET', 'https://platform.invalid:8000/admin/operations'))
        self.assertTrue(options['verify'])
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(options['stream'])
        self.assertEqual(options['timeout'], (3, 12))
        self.response.close.assert_called_once()
        with self.assertRaises(ValueError):
            self.client.request('https://evil.invalid')
        self.session.request.assert_called_once()
        self.client.close()
        self.session.close.assert_called_once()

    def test_network_failures_and_redirects_are_safe_errors_without_private_response(self):
        self.session.request.side_effect = requests.Timeout('test-token private transport failure')
        with self.assertRaises(ApiError) as error:
            self.client.request('start', {'user_id': 1, 'challenge_template_id': 2})
        self.assertNotIn('test-token', str(error.exception))
        self.session.request.assert_called_once()
        self.session.request.side_effect = None
        self.response.status_code = 307
        with self.assertRaises(ApiError):
            self.client.request('operations')

    def test_json_failure_is_not_downloaded_as_vpn_configuration(self):
        with self.assertRaises(ApiError):
            self.client.request('vpn', {'user_id': 1}, download=True)
        self.response.headers = {'Content-Type': 'application/x-openvpn-profile'}
        self.response.content = b'client\nremote example.invalid 1194\n'
        self.assertEqual(self.client.request('vpn', {'user_id': 1}, download=True), self.response.content)

    def test_invalid_origins_or_disabled_tls_are_rejected(self):
        for origin in ('http://platform.invalid', 'https://user:password@platform.invalid', 'https://platform.invalid/path', 'https://platform.invalid?redirect=evil'):
            with self.assertRaises(ValueError):
                InternalClient(origin, 'token')
        for certificate in (False, 0, None, '', 'relative-ca.pem', '/etc/../ca.pem'):
            with self.assertRaises(ValueError):
                InternalClient('https://platform.invalid', 'token', certificate=certificate)


class ValidationTests(unittest.TestCase):
    def test_ids_reject_boolean_unicode_fractional_overflow_and_injection_values(self):
        self.assertEqual(positive_id('42'), 42)
        for value in (True, False, '١', 1.5, -1, 0, '1; DROP', 2**63, None):
            with self.assertRaises(ApiError):
                positive_id(value)

    def test_text_username_email_urls_and_enum_constraints(self):
        self.assertEqual(text('hello', name='Value', maximum=5), 'hello')
        self.assertEqual(username('student_1'), 'student_1')
        self.assertEqual(email('student@example.invalid'), 'student@example.invalid')
        self.assertEqual(website('https://example.invalid/profile'), 'https://example.invalid/profile')
        self.assertEqual(website(None), '')
        self.assertEqual(choice('web', ['web', 'crypto'], 'category'), 'web')
        for action in (lambda: text('x\x00', name='Value', maximum=5), lambda: username('a;exec'), lambda: email('bad\n@email.invalid'),
                       lambda: website('javascript:alert(1)'), lambda: website('https://user:password@example.invalid'), lambda: choice(True, ['true'], 'category')):
            with self.assertRaises(ApiError):
                action()
