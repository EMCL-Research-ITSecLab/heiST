"""Small explicit validators for browser contracts; no coercion of booleans to IDs."""
import re
from urllib.parse import urlsplit
from .errors import ApiError


def positive_id(value, name='identifier'):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ApiError('Invalid '+name)
    if isinstance(value, str):
        if not 1 <= len(value) <= 19 or not value.isascii() or not value.isdigit():
            raise ApiError('Invalid '+name)
        value = int(value)
    if not 0 < value < 2**63:
        raise ApiError('Invalid '+name)
    return value


def text(value, *, name, maximum, minimum=0):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ApiError(f'{name} must contain {minimum} to {maximum} characters')
    return value


def username(value):
    if not isinstance(value, str) or re.fullmatch('[A-Za-z0-9_]{3,20}', value) is None:
        raise ApiError('Usernames must contain 3 to 20 letters, numbers or underscores')
    return value


def email(value):
    if not isinstance(value, str) or len(value) > 255 or re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value) is None:
        raise ApiError('Enter a valid email address')
    return value


def website(value, name='Website URL'):
    if value in ('', None):
        return ''
    text(value, name=name, maximum=255)
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or (parsed.port is not None and not 1 <= parsed.port <= 65535) or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 33 for c in value) or '\\' in value:
            raise ValueError('Invalid URL')
    except ValueError:
        raise ApiError('Enter a valid HTTP or HTTPS '+name.lower()) from None
    return value


def choice(value, allowed, name):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError('Invalid '+name)
    return value
