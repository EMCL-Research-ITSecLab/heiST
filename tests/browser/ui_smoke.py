"""Browser contracts and responsive UI regressions against the production build."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tests.browser.support import BrowserFixture


class BrowserTests(BrowserFixture):
    def test_unconfirmed_training_preference_is_not_reported_as_saved(self):
        self.role='student';writes=[]
        def preference(route):
            if route.request.method=='PUT':writes.append(route.request.post_data)
            route.fulfill(json={'success':True,'data':{'opted_out':False,'revision':1}})
        self.page.route('**/api/profile/training-preference',preference)
        self.visit('/profile')
        checkbox=self.page.get_by_label('Allow my challenge traffic in training datasets.',exact=True)
        checkbox.click()
        self.page.get_by_text('Training preference was not confirmed.',exact=True).wait_for()
        self.page.wait_for_function("document.querySelector('input[type=checkbox]')?.disabled === false")
        self.assertTrue(checkbox.is_checked())
        self.assertEqual(len(writes),1)

    def test_training_opt_out_can_be_changed_in_account_and_is_not_public(self):
        self.role='student'
        self.visit('/profile')
        checkbox=self.page.get_by_label('Allow my challenge traffic in training datasets.',exact=True)
        checkbox.wait_for()
        self.assertTrue(checkbox.is_checked())
        checkbox.uncheck()
        self.page.wait_for_function("document.querySelector('input[type=checkbox]')?.disabled === false")
        self.assertFalse(checkbox.is_checked())
        self.assertEqual(self.mutations[0][0],'profile/training-preference')
        self.assertEqual(json.loads(self.mutations[0][1]),{'opted_out':True})
        checkbox.check()
        self.page.wait_for_function("document.querySelector('input[type=checkbox]')?.disabled === false")
        self.assertTrue(checkbox.is_checked())
        self.assertEqual(json.loads(self.mutations[1][1]),{'opted_out':False})
        self.visit('/profile/investigator')
        self.assertEqual(self.page.get_by_label('Allow my challenge traffic in training datasets.',exact=True).count(),0)

    def test_signup_has_no_training_control_and_still_requires_legal_acceptance(self):
        self.visit('/signup')
        checkbox=self.page.get_by_label('Allow my challenge traffic in training datasets.',exact=True)
        self.assertEqual(checkbox.count(),0)
        self.assertEqual(self.page.locator('[name=training_opt_out]').count(),0)
        self.assertTrue(self.page.get_by_role('checkbox',name='I accept',exact=False).evaluate('(element) => element.required'))

    def test_private_activity_loads_on_demand_and_command_html_is_only_text(self):
        self.role='admin'
        command='<img src=x onerror="window.injected=true">'+'x'*2048
        self.responses['admin/monitoring/activity']={'success':True,'data':{'status':'ready','counts':{'commands':1,'processes':1},'events':[
            {'machine_id':123,'timestamp':'2026-11-11T12:00:00Z','kind':'command','description':'Fixture command','command':command,'truncated':True}]}}
        self.page.set_viewport_size({'width':320,'height':900})
        self.visit('/operations?tab=health')
        self.assertFalse(any(endpoint=='admin/monitoring/activity' for _,endpoint,_ in self.requests))
        self.page.get_by_role('button',name='Load activity',exact=True).click()
        table=self.page.get_by_role('table',name='Recent command and process events');table.wait_for()
        self.assertIn('<img',table.inner_text())
        self.assertIsNone(self.page.evaluate('window.injected'))
        self.assertEqual(table.locator('img').count(),0)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),320)
        self.page.get_by_role('button',name='Hide activity',exact=True).click()
        self.assertEqual(self.page.get_by_role('table',name='Recent command and process events').count(),0)
        self.assertEqual(self.mutations,[])

    def test_instance_activity_is_scoped_and_zero_events_are_not_coverage(self):
        from tests.browser.showcase_data import responses
        self.role='admin';self.responses=responses()
        self.responses['admin/monitoring/activity']={'success':True,'data':{'status':'ready','counts':{'commands':0,'processes':0},'events':[]}}
        self.visit('/manage-instances')
        self.page.get_by_role('button',name='Inspect',exact=True).first.click()
        self.page.get_by_role('button',name='Load activity',exact=True).click()
        self.page.get_by_text('No events received in this time window.',exact=False).wait_for()
        urls=[url for _,endpoint,url in self.requests if endpoint=='admin/monitoring/activity']
        self.assertTrue(urls and urls[-1].endswith('?instance_id=101'))
        self.assertIn('coverage is unverified',self.page.locator('main').inner_text())
        self.assertEqual(self.mutations,[])

    def test_instance_monitoring_shows_agent_states_without_command_content(self):
        from tests.browser.showcase_data import responses
        self.role='admin';self.responses=responses()
        self.visit('/manage-instances')
        self.page.get_by_role('button',name='Inspect',exact=True).first.click()
        panel=self.page.get_by_role('region',name='Challenge monitoring',exact=True)
        panel.get_by_role('table',name='Challenge monitoring agents').wait_for()
        self.assertIn('Active',panel.inner_text())
        self.assertIn('Disconnected',panel.inner_text())
        self.assertIn('remain unverified',panel.inner_text())
        self.assertEqual(self.mutations,[])

    def test_monitoring_failures_and_stale_evidence_are_visible(self):
        self.role = 'admin'
        monitoring = {
            'status': 'stale', 'checked_at': '2026-11-01T10:00:00Z', 'checks': [
                {'id': 'host.sensor.dmz', 'label': 'DMZ sensor', 'state': 'failed', 'summary': 'Required sensor stopped'},
                {'id': 'monitoring.delivery', 'label': 'Event delivery', 'state': 'unknown', 'summary': 'Canary not verified'},
            ]}
        self.responses['admin/operations'] = {'success': True, 'data': {'monitoring': monitoring}}
        self.visit('/operations?tab=health')
        panel = self.page.get_by_role('region', name='Platform monitoring', exact=True)
        self.assertIn('Current health is unavailable', panel.inner_text())
        self.assertIn('Failed checks: 1', panel.inner_text())
        self.assertIn('Required sensor stopped', panel.inner_text())
        self.assertTrue(panel.get_by_role('table', name='Platform monitoring checks').is_visible())
        self.assertEqual(self.mutations, [])

    def test_all_public_and_administrator_pages_render_without_runtime_errors(self):
        pages = ['/', '/landing', '/explore', '/challenge?id=1', '/login', '/signup', '/404', '/profile_public?username=someone']
        for path in pages:
            with self.subTest(path=path):
                self.visit(path)
        self.role = 'admin'
        for path in ['/dashboard', '/profile', '/activity', '/announcements', '/badges', '/manage-ctf', '/create-ctf', '/upload-diskfile', '/manage-announcements', '/operations', '/manage-users', '/manage-instances']:
            with self.subTest(path=path):
                self.visit(path)
                self.assertNotIn('Something went wrong', self.page.locator('main').inner_text())

    def test_student_cannot_open_administration_or_issue_admin_requests(self):
        self.role = 'student'
        self.visit('/manage-ctf')
        self.assertIn('Administrator access required', self.page.locator('main').inner_text())
        self.assertEqual(self.mutations, [])
        self.assertEqual(self.page.get_by_role('link', name='Create challenge', exact=True).count(), 0)

    def test_login_posts_csrf_and_returns_to_requested_page(self):
        self.visit('/login?next=%2Fexplore')
        self.page.get_by_label('Username').fill('investigator')
        self.page.locator('input[name=password]').fill('test-only-password')
        self.page.get_by_role('button', name='Sign in').click()
        self.page.wait_for_url('**/explore')
        endpoint, body, headers = self.mutations[0]
        self.assertEqual(endpoint, 'login')
        self.assertEqual(headers.get('x-csrf-token'), 'a'*64)
        self.assertNotIn('name="csrf_token"', body)

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
        self.assertEqual(self.mutations[0][0], 'reset-password')
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
        self.page.get_by_role('button',name='Add network').click()
        internal=self.page.get_by_role('group',name='Network 2',exact=True)
        internal.get_by_label('Network name').fill('internal')
        internal.get_by_label('Student accessible',exact=True).uncheck()
        internal.get_by_label('DMZ',exact=True).check()
        internal.get_by_label('gateway',exact=True).check()
        self.assertEqual(self.page.get_by_role('img',name='Challenge network preview').locator('path.topology-edge').count(),2)
        self.page.get_by_role('button', name='Add flag', exact=False).click()
        flag = self.page.get_by_role('group', name='Flag 1', exact=True)
        flag.get_by_label('Flag value').fill('fixture-discovery')
        self.page.get_by_role('button', name='Create challenge', exact=False).click()
        self.page.wait_for_url('**/manage-ctf')
        endpoint, body, headers = self.mutations[0]
        self.assertEqual(endpoint, 'admin/challenges')
        for field in ('vms', 'subnets', 'flags', 'hints'):
            self.assertIn('name="' + field + '"', body)
        self.assertIn('gateway', body)
        self.assertIn('fixture.ova', body)
        self.assertIn('attached_vms', body)
        self.assertIn('internal',body)
        self.assertIn('students',body)
        self.assertIn('\"dmz\":true',body)
        self.assertIn('\"accessible\":false',body)
        self.assertEqual(headers['x-csrf-token'], 'a'*64)

    def test_chunked_artifact_upload_finalizes_after_all_chunks(self):
        self.role = 'admin'
        self.visit('/upload-diskfile')
        self.page.locator('input[type=file]').set_input_files({'name': 'fixture.ova', 'mimeType': 'application/octet-stream', 'buffer': b'abcdefghijkl'})
        self.page.get_by_role('button', name='Upload artifact').click()
        self.page.get_by_text('Transfer complete. Validation is pending.', exact=True).wait_for()
        requests = [(endpoint, body) for endpoint, body, _ in self.mutations]
        self.assertEqual(len(requests), 5)
        self.assertEqual(json.loads(requests[0][1])['name'],'fixture.ova')
        self.assertTrue(requests[-1][0].endswith('/seal'))
        self.assertEqual([endpoint.rsplit('/',1)[-1] for endpoint,_ in requests[1:-1]],['0','1','2'])
        self.assertEqual([body for _,body in requests[1:-1]],['abcde','fghij','kl'])


    def test_administrator_diagnostics_show_stale_archive_and_export(self):
        self.role = 'admin'
        self.visit('/operations?tab=health')
        self.page.get_by_role('heading', name='Log archive', exact=True).wait_for()
        self.assertEqual(self.page.get_by_text('stale', exact=True).count(), 1)
        self.assertEqual(self.page.get_by_text('backend.service', exact=True).count(), 1)
        with self.page.expect_download() as download:
            self.page.get_by_role('button', name='Download diagnostics JSON').click()
        self.assertEqual(download.value.suggested_filename, 'heist-operations.json')


    def test_mobile_navigation_and_theme(self):
        self.role = 'admin'
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.visit('/dashboard')
        self.page.get_by_role('button', name='Toggle navigation').click()
        self.page.get_by_role('link', name='Challenges', exact=True).click()
        self.page.wait_for_url('**/manage-ctf')
        self.page.wait_for_function("document.querySelector('.menu-button').getAttribute('aria-expanded') === 'false'")
        self.page.get_by_role('button', name='Use light theme').click()
        self.page.get_by_role('button', name='Use dark theme').click()
        self.assertEqual(self.page.locator('html').get_attribute('data-theme'), 'dark')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)


if __name__ == '__main__':
    unittest.main(verbosity=2)
