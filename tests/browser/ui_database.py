"""Real Chromium -> HTTPS -> Flask -> restricted PostgreSQL UI contracts.

Requires an explicitly isolated PostgreSQL administrator connection. Every run
creates and drops its own database and roles; no VM operations are allowed.
The local HTTPS certificate is trusted through its exact generated public key.
"""
from contextlib import closing
import base64
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flask import abort, send_from_directory
from werkzeug.serving import make_server, WSGIRequestHandler
from heist.api.public import create_app
from heist.api.public.repository import Repository
from tests import test_web_database as database_tests


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


class BrowserDatabaseTests(unittest.TestCase):
    remove_database = classmethod(database_tests.WebDatabaseTests.remove_database.__func__)

    @classmethod
    def setUpClass(cls):
        if os.environ.get('HEIST_BROWSER_DATABASE_TESTS') != '1' or not os.environ.get('TEST_DATABASE_URL'):
            raise RuntimeError('Declare HEIST_BROWSER_DATABASE_TESTS=1 and an isolated TEST_DATABASE_URL')
        database_tests.WebDatabaseTests.setUpClass.__func__(cls)
        cls.addClassCleanup(database_tests.WebDatabaseTests.tearDownClass.__func__, cls)
        temporary = tempfile.TemporaryDirectory(prefix='heist-browser-postgres-')
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        key, cert = root/'server.key', root/'server.crt'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
                        '-keyout',str(key),'-out',str(cert)],check=True,capture_output=True,timeout=30)
        public = subprocess.run(['openssl','x509','-in',str(cert),'-pubkey','-noout'],check=True,capture_output=True).stdout
        der = subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=public,check=True,capture_output=True).stdout
        pin = base64.b64encode(hashlib.sha256(der).digest()).decode()
        def forbid_host_operations():
            raise AssertionError('UI database tests must not contact the privileged host API')
        cls.app = create_app({'WEB_SESSION_SECRET': secrets.token_hex(32), 'DATA_ROOT': str(root/'data'),
                             'LECTURE_SIGNUP_TOKEN':'test-lecture-code','IMPRINT_URL':'https://example.invalid/impressum',
                             'PRIVACY_URL':'https://example.invalid/privacy','LEGAL_VERSION':'test-policy-1'},
                             repository_factory=lambda: Repository(lambda: cls.psycopg2.connect(**cls.api_settings)),
                             internal_client_factory=forbid_host_operations)
        @cls.app.get('/', defaults={'path': ''})
        @cls.app.get('/<path:path>')
        def frontend(path):
            if path.startswith('api/'):
                abort(404)
            dist = ROOT/'frontend/dist'
            return send_from_directory(dist, path if (dist/path).is_file() else 'index.html')
        cls.server = make_server('127.0.0.1',0,cls.app,threaded=True,ssl_context=(str(cert),str(key)),request_handler=QuietHandler)
        cls.addClassCleanup(cls.server.server_close)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.shutdown)
        cls.origin = 'https://127.0.0.1:'+str(cls.server.server_port)
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        # Trust only this disposable server's key; certificate errors are not
        # globally ignored, and no CA is installed on the workstation.
        cls.browser = cls.playwright.chromium.launch(args=['--ignore-certificate-errors-spki-list='+pin])
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        database_tests.WebDatabaseTests.setUp(self)
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('UPDATE public.users SET is_admin=true WHERE id=%s',(self.user_id,))
            connection.commit()
        self.context = self.browser.new_context(viewport={'width':1440,'height':1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto(self.origin+'/login')
        self.page.get_by_label('Username').fill(self.username)
        self.page.locator('input[name=password]').fill('legacy-password')
        self.page.get_by_role('button',name='Sign in',exact=False).click()
        self.page.wait_for_url('**/dashboard')

    def tearDown(self):
        self.assertEqual(self.errors,[])

    def test_signup_requires_code_and_acceptance_and_persists_the_policy_record(self):
        self.page.get_by_role('button',name='Sign out',exact=True).click()
        self.page.wait_for_url('**/login')
        self.page.goto(self.origin+'/signup')
        username='new_'+self.username
        self.page.get_by_label('Username',exact=True).fill(username)
        self.page.get_by_label('Email address').fill(username+'@example.invalid')
        self.page.get_by_label('Password',exact=True).fill('strong-test-password')
        self.page.get_by_label('Confirm password').fill('strong-test-password')
        self.page.get_by_label('Lecture code').fill('wrong')
        self.page.locator('input[name=accept_legal]').check()
        self.page.get_by_role('button',name='Create account',exact=True).click()
        self.page.get_by_text('Invalid lecture code',exact=True).wait_for()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM public.users WHERE username=%s',(username,))
                self.assertEqual(cursor.fetchone(),(0,))
        self.page.get_by_label('Lecture code').fill('test-lecture-code')
        self.page.get_by_role('button',name='Create account',exact=True).click()
        self.page.wait_for_url('**/dashboard')
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT a.privacy_url,a.imprint_url,a.accepted_at IS NOT NULL FROM public.registration_acceptances a JOIN public.users u ON u.id=a.user_id WHERE u.username=%s',(username,))
                self.assertEqual(cursor.fetchone(),('https://example.invalid/privacy','https://example.invalid/impressum',True))

    def test_login_uses_secure_persistent_session_and_logout_revokes_it(self):
        cookies = self.context.cookies()
        cookie = next(item for item in cookies if item['name']=='__Host-heist_session')
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httpOnly'])
        self.page.reload()
        self.page.get_by_role('link',name='Communications',exact=True).wait_for()
        self.page.get_by_role('button',name='Sign out',exact=True).click()
        self.page.wait_for_url('**/login')
        self.page.goto(self.origin+'/dashboard')
        self.page.wait_for_url('**/login?next=*')

    def test_announcement_create_edit_and_delete_persist_through_the_real_api(self):
        self.page.goto(self.origin+'/manage-announcements')
        self.page.get_by_role('button',name='New announcement',exact=False).click()
        self.page.get_by_label('Title',exact=True).fill('Browser persistence check')
        self.page.get_by_label('Announcement',exact=True).fill('A disposable end-to-end announcement.')
        self.page.get_by_role('button',name='Publish announcement',exact=True).click()
        self.page.get_by_text('Announcement published',exact=True).wait_for()
        self.page.reload()
        card = self.page.locator('section.card').filter(has=self.page.get_by_role('heading',name='Browser persistence check',exact=True))
        card.get_by_role('button',name='Edit',exact=True).click()
        self.page.get_by_label('Title',exact=True).fill('Updated browser persistence check')
        self.page.get_by_role('button',name='Publish announcement',exact=True).click()
        self.page.get_by_text('Announcement updated',exact=True).wait_for()
        self.page.reload()
        card = self.page.locator('section.card').filter(has=self.page.get_by_role('heading',name='Updated browser persistence check',exact=True))
        card.get_by_role('button',name='Delete',exact=True).click()
        self.page.get_by_role('dialog').get_by_role('button',name='Delete announcement',exact=True).click()
        self.page.get_by_text('Announcement deleted',exact=True).wait_for()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM public.announcements WHERE title IN (%s,%s)",('Browser persistence check','Updated browser persistence check'))
                self.assertEqual(cursor.fetchone()[0],0)

    def test_database_role_revocation_closes_administrator_ui_after_reload(self):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('UPDATE public.users SET is_admin=false WHERE id=%s',(self.user_id,))
            connection.commit()
        self.page.goto(self.origin+'/manage-ctf')
        self.page.get_by_role('heading',name='Administrator access required',exact=True).wait_for()
        self.assertEqual(self.page.get_by_role('button',name='Delete',exact=True).count(),0)


    def test_user_role_and_password_management_persist_through_both_flask_boundaries(self):
        from heist.api.internal import create_app as internal_app
        from heist.security.passwords import verify_password
        from heist.api.public.internal_client import OPERATIONS
        import uuid
        temporary=tempfile.TemporaryDirectory(prefix='heist-admin-ui-')
        self.addCleanup(temporary.cleanup)
        platform=internal_app({'BACKEND_AUTHENTICATION_TOKEN':'fixture-internal-token',
            'OPERATION_DIRECTORY':temporary.name,'MAINTENANCE_FILE':temporary.name+'/absent'},
            services={'get_db_connection':lambda:self.psycopg2.connect(**self.settings)})
        class Bridge:
            # In-process WSGI for the internal boundary, real SQL and real web HTTPS.
            # Production TLS transport is verified separately; no VM calls are allowed.
            def request(bridge,operation,payload=None):
                if operation not in ('admin_users','admin_user_change'):raise AssertionError('Unexpected privileged operation')
                method,path,_=OPERATIONS[operation]
                with platform.test_client() as client:
                    response=client.open(path,method=method,base_url='https://localhost',json=payload,
                        headers={'Authentication-Token':'fixture-internal-token','Idempotency-Key':uuid.uuid4().hex})
                if response.status_code!=200:raise AssertionError(response.json)
                return response.json
            def close(bridge):pass
        previous=self.app.extensions['internal_client_factory']
        self.app.extensions['internal_client_factory']=Bridge
        self.addCleanup(lambda:self.app.extensions.update(internal_client_factory=previous))
        name=self.username+'b'
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM api.create_user(%s,%s,%s,%s,'127.0.0.1')",(name,name+'@example.invalid',self.old_hash,self.legacy_salt))
                target=cursor.fetchone()[0]
                cursor.execute("INSERT INTO web_sessions(token_hash,user_id,auth_version,created_at,last_seen,expires_at,absolute_expires_at) VALUES (%s,%s,0,NOW(),NOW(),NOW()+INTERVAL '1 hour',NOW()+INTERVAL '1 day')",('f'*64,target))
            connection.commit()
        self.page.goto(self.origin+'/manage-users')
        self.page.get_by_label('Find a user',exact=True).fill(name)
        account=self.page.get_by_role('row').filter(has_text=name+'@example.invalid')
        account.get_by_role('button',name='Change role',exact=True).click()
        self.page.get_by_label('Type '+name+' to confirm',exact=True).fill(name)
        self.page.get_by_role('button',name='Apply',exact=True).click()
        self.page.get_by_role('dialog').wait_for(state='hidden')
        account.get_by_text('Administrator',exact=True).wait_for()
        account.get_by_role('button',name='Reset password',exact=True).click()
        self.page.get_by_label('Temporary password',exact=True).fill('temporary-browser-password')
        self.page.get_by_label('Type '+name+' to confirm',exact=True).fill(name)
        self.page.get_by_role('button',name='Apply',exact=True).click()
        self.page.get_by_role('dialog').wait_for(state='hidden')
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT is_admin,password_hash,password_salt,password_reset FROM users WHERE id=%s',(target,))
                admin,encoded,salt,reset=cursor.fetchone()
                self.assertTrue(admin);self.assertTrue(reset)
                self.assertTrue(verify_password(encoded,'temporary-browser-password',salt))
                cursor.execute('SELECT count(*) FROM web_sessions WHERE user_id=%s',(target,))
                self.assertEqual(cursor.fetchone(),(0,))
        self.assertEqual(self.errors,[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
