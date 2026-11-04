"""Opaque, revocable server-side sessions and session-bound CSRF tokens."""
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets


class Sessions:
    def __init__(self, repository, secret, *, clock=None):
        if not isinstance(secret, str) or not re.fullmatch('[a-fA-F0-9]{64}', secret):
            raise ValueError('Configure a persistent 32-byte web session secret as hexadecimal')
        self.repository = repository
        self.key = bytes.fromhex(secret)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def identity(self, raw):
        if not isinstance(raw, str) or not re.fullmatch('[a-f0-9]{64}', raw):
            return None
        return hashlib.sha256(raw.encode()).hexdigest()

    def load(self, raw):
        identifier = self.identity(raw)
        if identifier is None:
            return None
        return self.repository.call('web_session_read', identifier, self.clock(), one=True)

    def csrf(self, raw):
        if self.identity(raw) is None:
            raise ValueError('Invalid session identity')
        return hmac.new(self.key, b'csrf:'+raw.encode(), hashlib.sha256).hexdigest()

    def valid_csrf(self, raw, supplied):
        if self.identity(raw) is None or not isinstance(supplied, str) or not re.fullmatch('[a-f0-9]{64}', supplied):
            return False
        return hmac.compare_digest(self.csrf(raw), supplied)

    def rotate(self, old_raw=None, user_id=None, auth_version=0):
        raw = secrets.token_hex(32)
        self.repository.call('web_session_rotate', self.identity(old_raw), self.identity(raw), user_id, auth_version, self.clock())
        return raw

    def revoke(self, raw):
        identifier = self.identity(raw)
        if identifier is not None:
            self.repository.call('web_session_remove', identifier)
