"""Profile authorization and mutations against the real restricted PostgreSQL role."""
from contextlib import closing
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests import test_web_auth as auth_tests
from tests.test_web_media import png
from heist.security.passwords import verify_password


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class ProfileTests(unittest.TestCase):
    setUpClass = classmethod(auth_tests.PublicAuthenticationTests.setUpClass.__func__)
    tearDownClass = classmethod(auth_tests.PublicAuthenticationTests.tearDownClass.__func__)
    remove_database = classmethod(auth_tests.PublicAuthenticationTests.remove_database.__func__)
    request = auth_tests.PublicAuthenticationTests.request
    bootstrap = auth_tests.PublicAuthenticationTests.bootstrap
    login = auth_tests.PublicAuthenticationTests.login

    def setUp(self):
        auth_tests.PublicAuthenticationTests.setUp(self)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app.config['DATA_ROOT'] = temporary.name
        self.internal = Mock()
        self.app.extensions['internal_client_factory'] = lambda: self.internal

    def test_profile_reads_require_auth_and_public_view_excludes_private_identity(self):
        self.assertEqual(self.request('profile').status_code, 401)
        self.login()
        value = self.request('profile').json['data']
        self.assertEqual(value['basic']['email'], self.username+'@example.invalid')
        self.assertEqual(value['stats']['total_points'], 0)
        self.assertEqual(len(value['stats']['categories']), 6)
        self.assertIsInstance(value['badges'], list)
        public = self.request('profiles/'+self.username).json['data']['profile']
        for field in ('email', 'last_login', 'password_hash', 'password_salt', 'vpn_static_ip'):
            self.assertNotIn(field, public)
        self.assertEqual(self.request('profiles/missing_user').status_code, 404)
        self.assertEqual(self.request('profile?type=unknown').status_code, 400)

    def test_field_changes_use_session_owner_and_preserve_raw_text_for_react(self):
        self.login()
        for value in ({'action': 'update_full_name', 'full_name': 'Alice & Bob'},
                      {'action': 'update_bio', 'bio': '<script>alert(1)</script>'},
                      {'action': 'update_social', 'github': 'https://github.com/example', 'website': 'https://example.invalid'}):
            result = self.request('profile', 'POST', json={**value, 'user_id': self.user_id+1})
            self.assertEqual(result.status_code, 200, result.json)
        value = self.request('profile?type=basic').json['data']
        self.assertEqual(value['full_name'], 'Alice & Bob')
        self.assertEqual(value['bio'], '<script>alert(1)</script>')
        self.assertEqual(value['github_url'], 'https://github.com/example')
        for value in ({'action': 'update_email', 'email': 'invalid'}, {'action': 'update_username', 'username': '../root'},
                      {'action': 'update_social', 'website': 'javascript:alert(1)'}, {'action': 'update_bio', 'bio': 'x'*501},
                      {'action': 'update_avatar', 'avatar': '../../private'}, {'action': 'unknown'}):
            self.assertEqual(self.request('profile', 'POST', json=value).status_code, 400)

    def test_username_email_change_and_duplicate_conflict_are_atomic(self):
        self.login()
        updated = 'edit_'+self.username[4:]
        result = self.request('profile', 'POST', json={'action': 'update_username', 'username': updated})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.bootstrap().json['data']['user']['username'], updated)
        value = {'action': 'update_email', 'email': updated+'@example.invalid'}
        self.assertEqual(self.request('profile', 'POST', json=value).status_code, 200)
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)', ('taken_'+self.username[4:], 'taken_'+self.username+'@example.invalid', 'unused', '', '127.0.0.1'))
        result = self.request('profile', 'POST', json={'action': 'update_email', 'email': 'taken_'+self.username+'@example.invalid'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.request('profile?type=basic').json['data']['email'], value['email'])

    def test_avatar_upload_and_selection_clean_up_only_owned_generated_images(self):
        self.login()
        result = self.request('profile', 'POST', data={'action': 'upload_avatar', 'avatar': (io.BytesIO(png()), '../../evil.php')})
        self.assertEqual(result.status_code, 200, result.json)
        url = result.json['avatar_url']
        path = self.root/'media/avatars'/url.rsplit('/', 1)[-1]
        self.assertTrue(path.is_file())
        self.assertEqual(self.request('profile?type=basic').json['data']['avatar_url'], url)
        result = self.request('profile', 'POST', json={'action': 'update_avatar', 'avatar': 'avatar2'})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(path.exists())
        result = self.request('profile', 'POST', data={'action': 'upload_avatar', 'avatar': (io.BytesIO(b'<svg/>'), 'avatar.png')})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.request('profile?type=basic').json['data']['avatar_url'], '/assets/avatars/avatar2.png')

    def test_vpn_download_is_private_and_platform_identity_is_never_client_supplied(self):
        self.login()
        self.internal.request.return_value = b'client\nprivate-key\n'
        result = self.request('profile', 'POST', json={'action': 'get_vpn_config', 'user_id': self.user_id+1})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b'client\nprivate-key\n')
        self.assertIn('attachment', result.headers['Content-Disposition'])
        self.assertIn('no-store', result.headers['Cache-Control'])
        self.internal.request.assert_called_once_with('vpn', {'user_id': self.user_id}, download=True)
        self.internal.close.assert_called_once()

    def test_profile_password_change_uses_shared_policy_and_revokes_old_cookie(self):
        self.login()
        old = self.client.get_cookie('__Host-heist_session').value
        result = self.request('profile', 'POST', json={'action': 'change_password', 'current_password': 'legacy-password', 'new_password': 'changed-password'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertNotEqual(self.client.get_cookie('__Host-heist_session').value, old)
        self.assertTrue(verify_password(self.repo.call('web_auth_record', self.username, one=True)['password_hash'], 'changed-password'))

    def test_account_deletion_revokes_cookies_and_frees_ip_only_after_platform_success(self):
        self.login()
        cookie = self.client.get_cookie('__Host-heist_session').value
        self.internal.request.return_value = {'success': True}
        result = self.request('profile', 'DELETE', json={'password': 'wrong-password'})
        self.assertEqual(result.status_code, 401)
        self.internal.request.assert_not_called()
        result = self.request('profile', 'DELETE', json={'password': 'legacy-password', 'user_id': self.user_id+1})
        self.assertEqual(result.status_code, 200, result.json)
        self.internal.request.assert_called_once_with('delete_vpn', {'user_id': self.user_id})
        self.assertIsNone(self.repo.call('web_user_identity', self.user_id, one=True))
        replay = self.app.test_client()
        replay.set_cookie('__Host-heist_session', cookie, secure=True)
        self.assertFalse(replay.get('/api/session', base_url='https://localhost').json['data']['is_logged_in'])
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM vpn_static_ips WHERE user_id=%s', (self.user_id,))
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_failed_vpn_revocation_preserves_account_and_ip_for_retry(self):
        from heist.api.public.errors import ApiError
        self.login()
        self.internal.request.side_effect = ApiError('VPN revocation is unavailable', 503)
        result = self.request('profile', 'DELETE', json={'password': 'legacy-password'})
        self.assertEqual(result.status_code, 503)
        self.assertIsNotNone(self.repo.call('web_user_identity', self.user_id, one=True))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM vpn_static_ips WHERE user_id=%s', (self.user_id,))
                self.assertEqual(cursor.fetchone()[0], 1)
        self.internal.request.side_effect = None
        self.internal.request.return_value = {'success': True}
        self.assertEqual(self.request('profile', 'DELETE', json={'password': 'legacy-password'}).status_code, 200)

    def test_account_owner_resources_and_last_admin_are_checked_before_platform_mutation(self):
        self.login()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO challenge_templates(name,category,difficulty,creator_id) VALUES ('Owned exercise','web','easy',%s)", (self.user_id,))
        result = self.request('profile', 'DELETE', json={'password': 'legacy-password'})
        self.assertEqual(result.status_code, 409, result.json)
        self.assertIn('exercises', result.json['message'])
        self.internal.request.assert_not_called()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM challenge_templates WHERE creator_id=%s', (self.user_id,))
                cursor.execute('UPDATE users SET is_admin=FALSE')
                cursor.execute('UPDATE users SET is_admin=TRUE WHERE id=%s', (self.user_id,))
        result = self.request('profile', 'DELETE', json={'password': 'legacy-password'})
        self.assertEqual(result.status_code, 409, result.json)
        self.assertIn('another administrator', result.json['message'])
        self.internal.request.assert_not_called()
