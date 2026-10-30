"""Authenticate operator tools through the public, session-protected web API."""
import os
from urllib.parse import urlsplit


def get_authenticated_session(username, password, prints=False, *, base_url=None, ca_file=None):
    import requests
    base = (base_url or os.environ.get('HEIST_URL', 'https://localhost')).rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('HEIST_URL must be a plain HTTPS origin')
    session = requests.Session()
    session.heist_url = base
    session.verify = ca_file or os.environ.get('HEIST_CA_FILE') or True
    try:
        bootstrap = session.get(base + '/backend/session.php', timeout=(10, 30))
        bootstrap.raise_for_status()
        token = bootstrap.json()['data']['csrf_token']
        response = session.post(base + '/backend/login.php', data={
            'username': username, 'password': password, 'csrf_token': token,
        }, timeout=(10, 30))
        response.raise_for_status()
        result = response.json()
        if result.get('success') is not True:
            raise RuntimeError('Operator authentication was rejected')
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
