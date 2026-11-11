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
        self.app = create_app({'TESTING': True, 'WEB_SESSION_SECRET': 'a'*64, 'LECTURE_SIGNUP_TOKEN':'test-lecture-code',
                               'IMPRINT_URL':'https://example.invalid/impressum','PRIVACY_URL':'https://example.invalid/privacy','TERMS_URL':'https://example.invalid/terms','LEGAL_VERSION':'test-policy-1'},
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

    def test_signup_training_exclusion_is_optional_and_persisted(self):
        value=self.registration_body()
        self.assertEqual(self.request('signup','POST',json={**value,'training_opt_out':'invalid'}).status_code,400)
        self.assertEqual(self.request('signup','POST',json={**value,'training_opt_out':True}).status_code,200)
        result=self.request('profile/training-preference').json['data']
        self.assertIs(result['opted_out'],True)

    def test_signup_validates_policy_and_duplicate_accounts_without_partial_success(self):
        self.bootstrap()
        username = 'new_'+self.username[4:]
        value = {'username': username, 'email': username+'@example.invalid', 'password': 'strong-test-password', 'confirm-password': 'strong-test-password',
                 'lecture_token':'test-lecture-code','accept_legal':True,'legal_version':self.bootstrap().json['data']['legal']['version']}
        result = self.request('signup', 'POST', json={**value, 'password': 'short', 'confirm-password': 'short'})
        self.assertEqual(result.status_code, 400)
        self.assertIsNone(self.repo.call('web_auth_record', username, one=True))
        self.assertEqual(self.request('signup', 'POST', json=value).status_code, 200)
        self.assertEqual(self.bootstrap().json['data']['user']['username'], username)
        self.assertEqual(self.request('signup', 'POST', json=value).status_code, 409)

    def registration_body(self):
        data = self.bootstrap().json['data']
        return {'username':'new_'+self.username[4:], 'email':'new_'+self.username+'@example.invalid',
                'password':'strong-test-password','confirm-password':'strong-test-password',
                'lecture_token':'test-lecture-code','accept_legal':True,'legal_version':data['legal']['version']}

    def test_registration_secret_consent_and_current_policy_are_server_enforced(self):
        value = self.registration_body()
        self.assertNotIn('test-lecture-code',str(self.bootstrap().json))
        for change,status in (({'lecture_token':'wrong'},403),({'accept_legal':False},400),({'legal_version':'old'},409)):
            response=self.request('signup','POST',json={**value,**change})
            self.assertEqual(response.status_code,status,response.json)
            self.assertIsNone(self.repo.call('web_auth_record',value['username'],one=True))
        self.assertEqual(self.request('signup','POST',json=value).status_code,200)
        with self.psycopg2.connect(**self.settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT a.policy_version,a.imprint_url,a.privacy_url,a.terms_url,a.accepted_at IS NOT NULL FROM public.registration_acceptances a JOIN public.users u ON u.id=a.user_id WHERE u.username=%s',(value['username'],))
                self.assertEqual(cursor.fetchone(),(value['legal_version'],'https://example.invalid/impressum','https://example.invalid/privacy','https://example.invalid/terms',True))

    def test_registration_is_closed_without_operator_settings(self):
        for key in ('LECTURE_SIGNUP_TOKEN','TERMS_URL','PRIVACY_URL','LEGAL_VERSION'):
            old=self.app.config[key];self.app.config[key]=''
            self.assertFalse(self.bootstrap().json['data']['registration_enabled'])
            self.assertEqual(self.request('signup','POST',json={}).status_code,403)
            self.app.config[key]=old

    def test_acceptance_failure_rolls_back_the_new_account(self):
        from unittest.mock import patch
        value=self.registration_body()
        original=Repository.call
        def fail_acceptance(repo,function,*args,**kwargs):
            if function=='web_record_registration':raise RuntimeError('fixture acceptance failure')
            return original(repo,function,*args,**kwargs)
        with patch.object(Repository,'call',fail_acceptance):
            self.assertEqual(self.request('signup','POST',json=value).status_code,503)
        self.assertIsNone(self.repo.call('web_auth_record',value['username'],one=True))

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


class RegistrationSettingsTests(unittest.TestCase):
    def test_bundled_legal_text_is_bound_to_the_policy_revision(self):
        import hashlib,json
        from pathlib import Path
        from heist import legal
        root=Path(__file__).resolve().parents[1]
        documents=json.loads((root/'frontend/src/features/legal/documents.json').read_text())
        digest=hashlib.sha256(json.dumps({name:documents[name] for name in ('privacy-policy','terms-of-service')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest,legal.LEGAL_VERSION)
        self.assertEqual(json.loads((root/'assets/legal-sources.json').read_text())['version'],digest)
        self.assertEqual(set(documents),{'impressum','privacy-policy','terms-of-service'})

    def test_legal_settings_are_available_without_database_or_session_during_maintenance(self):
        from unittest.mock import Mock
        factory=Mock(side_effect=AssertionError('Site settings must not access SQL'))
        app=create_app({'TESTING':True,'WEB_SESSION_SECRET':'a'*64,'MAINTENANCE_FILE':'/proc/self/status',
                        'IMPRINT_URL':'https://example.invalid/impressum','PRIVACY_URL':'https://example.invalid/privacy','TERMS_URL':'https://example.invalid/terms'},repository_factory=factory)
        response=app.test_client().get('/api/site',base_url='https://localhost')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['data']['legal']['imprint_url'],'https://example.invalid/impressum')
        self.assertNotIn('Set-Cookie',response.headers)
        factory.assert_not_called()

    def test_only_public_https_links_and_complete_settings_enable_registration(self):
        from heist.api.public.registration import legal_settings,registration_enabled
        config={'REGISTRATION_ENABLED':True,'LECTURE_SIGNUP_TOKEN':'test-lecture-code','IMPRINT_URL':'https://example.invalid/impressum','PRIVACY_URL':'https://example.invalid/privacy','TERMS_URL':'https://example.invalid/terms','LEGAL_VERSION':'one'}
        self.assertTrue(registration_enabled(config))
        first=legal_settings(config)['version']
        self.assertNotEqual(first,legal_settings({**config,'LEGAL_VERSION':'two'})['version'])
        self.assertEqual(first,legal_settings({**config,'IMPRINT_URL':'https://operator.invalid/imprint'})['version'])
        self.assertNotEqual(first,legal_settings({**config,'TERMS_URL':'https://operator.invalid/terms'})['version'])
        for url in ('javascript:alert(1)','http://example.invalid','https://user:secret@example.invalid','https://example.invalid:bad','https://example.invalid/\n'):
            self.assertFalse(registration_enabled({**config,'PRIVACY_URL':url}))
            self.assertFalse(registration_enabled({**config,'TERMS_URL':url}))
        for code in ('','secret','dummy-token',None):self.assertFalse(registration_enabled({**config,'LECTURE_SIGNUP_TOKEN':code}))
