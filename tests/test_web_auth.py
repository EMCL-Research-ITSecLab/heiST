"""Browser auth contracts run against actual PostgreSQL with the restricted web role."""
from contextlib import closing
import os
import unittest

from heist.api.public import create_app
from heist.api.public.repository import Repository
from heist.security.passwords import verify_password
from tests import test_web_database as database_tests


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class PublicAuthenticationTests(unittest.TestCase):
    setUpClass = classmethod(database_tests.WebDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(database_tests.WebDatabaseTests.tearDownClass.__func__)
    remove_database = classmethod(database_tests.WebDatabaseTests.remove_database.__func__)

    def setUp(self):
        database_tests.WebDatabaseTests.setUp(self)
        self.app = create_app({'TESTING': True, 'WEB_SESSION_SECRET': 'a'*64},
                              repository_factory=lambda: Repository(lambda: self.psycopg2.connect(**self.api_settings)), clock=lambda: self.now)
        self.client = self.app.test_client()
        self.client.environ_base['REMOTE_ADDR'] = '192.0.2.'+str(self.user_id % 250 + 1)
        self.token = None

    def request(self, path, method='GET', **kwargs):
        headers = kwargs.pop('headers', {})
        if method != 'GET' and self.token:
            headers = {'X-CSRF-Token': self.token, **headers}
        response = self.client.open('/api/'+path, method=method, base_url='https://localhost', headers=headers, **kwargs)
        if response.is_json and response.json.get('csrf_token'):
            self.token = response.json['csrf_token']
        return response

    def bootstrap(self):
        result = self.request('session')
        self.assertEqual(result.status_code, 200)
        self.token = result.json['data']['csrf_token']
        return result

    def login(self):
        self.bootstrap()
        result = self.request('login', 'POST', json={'username': self.username, 'password': 'legacy-password'})
        self.assertEqual(result.status_code, 200, result.json)
        return result

    def update_user(self, assignments):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('UPDATE users SET '+assignments+' WHERE id=%s', (self.user_id,))

    def test_guest_bootstrap_cookie_csrf_login_rotation_and_legacy_upgrade(self):
        result = self.bootstrap()
        self.assertFalse(result.json['data']['is_logged_in'])
        cookie = self.client.get_cookie('__Host-heist_session')
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Strict')
        old_cookie, old_token = cookie.value, self.token
        self.login()
        self.assertNotEqual(self.client.get_cookie('__Host-heist_session').value, old_cookie)
        self.assertNotEqual(self.token, old_token)
        result = self.bootstrap().json['data']
        self.assertTrue(result['is_logged_in'])
        self.assertEqual(set(result['user']), {'username', 'avatar_url', 'is_admin'})
        record = self.repo.call('web_auth_record', self.username, one=True)
        self.assertTrue(record['password_hash'].startswith('scrypt:'))
        self.assertTrue(verify_password(record['password_hash'], 'legacy-password'))

    def test_unknown_user_and_wrong_password_have_identical_public_failure(self):
        self.bootstrap()
        first = self.request('login', 'POST', json={'username': self.username, 'password': 'incorrect'})
        second = self.request('login', 'POST', json={'username': 'unknown_user', 'password': 'incorrect'})
        self.assertEqual(first.status_code, 401)
        self.assertEqual(first.json, second.json)
        self.assertNotIn('password_hash', str(first.json))

    def test_missing_csrf_cross_origin_duplicate_fields_and_insecure_transport_are_denied(self):
        self.bootstrap()
        response = self.client.post('/api/login', base_url='https://localhost', json={'username': self.username, 'password': 'legacy-password'})
        self.assertEqual(response.status_code, 403)
        response = self.request('login', 'POST', json={'username': self.username, 'password': 'legacy-password'}, headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(response.status_code, 403)
        response = self.request('login', 'POST', data='{"username":"first","username":"second"}', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.get('/api/session', base_url='http://localhost')
        self.assertEqual(response.status_code, 400)

    def test_logout_revokes_replayed_cookie(self):
        self.login()
        old = self.client.get_cookie('__Host-heist_session').value
        self.assertEqual(self.request('logout', 'POST', json={}).status_code, 200)
        replay = self.app.test_client()
        replay.set_cookie('__Host-heist_session', old, secure=True)
        response = replay.get('/api/session', base_url='https://localhost')
        self.assertFalse(response.json['data']['is_logged_in'])

    def test_signup_validates_policy_and_duplicate_accounts_without_partial_success(self):
        self.bootstrap()
        username = 'new_'+self.username[4:]
        value = {'username': username, 'email': username+'@example.invalid', 'password': 'strong-test-password', 'confirm-password': 'strong-test-password'}
        result = self.request('signup', 'POST', json={**value, 'password': 'short', 'confirm-password': 'short'})
        self.assertEqual(result.status_code, 400)
        self.assertIsNone(self.repo.call('web_auth_record', username, one=True))
        self.assertEqual(self.request('signup', 'POST', json=value).status_code, 200)
        self.assertEqual(self.bootstrap().json['data']['user']['username'], username)
        self.assertEqual(self.request('signup', 'POST', json=value).status_code, 409)

    def test_password_change_revokes_old_sessions_and_current_session_is_rotated(self):
        self.login()
        old = self.client.get_cookie('__Host-heist_session').value
        result = self.request('reset-password', 'POST', json={'current_password': 'legacy-password', 'new_password': 'changed-test-password', 'confirm_password': 'changed-test-password'})
        self.assertEqual(result.status_code, 200)
        self.assertNotEqual(self.client.get_cookie('__Host-heist_session').value, old)
        self.assertTrue(self.bootstrap().json['data']['is_logged_in'])
        record = self.repo.call('web_auth_record', self.username, one=True)
        self.assertTrue(verify_password(record['password_hash'], 'changed-test-password'))
        replay = self.app.test_client()
        replay.set_cookie('__Host-heist_session', old, secure=True)
        self.assertFalse(replay.get('/api/session', base_url='https://localhost').json['data']['is_logged_in'])

    def test_administrator_role_is_reloaded_and_revocation_is_immediate(self):
        self.login()
        self.assertFalse(self.bootstrap().json['data']['user']['is_admin'])
        self.update_user('is_admin=TRUE')
        self.assertTrue(self.bootstrap().json['data']['user']['is_admin'])
        self.update_user('is_admin=FALSE')
        self.assertFalse(self.bootstrap().json['data']['user']['is_admin'])

    def test_expired_session_returns_to_guest_state(self):
        from datetime import timedelta
        self.login()
        self.now += timedelta(hours=9)
        self.assertFalse(self.bootstrap().json['data']['is_logged_in'])

    def test_closed_registration_and_malformed_password_change_are_clear_errors(self):
        self.bootstrap()
        self.app.config['REGISTRATION_ENABLED'] = False
        result = self.request('signup', 'POST', json={'username': 'closed_user', 'password': 'sample-password'})
        self.assertEqual(result.status_code, 403)
        self.login()
        result = self.request('reset-password', 'POST', json={'current_password': 'legacy-password', 'new_password': None, 'confirm_password': None})
        self.assertEqual(result.status_code, 400)
        self.assertTrue(verify_password(self.repo.call('web_auth_record', self.username, one=True)['password_hash'], 'legacy-password'))

    def test_large_and_duplicate_form_requests_fail_before_authentication(self):
        from werkzeug.datastructures import MultiDict
        self.bootstrap()
        result = self.request('login', 'POST', data='x'*65537, content_type='application/json')
        self.assertEqual(result.status_code, 413)
        result = self.request('login', 'POST', data=MultiDict([('username', self.username), ('username', 'other'), ('password', 'legacy-password')]))
        self.assertEqual(result.status_code, 400)

    def test_force_reset_flag_and_expired_reset_window_are_preserved(self):
        self.update_user("password_reset=TRUE, password_reset_timestamp=CURRENT_TIMESTAMP-INTERVAL '6 days'")
        result = self.login()
        self.assertEqual(result.json['redirect'], '/reset-password')
        self.assertTrue(self.bootstrap().json['data']['requires_password_change'])
        result = self.request('reset-password', 'POST', json={'current_password': 'legacy-password', 'new_password': 'changed-test-password', 'confirm_password': 'changed-test-password'})
        self.assertEqual(result.status_code, 403)
        self.assertTrue(self.repo.call('web_auth_record', self.username, one=True)['password_reset'])
