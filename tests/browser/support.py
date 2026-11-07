"""Chromium UI regressions against the production build with isolated HTTP API fixtures.
Run after npm --prefix frontend run build. No real challenge actions are invoked.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not (ROOT/'frontend/dist'/urlsplit(self.path).path.lstrip('/')).is_file():
            self.path = '/index.html'
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class BrowserFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT/'frontend/dist')))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.playwright = sync_playwright().start()
        import os
        browser_name = os.environ.get('HEIST_BROWSER', 'chromium')
        if browser_name not in ('chromium', 'firefox', 'webkit'):
            raise ValueError('Unsupported HEIST_BROWSER')
        cls.browser = getattr(cls.playwright, browser_name).launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='en-GB', timezone_id='UTC', device_scale_factor=1)
        self.context.set_default_timeout(5000)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.role = 'guest'
        self.password_change = False
        self.failed = False
        self.mutations = []
        self.responses = {}
        self.requests = []
        self.context.route('**/api/**', self.api)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def api(self, route):
        request = route.request
        endpoint = urlsplit(request.url).path.removeprefix('/api/')
        self.requests.append((request.method, endpoint, request.url))
        if request.method == 'GET' and endpoint in self.responses:
            return route.fulfill(json=self.responses[endpoint])
        if request.method in ('POST','PUT','PATCH','DELETE'):
            self.mutations.append((endpoint, request.post_data or '', request.headers))
            match = re.fullmatch(r'admin/challenges/(\d+)/restore', endpoint)
            if match and request.method == 'POST':
                for challenge in self.responses.get('admin/challenges', {}).get('data', {}).get('challenges', []):
                    if str(challenge['id']) == match[1]:
                        challenge['marked_for_deletion'] = False
            if endpoint == 'login':
                self.role = 'student'
            if endpoint == 'reset-password':
                self.password_change = False
            if endpoint == 'logout':
                self.role = 'guest'
            if endpoint=='admin/artifact-uploads':
                return route.fulfill(status=201,json={'success':True,'data':{'id':'b'*32,'name':'fixture.ova','size':12,'guest_os':'linux','state':'RECEIVING','chunk_bytes':5}})
            if endpoint.endswith('/seal'):
                return route.fulfill(status=202,json={'success':True,'data':{'state':'SEALED'},'message':'Transfer complete. Validation is pending.'})
            return route.fulfill(json={'success': True, 'message': 'Changes saved.', 'redirect': '/dashboard'})
        if endpoint == 'session':
            return route.fulfill(json={'success': True, 'data': {'is_logged_in': self.role != 'guest', 'requires_password_change': self.password_change, 'csrf_token': 'a'*64, 'user': {'username': 'investigator', 'is_admin': self.role == 'admin'}}})
        if self.failed:
            return route.fulfill(status=503, json={'success': False, 'message': 'Temporary service failure'})
        if endpoint == 'admin/operations':
            return route.fulfill(json={'success': True, 'data': {'database': 'ready', 'maintenance': False, 'source_version': '0.3.0', 'services': [{'unit': 'backend.service', 'state': 'active', 'detail': 'running'}], 'archive': {'status': 'stale', 'last_success_at': '2026-10-30T10:00:00Z'}, 'lifecycle': {'ACTIVE': 2}, 'release': {'version': '0.3.0'}, 'checked_at': '2026-10-30T11:00:00Z'}})
        if endpoint == 'admin/challenges/options':
            return route.fulfill(json={'success': True, 'ovas': [{'filename': 'fixture.ova'}]})
        if endpoint == 'challenge':
            return route.fulfill(json={'success': True, 'challenge': {'id': 1, 'name': 'Identity lab', 'description': '<script>window.injected=true</script>', 'is_active': True, 'flags_total': 2, 'challenge_status': {'challenge_status': 'running'}, 'remaining_seconds': 3600}})
        if endpoint=='admin/artifacts':
            return route.fulfill(json={'success':True,'data':{'ovas':[],'uploads':[],'limits':{'MAX_FILE_SIZE':10000,'CHUNK_SIZE':5}}})
        data = {'challenges': [], 'stats': {}, 'pagination': {'total_pages': 1}, 'badges': [], 'activities': [], 'announcements': [], 'ovas': [], 'user': {}, 'profile': {}}
        route.fulfill(json={'success': True, 'data': data})

    def visit(self, path):
        self.page.goto(self.origin + path)
        self.page.get_by_role('main').get_by_role('heading').first.wait_for()

