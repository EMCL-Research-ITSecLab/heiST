"""Bounded requests to the authenticated Flask browser API; never replay writes."""
from urllib.parse import urlsplit
import re


def origin(value):
    if not isinstance(value, str) or any(ord(character) <= 32 for character in value):
        raise ValueError('HEIST_URL must be a plain HTTPS origin')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('HEIST_URL must be a plain HTTPS origin')
    return value.rstrip('/')


def request(session, method, path, *, timeout=(10, 30), **kwargs):
    if (not path.startswith('/api/') or any(character in path for character in ('\\', '#', '%'))
            or any(part in ('.', '..') for part in path.split('/'))):
        raise ValueError('Declare a fixed browser API path')
    if session.verify is False:
        raise ValueError('Operator sessions require verified TLS')
    response = session.request(method, origin(session.heist_url)+path,
                               timeout=timeout, allow_redirects=False, **kwargs)
    try:
        value = response.json()
    except ValueError:
        value = None
    if not 200 <= response.status_code < 300:
        message = value.get('message', '') if isinstance(value, dict) else ''
        message = ''.join(character for character in str(message)[:512] if ord(character) >= 32)
        raise RuntimeError(f'Browser API returned HTTP {response.status_code}: {message}; inspect the existing operation before retrying')
    if value is None:
        raise RuntimeError('Browser API returned an invalid JSON response')
    if not isinstance(value, dict) or value.get('success') is not True:
        raise RuntimeError('Browser API did not confirm the operation; inspect its state before retrying')
    return value


def artifact_name(value):
    if not isinstance(value, str):
        raise ValueError('Declare an OVA filename')
    value = value if value.lower().endswith('.ova') else value+'.ova'
    if '..' in value or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,190}\.ova', value, re.I) is None:
        raise ValueError('Declare a plain OVA filename without directories')
    return value
