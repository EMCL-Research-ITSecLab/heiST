"""Fixed-operation HTTPS transport from the unprivileged web API to the platform API."""
from urllib.parse import urlsplit
from pathlib import Path
import json
import re
import os
from heist.security.tls import server_name as tls_name
from heist.infrastructure.tls import TLSIdentityAdapter
import uuid
import requests
from .errors import ApiError

OPERATIONS = {
    'parse_challenge_yaml': ('POST','/admin/challenges/parse-yaml',15),
    'health': ('GET','/health/ready',10),
    'delete_artifact': ('POST', '/artifacts/retire', 120),
    'operations': ('GET', '/admin/operations', 12),
    'start': ('POST', '/launch-challenge', 1200),
    'stop': ('POST', '/stop-challenge', 300),
    'import_templates': ('POST', '/import-machine-templates', 1200),
    'delete_templates': ('POST', '/delete-machine-templates', 300),
    'delete_vpn': ('POST', '/delete-user-config', 120),
    'vpn': ('POST', '/get-user-config', 120),
}


class ImageRejected(ApiError):
    def __init__(self, code, message):
        super().__init__(message, 422)
        self.code = code


def response_bytes(response):
    data=bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        data.extend(chunk)
        if len(data)>2*1024**2:
            raise ApiError('The platform response exceeded its size limit',503)
    return bytes(data)


class InternalClient:
    def __init__(self, origin, token, *, certificate=True, server_name=None, session=None):
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
        if server_name is not None:
            self.session.mount(self.origin+'/',TLSIdentityAdapter(tls_name(server_name)))
        self.operation_ids = {}

    @classmethod
    def from_environment(cls,values=None):
        values=os.environ if values is None else values
        host=values.get('BACKEND_HOST','localhost')
        if ':' in host and not host.startswith('['):
            host='['+host+']'
        return cls('https://'+host+':'+values.get('BACKEND_PORT','8000'),
                   values.get('BACKEND_AUTHENTICATION_TOKEN'),
                   certificate=values.get('HEIST_BACKEND_CA_FILE') or True,
                   server_name=values.get('HEIST_BACKEND_SERVER_NAME'))

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
                if operation=='delete_artifact' and response.status_code==409:
                    rejected=json.loads(response_bytes(response))
                    if rejected.get('code')=='image_conflict' and isinstance(rejected.get('message'),str) and len(rejected['message'])<=500:
                        raise ApiError(rejected['message'],409)
                if operation == 'parse_challenge_yaml' and response.status_code == 400:
                    rejected = json.loads(response_bytes(response))
                    message = rejected.get('error') if isinstance(rejected,dict) else None
                    raise ApiError(message if isinstance(message,str) and len(message)<=300 else 'Invalid YAML document',400)
                if not 200 <= response.status_code < 300:
                    raise ApiError('The platform operation could not be completed. Check its status before retrying.', 503)
                data = response_bytes(response)
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

    def artifact_request(self, owner, identifier, action, *, payload=None, index=None, data=None):
        if type(owner) is not int or not 0<owner<2**63 or not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):
            raise ValueError('Invalid artifact transfer identity')
        suffix={'init':'','status':'','seal':'/seal','publish':'/publish','chunk':'/chunks/'}
        if action not in suffix:
            raise ValueError('Unsupported artifact action')
        method='GET' if action=='status' else 'PUT' if action=='chunk' else 'POST'
        endpoint='/artifacts/'+str(owner)+'/'+identifier+suffix[action]
        options={'json':payload}
        headers={'Authentication-Token':self.token,'Accept':'application/json'}
        if action=='chunk':
            if type(index) is not int or index<0 or not isinstance(data,bytes) or not 0<len(data)<=4*1024**2:
                raise ValueError('Invalid artifact chunk')
            endpoint+=str(index)
            options={'data':data}
            headers['Content-Type']='application/octet-stream'
        try:
            response=self.session.request(method,self.origin+endpoint,headers=headers,
                verify=self.certificate,timeout=(3,1830 if action=='publish' else 120),
                allow_redirects=False,stream=True,**options)
            try:
                value=json.loads(response_bytes(response))
                if not isinstance(value,dict):
                    raise ValueError('Invalid image response')
                if 200<=response.status_code<300 and value.get('success') is True and isinstance(value.get('data'),dict):
                    return value['data']
                if response.status_code in (400,403,409,422) and value.get('code') in ('image_conflict','invalid_image'):
                    message=value.get('message')
                    raise ImageRejected(value['code'],message if isinstance(message,str) and len(message)<=500 else 'Image validation failed')
                raise ApiError('Image operation is unavailable or still running; its identity is retained for reconciliation',503)
            finally:
                response.close()
        except (requests.RequestException,ValueError):
            raise ApiError('Image transfer is temporarily unavailable; its identity is retained for retry',503) from None

    def close(self):
        self.session.close()
