"""Chromium UI regressions against the production build with isolated HTTP API fixtures.
Run after npm --prefix frontend run build. No real challenge actions are invoked.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
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


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT/'frontend/dist')))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.context.set_default_timeout(5000)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.role = 'guest'
        self.password_change = False
        self.failed = False
        self.mutations = []
        self.context.route('**/backend/**', self.api)
        self.context.route('**/config/general.config.json', lambda route: route.fulfill(json={'upload': {'MAX_FILE_SIZE': 10000, 'CHUNK_SIZE': 5, 'CHUNK_UPLOAD_THRESHOLD': 10}}))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def api(self, route):
        request = route.request
        endpoint = urlsplit(request.url).path.rsplit('/', 1)[-1]
        if request.method == 'POST':
            self.mutations.append((endpoint, request.post_data or '', request.headers))
            if endpoint == 'login.php':
                self.role = 'student'
            if endpoint == 'reset-password.php':
                self.password_change = False
            if endpoint == 'logout.php':
                self.role = 'guest'
            return route.fulfill(json={'success': True, 'message': 'Changes saved.', 'redirect': '/dashboard', 'uploadId': 'owned-test-upload'})
        if endpoint == 'session.php':
            return route.fulfill(json={'success': True, 'data': {'is_logged_in': self.role != 'guest', 'requires_password_change': self.password_change, 'csrf_token': 'a'*64, 'user': {'username': 'investigator', 'is_admin': self.role == 'admin'}}})
        if self.failed:
            return route.fulfill(status=503, json={'success': False, 'message': 'Temporary service failure'})
        if endpoint == 'create-ctf.php':
            return route.fulfill(json={'success': True, 'ovas': [{'filename': 'fixture.ova'}]})
        if endpoint == 'challenge.php':
            return route.fulfill(json={'success': True, 'challenge': {'id': 1, 'name': 'Identity lab', 'description': '<script>window.injected=true</script>', 'is_active': True, 'flags_total': 2, 'challenge_status': {'challenge_status': 'running'}, 'remaining_seconds': 3600}})
        data = {'challenges': [], 'stats': {}, 'pagination': {'total_pages': 1}, 'badges': [], 'activities': [], 'announcements': [], 'ovas': [], 'user': {}, 'profile': {}}
        route.fulfill(json={'success': True, 'data': data})

    def visit(self, path):
        self.page.goto(self.origin + path)
        self.page.get_by_role('main').get_by_role('heading').first.wait_for()

    def test_all_public_and_administrator_pages_render_without_runtime_errors(self):
        pages = ['/', '/landing', '/explore', '/challenge?id=1', '/login', '/signup', '/404', '/profile_public?username=someone']
        for path in pages:
            with self.subTest(path=path):
                self.visit(path)
        self.role = 'admin'
        for path in ['/dashboard', '/profile', '/activity', '/announcements', '/badges', '/manage-ctf', '/create-ctf', '/upload-diskfile', '/manage-announcements', '/operations']:
            with self.subTest(path=path):
                self.visit(path)
                self.assertNotIn('Something went wrong', self.page.locator('main').inner_text())

    def test_student_cannot_open_administration_or_issue_admin_requests(self):
        self.role = 'student'
        self.visit('/manage-ctf')
        self.assertIn('This space is for administrators', self.page.locator('main').inner_text())
        self.assertEqual(self.mutations, [])
        self.assertEqual(self.page.get_by_role('link', name='Create challenge', exact=True).count(), 0)

    def test_login_posts_csrf_and_returns_to_requested_page(self):
        self.visit('/login?next=%2Fexplore')
        self.page.get_by_label('Username').fill('investigator')
        self.page.locator('input[name=password]').fill('test-only-password')
        self.page.get_by_role('button', name='Sign in').click()
        self.page.wait_for_url('**/explore')
        endpoint, body, headers = self.mutations[0]
        self.assertEqual(endpoint, 'login.php')
        self.assertEqual(headers.get('x-csrf-token'), 'a'*64)
        self.assertIn('csrf_token', body)

    def test_forced_password_change_uses_existing_api_field_names(self):
        self.role = 'student'
        self.password_change = True
        self.page.goto(self.origin + '/dashboard')
        self.page.wait_for_url('**/reset-password')
        self.page.get_by_label('Current password').fill('old-test-password')
        self.page.get_by_label('New password').fill('new-test-password')
        self.page.get_by_label('Confirm password').fill('new-test-password')
        self.page.get_by_role('button', name='Save new password').click()
        self.page.wait_for_url('**/dashboard')
        self.assertEqual(self.mutations[0][0], 'reset-password.php')
        for field in ('current_password', 'new_password', 'confirm_password'):
            self.assertIn('name="' + field + '"', self.mutations[0][1])

    def test_server_errors_can_be_retried_and_injected_html_stays_text(self):
        self.role = 'student'
        self.failed = True
        self.visit('/explore')
        self.page.get_by_role('button', name='Try again').click()
        self.failed = False
        self.page.get_by_role('button', name='Try again').click()
        self.page.get_by_text('No matching challenges').wait_for()
        self.visit('/challenge?id=1')
        self.assertIn('<script>', self.page.locator('.prose').first.inner_text())
        self.assertIsNone(self.page.evaluate('window.injected'))

    def test_challenge_editor_submits_structured_existing_api_contract(self):
        self.role = 'admin'
        self.visit('/create-ctf')
        self.page.get_by_label('Challenge name').fill('Fixture investigation')
        self.page.get_by_label('Description', exact=True).fill('A disposable browser fixture')
        self.page.get_by_role('button', name='Add machine').click()
        machine = self.page.get_by_role('group', name='Machine 1', exact=True)
        machine.get_by_label('Machine name').fill('gateway')
        machine.get_by_label('OVA artifact').select_option('fixture.ova')
        machine.get_by_label('Domain name').fill('gateway.lab')
        self.page.get_by_role('button', name='Add network').click()
        network = self.page.get_by_role('group', name='Network 1', exact=True)
        network.get_by_label('Network name').fill('students')
        network.get_by_label('gateway', exact=True).check()
        self.page.get_by_role('button', name='Add flag', exact=False).click()
        flag = self.page.get_by_role('group', name='Flag 1', exact=True)
        flag.get_by_label('Flag value').fill('fixture-discovery')
        self.page.get_by_role('button', name='Create challenge', exact=False).click()
        self.page.wait_for_url('**/manage-ctf')
        endpoint, body, headers = self.mutations[0]
        self.assertEqual(endpoint, 'create-ctf.php')
        for field in ('vms', 'subnets', 'flags', 'hints', 'csrf_token'):
            self.assertIn('name="' + field + '"', body)
        self.assertIn('gateway', body)
        self.assertIn('fixture.ova', body)
        self.assertIn('attached_vms', body)
        self.assertEqual(headers['x-csrf-token'], 'a'*64)

    def test_chunked_artifact_upload_finalizes_after_all_chunks(self):
        self.role = 'admin'
        self.visit('/upload-diskfile')
        self.page.locator('input[type=file]').set_input_files({'name': 'fixture.ova', 'mimeType': 'application/octet-stream', 'buffer': b'abcdefghijkl'})
        self.page.get_by_role('button', name='Upload artifact').click()
        self.page.get_by_text('Artifact uploaded and validated.', exact=False).wait_for()
        requests = [(endpoint, body) for endpoint, body, _ in self.mutations]
        self.assertEqual(len(requests), 5)
        self.assertEqual(json.loads(requests[0][1])['phase'], 'init')
        self.assertEqual(json.loads(requests[-1][1])['phase'], 'finalize')
        for endpoint, body in requests[1:-1]:
            self.assertEqual(endpoint, 'upload-diskfile.php')
            self.assertIn('name="chunkIndex"', body)
            self.assertIn('name="csrf_token"', body)


    def test_mobile_navigation_and_theme(self):
        self.role = 'admin'
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.visit('/dashboard')
        self.page.get_by_role('button', name='Toggle navigation').click()
        self.page.get_by_role('link', name='Challenges', exact=True).click()
        self.page.wait_for_url('**/manage-ctf')
        self.page.wait_for_function("document.querySelector('.menu-button').getAttribute('aria-expanded') === 'false'")
        self.page.get_by_role('button', name='Use dark theme').click()
        self.assertEqual(self.page.locator('html').get_attribute('data-theme'), 'dark')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)


if __name__ == '__main__':
    unittest.main(verbosity=2)
