"""Capture the built UI with synthetic data; never connect to a live heiST API."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.browser.support import BrowserFixture
from tests.browser.showcase_data import responses

PAGES = {
    'dashboard': ('/dashboard', 'admin'),
    'manage_challenges': ('/manage-ctf', 'admin'),
    'create_challenge': ('/create-ctf', 'admin'),
    'deploy_challenge': ('/challenge?id=4', 'student'),
    'operations': ('/operations', 'admin'),
    'login': ('/login', 'guest'),
    'signup': ('/signup', 'guest'),
    'impressum': ('/impressum', 'guest'),
    'privacy': ('/privacy-policy', 'guest'),
    'mobile': ('/dashboard', 'student'),
}


def capture(output):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    BrowserFixture.setUpClass()
    try:
        for theme in ('light', 'dark'):
            for name, (route, role) in PAGES.items():
                fixture = BrowserFixture()
                fixture.setUp()
                try:
                    fixture.role = role
                    fixture.responses = responses()
                    viewport = {'width': 390, 'height': 844} if name == 'mobile' else {'width': 1440, 'height': 1000}
                    fixture.page.set_viewport_size(viewport)
                    fixture.context.add_init_script(f"localStorage.setItem('heist-theme', {json.dumps(theme)})")
                    fixture.page.clock.set_fixed_time(datetime(2026, 11, 1, 10, 5, tzinfo=timezone.utc))
                    fixture.visit(route)
                    fixture.page.wait_for_function("!document.querySelector('main .loading')")
                    fixture.page.evaluate('document.fonts.ready')
                    if name == 'create_challenge':
                        fixture.page.get_by_label('Challenge name').fill('The Glass Directory')
                        fixture.page.get_by_label('Description', exact=True).fill('Investigate identity boundaries across a portal, directory and archive. Collect evidence and document your findings.')
                        fixture.page.get_by_label('Category', exact=True).select_option('web')
                        fixture.page.get_by_label('Difficulty', exact=True).select_option('medium')
                        fixture.page.get_by_role('button', name='Add machine').click()
                        machine = fixture.page.get_by_role('group', name='Machine 1', exact=True)
                        machine.get_by_label('Machine name').fill('portal')
                        machine.get_by_label('OVA artifact').select_option('identity-portal.ova')
                        fixture.page.get_by_role('button', name='Add machine').click()
                        fixture.page.get_by_role('group', name='Machine 2', exact=True).get_by_label('Machine name').fill('directory')
                        fixture.page.get_by_role('button', name='Add network').click()
                        fixture.page.get_by_label('Network name',exact=True).fill('Entry')
                        fixture.page.get_by_role('checkbox',name='portal',exact=True).check()
                        fixture.page.get_by_role('checkbox',name='directory',exact=True).check()
                    fixture.page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0, 0); }')
                    fixture.page.evaluate('() => Promise.all([...document.images].filter(image => image.getBoundingClientRect().top < innerHeight).map(image => image.decode()))')
                    fixture.page.screenshot(path=output/f'{name}_{theme}.png', animations='disabled', caret='hide')
                    records.append({'file': f'{name}_{theme}.png', 'route': route, 'role': role, 'theme': theme, 'viewport': viewport})
                finally:
                    fixture.tearDown()
        sources = {}
        for directory in ('frontend/src', 'frontend/public'):
            for path in sorted((ROOT/directory).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('frontend/package-lock.json','tests/browser/support.py','tests/browser/showcase_data.py','tools/testing/screenshots.py'):
            sources[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for record in records:
            record['sha256'] = hashlib.sha256((output/record['file']).read_bytes()).hexdigest()
        manifest = {'schema': 1, 'data': 'synthetic documentation fixtures; not an installed-platform acceptance test',
                    'browser': BrowserFixture.browser.version, 'sources': sources, 'captures': records}
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    finally:
        BrowserFixture.tearDownClass()
    print(f'Captured {len(records)} screenshots and source hashes in {output}')


def check(output):
    manifest = json.loads((output/'manifest.json').read_text())
    for name, expected in manifest['sources'].items():
        path = ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Screenshot input changed; regenerate captures: '+name)
    expected_sources = {str(path.relative_to(ROOT)) for directory in ('frontend/src','frontend/public')
                        for path in (ROOT/directory).rglob('*') if path.is_file()}
    if not expected_sources.issubset(manifest['sources']):
        raise RuntimeError('New UI files require refreshed screenshots')
    for record in manifest['captures']:
        if hashlib.sha256((output/record['file']).read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Documentation screenshot changed: '+record['file'])
    print('Verified screenshot sources and PNG checksums')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'assets/showcase')
    parser.add_argument('--check', action='store_true', help='Check screenshot freshness without launching a browser')
    args = parser.parse_args()
    check(args.output) if args.check else capture(args.output)


if __name__ == '__main__':
    main()
