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
        paths = ['/landing', '/dashboard', '/explore', '/challenge?id=4', '/profile', '/manage-ctf', '/create-ctf', '/upload-diskfile', '/operations']
        for width in (320, 390, 768, 1024, 1440):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for theme in ('light', 'dark'):
                self.page.evaluate("(theme) => localStorage.setItem('heist-theme', theme)", theme) if self.page.url.startswith(self.origin) else None
                for path in paths:
                    with self.subTest(width=width, theme=theme, path=path):
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
        for width in (320, 390, 1024):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for path in ('/dashboard', '/explore', '/challenge?id=4', '/profile'):
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

    def test_theme_survives_navigation_and_reload(self):
        self.settled('/dashboard')
        self.page.get_by_role('button', name='Use dark theme').click()
        self.page.get_by_role('link', name='Challenges', exact=True).click()
        self.page.wait_for_url('**/manage-ctf')
        self.page.reload()
        self.page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        self.assertEqual(self.page.evaluate("localStorage.getItem('heist-theme')"), 'dark')


if __name__ == '__main__':
    unittest.main(verbosity=2)
