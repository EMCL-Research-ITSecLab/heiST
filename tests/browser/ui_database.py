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
        cls.app = create_app({'WEB_SESSION_SECRET': secrets.token_hex(32), 'DATA_ROOT': str(root/'data')},
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
