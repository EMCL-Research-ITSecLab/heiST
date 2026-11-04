"""Fixed-operation HTTPS transport from the unprivileged web API to the platform API."""
from urllib.parse import urlsplit
from pathlib import Path
import json
import uuid
import requests
from .errors import ApiError

OPERATIONS = {
    'operations': ('GET', '/admin/operations', 12),
    'start': ('POST', '/launch-challenge', 1200),
    'stop': ('POST', '/stop-challenge', 300),
    'import_templates': ('POST', '/import-machine-templates', 1200),
    'delete_templates': ('POST', '/delete-machine-templates', 300),
    'delete_vpn': ('POST', '/delete-user-config', 120),
    'vpn': ('POST', '/get-user-config', 120),
}


class InternalClient:
    def __init__(self, origin, token, *, certificate=True, session=None):
        url = urlsplit(origin)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment or any(ord(c) < 33 for c in origin) or '\\' in origin or (url.port is not None and not 1 <= url.port <= 65535):
            raise ValueError('Configure a plain HTTPS internal API origin')
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Configure an internal API authentication token')
        if certificate is not True and (not isinstance(certificate, str) or not Path(certificate).is_absolute() or '..' in Path(certificate).parts):
            raise ValueError('Internal API TLS requires verification or an absolute CA file')
        self.origin = origin.rstrip('/')
        self.token = token
        self.certificate = certificate
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.operation_ids = {}

    def request(self, operation, payload=None, *, download=False):
        if operation not in OPERATIONS:
            raise ValueError('Unsupported platform operation')
        method, endpoint, timeout = OPERATIONS[operation]
        fingerprint = json.dumps([operation, payload], sort_keys=True)
        operation_id = self.operation_ids.setdefault(fingerprint, uuid.uuid4().hex)
        try:
            response = self.session.request(method, self.origin+endpoint, json=payload,
                        headers={'Authentication-Token': self.token, 'Accept': 'application/json', 'Idempotency-Key': operation_id},
                        verify=self.certificate, timeout=(3, timeout), allow_redirects=False, stream=True)
            try:
                if not 200 <= response.status_code < 300:
                    raise ApiError('The platform operation could not be completed. Check its status before retrying.', 503)
                data = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > 2*1024*1024:
                        raise ApiError('The platform response exceeded its size limit', 503)
                if download:
                    if operation != 'vpn' or 'application/json' in response.headers.get('Content-Type', ''):
                        raise ApiError('The VPN configuration is temporarily unavailable', 503)
                    if not data or len(data) > 2*1024*1024:
                        raise ApiError('The VPN configuration is temporarily unavailable', 503)
                    return bytes(data)
                value = json.loads(data)
                if not isinstance(value, dict) or value.get('success') is not True:
                    raise ApiError('The platform operation could not be completed. Check its status before retrying.', 503)
                return value
            finally:
                response.close()
        except (requests.RequestException, ValueError):
            raise ApiError('The platform service is temporarily unavailable. Check its status before retrying.', 503) from None

    def close(self):
        self.session.close()
