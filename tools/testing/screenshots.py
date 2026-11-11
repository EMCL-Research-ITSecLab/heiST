"""Capture the built UI with synthetic data; never connect to a live heiST API."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import re
import struct

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.browser.support import BrowserFixture
from tests.browser.showcase_data import responses

PAGES = {
    'landing': ('/landing','guest'),
    'dashboard': ('/dashboard', 'admin'),
    'explore': ('/explore','student'),
    'deploy_challenge': ('/challenge?id=4', 'student'),
    'profile': ('/profile','student'),
    'public_profile': ('/profile/investigator','student'),
    'activity': ('/activity','student'),
    'achievements': ('/badges','student'),
    'announcements': ('/announcements','student'),
    'manage_challenges': ('/manage-ctf', 'admin'),
    'create_challenge': ('/create-ctf', 'admin'),
    'artifacts': ('/upload-diskfile','admin'),
    'manage_announcements': ('/manage-announcements','admin'),
    'operations': ('/operations', 'admin'),
    'monitoring_activity': ('/operations', 'admin'),
    'users': ('/manage-users','admin'),
    'instances': ('/manage-instances','admin'),
    'instance_details': ('/manage-instances','admin'),
    'login': ('/login', 'guest'),
    'signup': ('/signup', 'guest'),
    'reset_password': ('/reset-password','student'),
    'impressum': ('/impressum', 'guest'),
    'privacy': ('/privacy-policy', 'guest'),
    'terms': ('/terms-of-service', 'guest'),
    'not_found': ('/404','guest'),
    'mobile': ('/dashboard', 'student'),
    'collapsed_navigation': ('/dashboard','admin'),
}
ALIASES = {'/':'landing','/profile_public?username=investigator':'public_profile'}


def check_routes():
    source=(ROOT/'frontend/src/App.tsx').read_text().split('export const routes = [',1)[1].split('] as const',1)[0]
    declared=set(re.findall(r"\['([^']+)'",source))
    captured={route.split('?')[0] for route,_ in PAGES.values()} | {route.split('?')[0] for route in ALIASES}
    captured.discard('/profile/investigator');captured.add('/profile/:username')
    if declared-captured:raise RuntimeError('Routes without documentation captures: '+str(sorted(declared-captured)))


def capture(output):
    check_routes()
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
                    fixture.password_change = name == 'reset_password'
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
                        machine.get_by_label('Domain name').fill('portal.lab')
                        fixture.page.get_by_role('button', name='Add machine').click()
                        directory=fixture.page.get_by_role('group',name='Machine 2',exact=True)
                        directory.get_by_label('Machine name').fill('directory')
                        directory.get_by_label('OVA artifact').select_option('identity-directory.ova')
                        directory.get_by_label('Domain name').fill('directory.lab')
                        fixture.page.get_by_role('button', name='Add network').click()
                        fixture.page.get_by_label('Network name',exact=True).fill('Entry')
                        fixture.page.get_by_role('checkbox',name='portal',exact=True).check()
                        fixture.page.get_by_role('checkbox',name='directory',exact=True).check()
                        fixture.page.get_by_role('button',name='Add network').click()
                        internal=fixture.page.get_by_role('group',name='Network 2',exact=True)
                        internal.get_by_label('Network name',exact=True).fill('Internal')
                        internal.get_by_role('checkbox',name='Student accessible',exact=True).uncheck()
                        internal.get_by_role('checkbox',name='directory',exact=True).check()
                        fixture.page.get_by_role('button',name='Add flag',exact=False).click()
                        fixture.page.get_by_label('Flag value').fill('synthetic-documentation-flag')
                        fixture.page.get_by_label('Flag description').fill('Find the identity permission boundary.')
                        fixture.page.get_by_role('button',name='Add hint',exact=False).click()
                        fixture.page.get_by_label('Hint text').fill('Compare the permissions on both networks.')
                    if name == 'instance_details':
                        fixture.page.get_by_role('row').filter(has_text='101').get_by_role('button',name='Inspect',exact=True).click()
                        fixture.page.get_by_role('heading',name='Latest operation',exact=True).wait_for()
                    if name in ('instance_details', 'monitoring_activity'):
                        fixture.page.get_by_role('button',name='Load activity',exact=True).click()
                        fixture.page.get_by_role('table',name='Recent command and process events').wait_for()
                    if name == 'collapsed_navigation':
                        fixture.page.get_by_role('button',name='Toggle navigation').click()
                    fixture.page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0, 0); }')
                    fixture.page.evaluate("() => Promise.all([...document.images].map(image => {image.loading='eager';return image.decode();}))")
                    if fixture.errors or fixture.page.locator('main [role=alert]').count():raise RuntimeError('A documentation page failed to render: '+name)
                    fixture.page.screenshot(path=output/f'{name}_{theme}.png', animations='disabled', caret='hide', full_page=True)
                    records.append({'file': f'{name}_{theme}.png', 'route': route, 'role': role, 'theme': theme, 'viewport': viewport, 'full_page': True, 'document_height': fixture.page.evaluate('document.documentElement.scrollHeight')})
                finally:
                    fixture.tearDown()
        sources = {}
        for directory in ('frontend/src', 'frontend/public'):
            for path in sorted((ROOT/directory).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('frontend/index.html','frontend/package.json','frontend/package-lock.json','tests/browser/support.py','tests/browser/showcase_data.py','tools/testing/screenshots.py'):
            sources[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for record in records:
            record['sha256'] = hashlib.sha256((output/record['file']).read_bytes()).hexdigest()
        manifest = {'schema': 1, 'data': 'synthetic documentation fixtures; not an installed-platform acceptance test',
                    'aliases': ALIASES, 'browser': BrowserFixture.browser.version, 'sources': sources, 'captures': records}
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        gallery='# UI screenshot gallery\n\nFull-page captures in both themes, using synthetic records. Click a file to inspect its complete content. These are fixture UI captures, not installed-platform acceptance.\n\n| Page / state | Light | Dark |\n|---|---|---|\n'
        gallery+=''.join(f'| {name.replace("_"," ").title()} | [Light]({name}_light.png) | [Dark]({name}_dark.png) |\n' for name in PAGES)
        gallery+='\nLanding also covers `/`; public profile also covers `/profile_public?username=investigator`. View the complete editor, account forms, nine achievements, instance details and legal text below the fold.\n'
        (output/'README.md').write_text(gallery)
    finally:
        BrowserFixture.tearDownClass()
    print(f'Captured {len(records)} screenshots and source hashes in {output}')


def check(output):
    check_routes()
    manifest = json.loads((output/'manifest.json').read_text())
    for name, expected in manifest['sources'].items():
        path = ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Screenshot input changed; regenerate captures: '+name)
    expected_sources = {str(path.relative_to(ROOT)) for directory in ('frontend/src','frontend/public')
                        for path in (ROOT/directory).rglob('*') if path.is_file()}
    if not expected_sources.issubset(manifest['sources']):
        raise RuntimeError('New UI files require refreshed screenshots')
    expected={(name,theme) for name in PAGES for theme in ('light','dark')}
    captured={(record['file'].removesuffix('.png').rsplit('_',1)[0],record['theme']) for record in manifest['captures']}
    if captured!=expected:raise RuntimeError('Missing or unexpected page/theme captures')
    for record in manifest['captures']:
        if not record.get('full_page'):raise RuntimeError('Documentation captures must include the full page')
        width,height=struct.unpack('>II',(output/record['file']).read_bytes()[16:24])
        if height<record['document_height'] or width!=record['viewport']['width']:raise RuntimeError('Clipped documentation capture')
        if hashlib.sha256((output/record['file']).read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Documentation screenshot changed: '+record['file'])
    print('Verified screenshot sources and PNG checksums')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'assets/screenshots')
    parser.add_argument('--check', action='store_true', help='Check screenshot freshness without launching a browser')
    args = parser.parse_args()
    check(args.output) if args.check else capture(args.output)


if __name__ == '__main__':
    main()
