"""Populated-state interaction, accessibility and layout contracts; no live mutations."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.browser.support import BrowserFixture
from tests.browser.showcase_data import responses


class LayoutTests(BrowserFixture):
    def setUp(self):
        super().setUp()
        self.role = 'admin'
        self.responses = responses()

    def settled(self, path):
        self.visit(path)
        self.page.wait_for_function("!document.querySelector('main .loading')")
        self.page.evaluate('document.fonts.ready')

    def test_populated_pages_fit_phone_tablet_desktop_in_both_themes(self):
        paths = ['/landing', '/dashboard', '/explore', '/challenge?id=4', '/profile', '/manage-ctf', '/create-ctf', '/upload-diskfile', '/operations', '/impressum', '/privacy-policy', '/signup', '/login', '/activity', '/badges', '/announcements', '/manage-announcements', '/manage-users', '/manage-instances', '/profile/investigator', '/404', '/reset-password']
        for width in (320, 390, 768, 1024, 1440):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for theme in ('light', 'dark'):
                self.page.evaluate("(theme) => localStorage.setItem('heist-theme', theme)", theme) if self.page.url.startswith(self.origin) else None
                for path in paths:
                    with self.subTest(width=width, theme=theme, path=path):
                        self.role='guest' if path in ('/signup','/login','/landing','/404') else 'admin'
                        self.password_change=path=='/reset-password'
                        self.settled(path)
                        # Theme is applied by the app on a full document load.
                        self.page.evaluate("(theme) => document.documentElement.dataset.theme = theme", theme)
                        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
                        self.assertEqual(self.page.get_by_role('main').get_by_role('heading', level=1).count(), 1)
                        self.assertEqual(self.page.locator('main [role=alert]').count(), 0)
                        for image in self.page.locator('img:visible').all():
                            image.scroll_into_view_if_needed()
                            self.page.wait_for_function('(image) => image.complete', arg=image.element_handle())
                            self.assertGreater(image.evaluate('(image) => image.naturalWidth'), 0)

    def test_maximum_length_names_and_unbroken_descriptions_do_not_escape_mobile_cards(self):
        long_name = 'W'*100
        for challenge in self.responses['dashboard']['data']['challenges']:
            challenge['name'] = long_name
            challenge['description'] = 'evidence'*200
        self.responses['challenge']['challenge']['name'] = long_name
        self.responses['profile']['data']['basic']['full_name'] = long_name
        self.responses['admin/operations']['data']['release']['commit'] = 'a'*40
        self.responses['admin/operations']['data']['release']['active_transaction'] = '20261107T101010Z-123456789abc'
        for width in (320, 390, 1024):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for path in ('/dashboard', '/explore', '/challenge?id=4', '/profile', '/operations'):
                with self.subTest(width=width, path=path):
                    self.settled(path)
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)

    def test_retired_challenge_restores_its_own_id_through_the_restore_endpoint(self):
        self.settled('/manage-ctf')
        retired = self.page.get_by_role('row').filter(has_text='Packet Trail')
        self.assertTrue(retired.get_by_role('button', name='Edit', exact=True).is_disabled())
        retired.get_by_role('button', name='Restore', exact=True).click()
        retired.get_by_text('Inactive', exact=True).wait_for()
        requests = [(method, endpoint) for method, endpoint, _ in self.requests if method != 'GET']
        self.assertEqual(requests, [('POST', 'admin/challenges/8/restore')])
        self.assertEqual(json.loads(self.mutations[0][1]), {})

    def test_search_filters_and_paging_do_not_leave_a_stale_admin_selection(self):
        items = self.responses['admin/challenges']['data']['challenges']
        items.extend({**items[0], 'id': i, 'name': f'Lab {i:03d}'} for i in range(20, 45))
        self.settled('/manage-ctf')
        self.page.get_by_role('button', name='Next', exact=False).click()
        self.page.get_by_label('Find a challenge').fill('Glass')
        self.assertEqual(self.page.locator('tbody tr').count(), 1)
        self.assertIn('The Glass Directory', self.page.locator('tbody').inner_text())
        self.page.get_by_label('Find a challenge').fill('')
        self.page.get_by_label('Availability').select_option('retired')
        self.assertEqual(self.page.locator('tbody tr').count(), 1)
        self.assertIn('Packet Trail', self.page.locator('tbody').inner_text())

    def test_delete_dialog_can_be_cancelled_by_keyboard_without_a_mutation(self):
        self.settled('/manage-ctf')
        row = self.page.get_by_role('row').filter(has_text='The Glass Directory')
        row.get_by_role('button', name='Delete', exact=True).focus()
        self.page.keyboard.press('Enter')
        dialog = self.page.get_by_role('dialog')
        dialog.wait_for()
        self.assertIn('The Glass Directory', dialog.inner_text())
        self.page.keyboard.press('Escape')
        dialog.wait_for(state='detached')
        self.assertEqual(self.mutations, [])
        self.assertTrue(row.get_by_role('button', name='Delete', exact=True).evaluate('(el) => el === document.activeElement'))

    def test_mobile_closed_navigation_is_not_keyboard_focusable_and_escape_returns_focus(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.settled('/manage-ctf')
        sidebar = self.page.locator('#workspace-navigation')
        self.assertTrue(sidebar.evaluate('(el) => el.inert'))
        button = self.page.get_by_role('button', name='Toggle navigation')
        button.click()
        self.assertFalse(sidebar.evaluate('(el) => el.inert'))
        self.page.wait_for_function("document.getElementById('workspace-navigation').contains(document.activeElement)")
        self.page.keyboard.press('Tab')
        self.assertTrue(sidebar.evaluate('(el) => el.contains(document.activeElement)'))
        self.page.keyboard.press('Escape')
        self.page.wait_for_function("document.getElementById('workspace-navigation').inert")
        self.assertTrue(button.evaluate('(el) => el === document.activeElement'))
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.page.wait_for_function("!document.getElementById('workspace-navigation').inert")

    def test_enabled_buttons_have_readable_text_in_light_and_dark_themes(self):
        self.settled('/manage-ctf')
        for theme in ('light', 'dark'):
            self.page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            self.page.evaluate('() => Promise.all(document.getAnimations().map(animation => animation.finished))')
            failures = self.page.evaluate("""() => {
              const rgb = value => value.match(/[\d.]+/g).map(Number);
              const luminance = value => rgb(value).slice(0, 3).map(n => {
                n /= 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
              }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
              return [...document.querySelectorAll('main button:not(:disabled), main .button')].filter(el => el.getClientRects().length).flatMap(el => {
                let parent = el, background;
                while (parent) {
                  background = getComputedStyle(parent).backgroundColor;
                  if (rgb(background).length === 3 || rgb(background)[3] > 0) break;
                  parent = parent.parentElement;
                }
                const foreground = luminance(getComputedStyle(el).color), back = luminance(background);
                const ratio = (Math.max(foreground, back) + .05) / (Math.min(foreground, back) + .05);
                return ratio >= 4.5 ? [] : [{text: el.textContent.trim(), ratio}];
              });
            }""")
            self.assertEqual(failures, [], theme)

    def test_copied_legal_pages_remain_public_when_session_storage_is_unavailable(self):
        self.role='guest'
        self.context.route('**/api/session',lambda route:route.fulfill(status=503,json={'success':False,'message':'Unavailable'}))
        for path,title in (('/impressum','Impressum'),('/privacy-policy','Datenschutzerklärung')):
            self.visit(path)
            self.page.get_by_role('heading',name=title,exact=True).wait_for()
            self.assertGreater(self.page.get_by_role('main').get_by_text('Universität Heidelberg',exact=True).count(),0)
            self.assertEqual(self.page.locator('main script, main iframe').count(),0)

    def test_closed_registration_has_no_signup_form_but_keeps_legal_links(self):
        self.role='guest'
        self.responses['site']={'success':True,'data':{'registration_enabled':False,'legal':{'imprint_url':'https://example.invalid/impressum','privacy_url':'https://example.invalid/privacy','version':'test'}}}
        self.settled('/signup')
        self.page.get_by_text('Registration is currently closed.',exact=True).wait_for()
        self.assertEqual(self.page.locator('input[name=lecture_token]').count(),0)
        self.assertEqual(self.page.get_by_role('navigation',name='Legal').get_by_role('link').count(),2)

    def test_signup_requires_lecture_code_and_unchecked_policy_acceptance_with_legal_links(self):
        self.role='guest'
        self.settled('/signup')
        legal=self.page.get_by_role('navigation',name='Legal')
        self.assertEqual(legal.get_by_role('link',name='Impressum').get_attribute('href'),'https://example.invalid/impressum')
        self.assertEqual(legal.get_by_role('link',name='Privacy policy').get_attribute('href'),'https://example.invalid/privacy')
        self.page.get_by_label('Username',exact=True).fill('new_student')
        self.page.get_by_label('Email address').fill('student@example.invalid')
        self.page.get_by_label('Password',exact=True).fill('test-password-long')
        self.page.get_by_label('Confirm password').fill('test-password-long')
        self.page.get_by_label('Lecture code').fill('lecture-fixture')
        acceptance=self.page.locator('input[name=accept_legal]')
        self.assertFalse(acceptance.is_checked())
        self.page.get_by_role('button',name='Create account',exact=True).click()
        self.assertFalse(any(endpoint=='signup' for endpoint,_,_ in self.mutations))
        acceptance.check()
        self.page.get_by_role('button',name='Create account',exact=True).click()
        self.page.wait_for_url('**/dashboard')
        body=next(body for endpoint,body,_ in self.mutations if endpoint=='signup')
        self.assertIn('lecture-fixture',body)
        self.assertIn('fixture-policy-v1',body)

    def test_network_preview_tracks_editor_connections_removal_and_dmz(self):
        self.settled('/create-ctf')
        self.page.get_by_role('button',name='Add machine',exact=False).click()
        self.page.get_by_label('Machine name',exact=True).fill('Target')
        self.page.get_by_role('button',name='Add network',exact=False).click()
        self.page.get_by_label('Network name',exact=True).fill('Entry')
        self.page.get_by_role('checkbox',name='Target',exact=True).check()
        diagram=self.page.get_by_role('img',name='Challenge network preview')
        self.assertEqual(diagram.locator('path.topology-edge').count(),1)
        for width in (320, 390, 768, 1440):
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertTrue(diagram.evaluate('''svg => {
                const region = svg.parentElement;
                const bounds = region.getBoundingClientRect();
                return region.scrollWidth <= region.clientWidth + 1 &&
                    [...svg.querySelectorAll('rect')].every(node => {
                        const box = node.getBoundingClientRect();
                        return box.left >= bounds.left && box.right <= bounds.right;
                    });
            }'''),f'Network or machine clipped at width {width}')
        self.page.get_by_role('checkbox',name='DMZ',exact=True).check()
        self.assertEqual(diagram.locator('.topology-network.dmz').count(),1)
        self.page.get_by_role('button',name='Remove machine',exact=True).click()
        self.assertEqual(diagram.locator('path.topology-edge').count(),0)
        self.assertEqual(diagram.locator('.topology-machine').count(),0)

    def test_official_branding_and_plain_page_titles(self):
        self.settled('/dashboard')
        logo = self.page.get_by_role('link',name='heiST home').get_by_role('img',name='heiST')
        self.assertEqual(logo.get_attribute('src'),'/assets/logo/logo_dark.svg')
        self.assertTrue(logo.evaluate('(image) => image.complete && image.naturalWidth > 0'))
        self.assertEqual(self.page.get_by_role('main').get_by_role('heading',level=1).inner_text(),'Dashboard')
        self.role = 'guest'
        self.settled('/login')
        self.assertEqual(self.page.get_by_role('main').get_by_role('heading',level=1).inner_text(),'Sign in')
        self.assertEqual(self.page.get_by_text('Good to have you back.',exact=True).count(),0)

    def test_yaml_import_populates_reviewable_form_without_creating_an_exercise(self):
        imported = {'name':'Imported lab','description':'Imported description','category':'web','difficulty':'easy','isActive':True,
                    'vms':[{'name':'target','ova_name':'fixture.ova','cores':2,'ram_gb':2,'domain_name':'lab.test','ad_role':'none'}],
                    'subnets':[{'name':'entry','accessible':True,'dmz':False,'attached_vms':['target']}],
                    'flags':[{'flag':'flag-from-yaml','description':'First flag','points':100,'user_specific':True,'vm_name':'target'}],
                    'hints':[{'hint_text':'Imported hint','unlock_points':0}]}
        self.responses['admin/challenges/options'] = {'success':True,'ovas':[{'filename':'fixture.ova'}]}
        requests = []
        def preview(route):
            requests.append(route.request.post_data_json)
            route.fulfill(json={'success':True,'data':imported})
        self.context.route('**/api/admin/challenges/import-yaml',preview)
        self.settled('/create-ctf')
        self.page.get_by_label('YAML file',exact=True).set_input_files({'name':'exercise.yaml','mimeType':'application/yaml','buffer':b'ctf: {name: Imported lab}'})
        self.page.get_by_text('YAML imported. Review the form before creating the challenge.',exact=True).wait_for()
        self.assertEqual(self.page.get_by_label('Challenge name',exact=True).input_value(),'Imported lab')
        self.assertEqual(self.page.get_by_label('Machine name',exact=True).input_value(),'target')
        self.assertEqual(self.page.get_by_label('Hint text',exact=True).input_value(),'Imported hint')
        self.assertEqual(self.page.get_by_role('img',name='Challenge network preview').locator('path.topology-edge').count(),1)
        self.assertEqual(requests,[{'yaml':'ctf: {name: Imported lab}'}])
        self.assertFalse(any(method=='POST' and endpoint=='admin/challenges' for method,endpoint,_ in self.requests))
        # An invalid replacement must preserve the existing draft.
        self.context.unroute('**/api/admin/challenges/import-yaml',preview)
        self.context.route('**/api/admin/challenges/import-yaml',lambda route:route.fulfill(status=400,json={'success':False,'message':'Invalid YAML document'}))
        self.page.get_by_label('YAML file',exact=True).set_input_files({'name':'bad.yml','mimeType':'application/yaml','buffer':b'ctf: ['})
        self.page.get_by_text('Invalid YAML document',exact=True).first.wait_for()
        self.assertEqual(self.page.get_by_label('Challenge name',exact=True).input_value(),'Imported lab')

    def test_theme_survives_navigation_and_reload(self):
        self.settled('/dashboard')
        self.page.get_by_role('button', name='Use light theme').click()
        self.page.get_by_role('button', name='Use dark theme').click()
        self.page.get_by_role('link', name='Challenges', exact=True).click()
        self.page.wait_for_url('**/manage-ctf')
        self.page.reload()
        self.page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        self.assertEqual(self.page.evaluate("localStorage.getItem('heist-theme')"), 'dark')

    def test_desktop_navigation_toggle_persists_and_removed_branding_stays_absent(self):
        self.settled('/dashboard')
        button=self.page.get_by_role('button',name='Toggle navigation')
        self.assertEqual(button.get_attribute('aria-expanded'),'true')
        button.click()
        self.assertEqual(button.get_attribute('aria-expanded'),'false')
        self.assertTrue(self.page.locator('#workspace-navigation').evaluate('(el)=>el.inert'))
        self.page.reload()
        self.assertEqual(button.get_attribute('aria-expanded'),'false')
        button.click()
        self.assertFalse(self.page.locator('#workspace-navigation').evaluate('(el)=>el.inert'))
        self.assertEqual(self.page.locator('.sidebar').get_by_text('SECURITY TRAINING',exact=True).count(),0)
        self.assertEqual(self.page.get_by_text('Heidelberg Security Training',exact=True).count(),0)

    def test_administrator_user_and_instance_actions_require_confirmation(self):
        self.settled('/manage-users')
        target=self.page.get_by_role('row').filter(has_text='student01@example.invalid')
        target.get_by_role('button',name='Change role',exact=True).click()
        self.page.get_by_role('button',name='Cancel',exact=True).click()
        self.assertEqual(self.mutations,[])
        target.get_by_role('button',name='Sign out sessions',exact=True).click()
        self.page.get_by_label('Type student01 to confirm',exact=True).fill('student01')
        self.page.get_by_role('button',name='Apply',exact=True).click()
        self.page.get_by_role('dialog').wait_for(state='hidden')
        self.assertEqual(json.loads(self.mutations[-1][1]),{'action':'revoke_sessions','confirmation':'student01'})
        self.settled('/manage-instances')
        self.assertTrue(self.page.get_by_role('row').filter(has_text='102').get_by_role('button',name='Remove',exact=True).is_enabled())
        active=self.page.get_by_role('row').filter(has_text='student01')
        active.get_by_role('button',name='Inspect',exact=True).click()
        self.page.get_by_role('heading',name='Latest operation',exact=True).wait_for()
        details=self.page.locator('.diagnostic-grid')
        self.assertIn('user',details.inner_text())
        self.assertEqual(details.get_by_text('2',exact=True).count(),1)
        self.responses['admin/instances/101']['data']['operation']={'state':'UNAVAILABLE','scope':'instance','resource':101}
        self.page.get_by_role('button',name='Refresh details',exact=True).click()
        details.get_by_text('UNAVAILABLE',exact=True).wait_for()
        active.get_by_role('button',name='Rebuild',exact=True).click()
        self.assertIn('All guest changes are lost',self.page.get_by_role('dialog').inner_text())
        self.page.get_by_role('button',name='Rebuild',exact=True).last.click()
        self.page.get_by_role('dialog').wait_for(state='hidden')
        self.assertEqual(self.mutations[-1][0],'admin/instances/101')
        self.assertEqual(json.loads(self.mutations[-1][1]),{'action':'rebuild'})
        self.settled('/operations')
        self.page.get_by_role('heading',name='Recorded operations',exact=True).wait_for()
        self.assertIn('NEEDS_REVIEW',self.page.locator('main').inner_text())
        with self.page.expect_response(lambda response: '/api/admin/jobs?' in response.url and 'state=NEEDS_REVIEW' in response.url):
            self.page.get_by_label('Operation state',exact=True).select_option('NEEDS_REVIEW')
        self.assertTrue(any('state=NEEDS_REVIEW' in url for method,endpoint,url in self.requests if endpoint=='admin/jobs'))


    def test_dashboard_highlights_announcements_and_hides_empty_news(self):
        self.responses['dashboard']['data']['news']=[
            {'id':1,'title':'Lecture update','importance':'normal','short_description':'New exercises are available.','created_at':'2026-11-01'},
            {'id':2,'title':'Scheduled maintenance','importance':'critical','short_description':'<script>window.noticeInjected=true</script>','created_at':'2026-11-01'},
        ]
        self.settled('/dashboard')
        region=self.page.get_by_role('region',name='Dashboard announcements')
        self.assertEqual(region.locator('h3').all_text_contents(),['Scheduled maintenance','Lecture update'])
        self.assertEqual(region.locator('.critical').count(),2)
        self.assertLess(region.bounding_box()['y'],self.page.get_by_text('Total points',exact=True).bounding_box()['y'])
        self.assertIsNone(self.page.evaluate('window.noticeInjected'))
        self.assertEqual(region.get_by_role('link',name='View all announcements',exact=False).get_attribute('href'),'/announcements')
        self.responses['dashboard']['data']['news']=[]
        self.settled('/dashboard')
        self.assertEqual(self.page.get_by_role('region',name='Dashboard announcements').count(),0)

    def test_original_badge_artwork_and_illustrated_user_fallback(self):
        self.settled('/badges')
        icons=[value.strip() for value in self.page.locator('.achievement-glyph').all_text_contents()]
        self.assertEqual(icons,['🕸️','🔐','👁️','🕵️','💣','🧩','💉','⚡','👑'])
        self.assertEqual(self.page.locator('.user-chip img').get_attribute('src'),'/assets/avatars/avatar1.png')


if __name__ == '__main__':
    unittest.main(verbosity=2)
