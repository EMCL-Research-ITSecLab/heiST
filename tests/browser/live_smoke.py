"""Read-only UI smoke checks against an explicitly selected heiST installation.
Use a dedicated test account. Exercise deployment/removal is not invoked.
"""
import argparse
import getpass
import os
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--admin', action='store_true', help='Also check administrator screens')
    parser.add_argument('--ignore-local-tls-errors', action='store_true', help='Only permitted for a loopback appliance tunnel')
    parser.add_argument('--allow-loopback-http', action='store_true', help='Only for an isolated, loopback PHP preview')
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    url = urlsplit(origin)
    loopback = url.hostname in ('localhost', '127.0.0.1', '::1')
    if url.username or url.password or url.path or url.query or url.fragment or not url.hostname:
        parser.error('Supply a plain web origin')
    if url.scheme != 'https' and not (args.allow_loopback_http and loopback and url.scheme == 'http'):
        parser.error('Use HTTPS, or explicitly enable a loopback HTTP preview')
    if args.ignore_local_tls_errors and not loopback:
        parser.error('TLS verification may only be disabled for a loopback appliance tunnel')
    password = os.environ.get('HEIST_TEST_PASSWORD') or getpass.getpass('Test account password: ')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(ignore_https_errors=args.ignore_local_tls_errors)
            page = context.new_page()
            page.set_default_timeout(15000)
            errors, failures = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: failures.append((urlsplit(response.url).path, response.status))
                    if '/backend/' in response.url and response.status >= 400 else None)
            page.goto(origin + '/login')
            page.locator('input[name=username]').fill(args.username)
            page.locator('input[name=password]').fill(password)
            page.get_by_role('button', name='Sign in').click()
            page.wait_for_url('**/dashboard')
            routes = ['/dashboard', '/explore', '/profile', '/badges', '/activity', '/announcements']
            if args.admin:
                routes += ['/manage-ctf', '/create-ctf', '/upload-diskfile', '/manage-announcements', '/operations']
            for route in routes:
                with page.expect_response(lambda response: '/backend/' in response.url and not response.url.endswith('/session.php')) as response:
                    page.goto(origin + route)
                response.value.finished()
                page.get_by_role('main').get_by_role('heading').first.wait_for()
                # ResourceState hides the loading indicator only after the API
                # response has been handled, rather than using an arbitrary sleep.
                page.locator('main .loading').wait_for(state='hidden')
                alerts = page.locator('main [role=alert]').all_inner_texts()
                if alerts:
                    raise RuntimeError(route + ': ' + '; '.join(alerts))
                print('PASS', route)
            if errors or failures:
                raise RuntimeError('Browser errors or failed API responses: ' + str(errors + failures))
        finally:
            browser.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
