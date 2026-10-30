"""Adaptive password hashes with read compatibility for the existing account database."""
import hashlib
import hmac
import re
from werkzeug.security import check_password_hash, generate_password_hash

METHOD = 'scrypt:32768:8:1'


def hash_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 72:
        raise ValueError('Passwords must contain between 8 and 72 characters')
    return generate_password_hash(password, method=METHOD)


def verify_password(stored, password, legacy_salt=''):
    if not isinstance(stored, str) or not isinstance(password, str) or len(password) > 72:
        return False
    if re.fullmatch('[a-fA-F0-9]{128}', stored) and isinstance(legacy_salt, str):
        candidate = hashlib.sha512((legacy_salt+password).encode()).hexdigest()
        return hmac.compare_digest(stored.lower(), candidate)
    try:
        return check_password_hash(stored, password)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored):
    return not isinstance(stored, str) or not stored.startswith(METHOD+'$')
