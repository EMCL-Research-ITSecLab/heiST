"""Legal-page imports preserve readable main content and exclude executable markup."""
import unittest
from tools.maintenance.import_legal_pages import Content


class LegalImportTests(unittest.TestCase):
    def test_main_content_keeps_text_and_safe_links_without_site_scripts_or_event_handlers(self):
        parser=Content()
        parser.feed('<header>Old navigation</header><main><h1 onclick="bad()">Notice</h1><p>Contact<br><a href="mailto:team@example.invalid" onclick="bad()">Team</a></p><script>bad()</script><iframe>bad()</iframe></main><footer>Old footer</footer>')
        self.assertEqual(parser.nodes[0],{'tag':'h1','attrs':{},'children':['Notice']})
        rendered=str(parser.nodes)
        self.assertIn('mailto:team@example.invalid',rendered)
        for unwanted in ('Old navigation','Old footer','onclick','bad()','iframe','script'):
            self.assertNotIn(unwanted,rendered)

    def test_executable_links_and_unreviewed_main_tags_are_refused(self):
        for html in ('<main><a href="javascript:bad()">Bad</a></main>','<main><form>Bad</form></main>'):
            with self.subTest(html=html),self.assertRaises(ValueError):Content().feed(html)
