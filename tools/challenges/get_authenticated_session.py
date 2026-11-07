"""Authenticate operator tools through the public, session-protected web API."""
import os
from .client import origin, request


def get_authenticated_session(username, password, prints=False, *, base_url=None, ca_file=None):
    import requests
    base = origin(base_url or os.environ.get('HEIST_URL', 'https://localhost'))
    session = requests.Session()
    session.heist_url = base
    session.verify = ca_file or os.environ.get('HEIST_CA_FILE') or True
    try:
        session.headers.update({'Origin': base})
        bootstrap = request(session, 'GET', '/api/session')
        token = bootstrap['data']['csrf_token']
        if not isinstance(token, str) or len(token) != 64:
            raise RuntimeError('Invalid bootstrap CSRF token')
        session.headers.update({'X-CSRF-Token': token})
        result = request(session, 'POST', '/api/login', json={'username': username, 'password': password})
        if result.get('redirect') == '/reset-password':
            raise RuntimeError('Change this operator account password in the browser before importing exercises')
        token = result.get('csrf_token')
        if not isinstance(token, str) or len(token) != 64:
            raise RuntimeError('The server did not return a valid session CSRF token')
        session.headers.update({'X-CSRF-Token': token})
        if prints:
            print('Authenticated operator session established')
        return session
    except BaseException:
        session.close()
        raise


def main():
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--ca-file')
    args = parser.parse_args()
    with get_authenticated_session(args.username, getpass.getpass(), True,
                                   base_url=args.url, ca_file=args.ca_file):
        pass


if __name__ == '__main__':
    main()
