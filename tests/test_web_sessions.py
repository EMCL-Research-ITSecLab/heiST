from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

from heist.security.sessions import Sessions


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.now = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.sessions = Sessions(self.repo, 'a'*64, clock=lambda: self.now)

    def test_invalid_configuration_and_cookie_do_not_reach_storage(self):
        with self.assertRaises(ValueError):
            Sessions(self.repo, 'short')
        for value in (None, '', 'a'*63, '../cookie', True):
            self.assertIsNone(self.sessions.load(value))
        self.repo.call.assert_not_called()

    def test_storage_never_receives_raw_cookie_and_rotation_is_unpredictable(self):
        first = self.sessions.rotate(user_id=42, auth_version=3)
        second = self.sessions.rotate(first, 42, 3)
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn(first, self.repo.call.call_args.args)
        self.assertNotIn(second, self.repo.call.call_args.args)
        self.assertEqual(self.repo.call.call_args.args[3:5], (42, 3))
        self.sessions.load(second)
        self.assertEqual(self.repo.call.call_args.args, ('web_session_read', self.sessions.identity(second), self.now))
        self.sessions.revoke(second)
        self.assertEqual(self.repo.call.call_args.args, ('web_session_remove', self.sessions.identity(second)))

    def test_csrf_token_is_bound_to_session_and_server_secret(self):
        first, second = 'b'*64, 'c'*64
        token = self.sessions.csrf(first)
        self.assertTrue(self.sessions.valid_csrf(first, token))
        self.assertFalse(self.sessions.valid_csrf(second, token))
        self.assertFalse(Sessions(self.repo, 'd'*64).valid_csrf(first, token))
        for invalid in (None, '', True, token.upper()):
            self.assertFalse(self.sessions.valid_csrf(first, invalid))
        with self.assertRaises(ValueError):
            self.sessions.csrf('../cookie')
