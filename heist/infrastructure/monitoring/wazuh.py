"""Bounded, certificate-verified Wazuh agent cleanup."""
import ipaddress
import json
from pathlib import Path
import re

import requests
from heist.infrastructure.tls import PinnedCertificateAdapter


class Wazuh:
    def __init__(self, host, port, username, password, *, certificate=True, pinned_certificate=None, session=None):
        if not isinstance(host, str) or not host:
            raise ValueError('Configure the monitoring API host')
        try:
            address = ipaddress.ip_address(host.strip('[]'))
            host = '['+str(address)+']' if address.version == 6 else str(address)
        except ValueError:
            if len(host) > 253 or any(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) is None for label in host.split('.')):
                raise ValueError('Invalid monitoring API host') from None
        if isinstance(port, bool) or not str(port).isascii() or not str(port).isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid monitoring API port')
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise ValueError('Configure monitoring API credentials')
        if certificate is not True and (not isinstance(certificate, str) or not Path(certificate).is_absolute() or '..' in Path(certificate).parts):
            raise ValueError('Monitoring API TLS requires verification or an absolute CA file')
        self.origin = 'https://'+host+':'+str(int(port))
        self.credentials = (username, password)
        self.certificate = pinned_certificate if pinned_certificate and certificate is True else certificate
        self.session = session or requests.Session()
        self.session.trust_env = False
        if pinned_certificate is not None:
            self.session.mount(self.origin+'/',PinnedCertificateAdapter(pinned_certificate))

    def call(self, method, path, *, raw=False, **options):
        try:
            response = self.session.request(method, self.origin+path, verify=self.certificate, timeout=(3, 10),
                                             allow_redirects=False, stream=True, **options)
            try:
                if response.status_code != 200:
                    raise RuntimeError('Monitoring API operation was not confirmed')
                data = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > (8192 if raw else 2*1024*1024):
                        raise RuntimeError('Monitoring API response exceeded its limit')
                if raw:
                    return data.decode('ascii').strip()
                result = json.loads(data)
                if not isinstance(result, dict) or result.get('error') != 0 or not isinstance(result.get('data'), dict):
                    raise RuntimeError('Monitoring API result was not confirmed')
                return result['data']
            finally:
                response.close()
        except (requests.RequestException, ValueError, UnicodeError):
            raise RuntimeError('Monitoring API is unavailable or returned an invalid response') from None

    def remove_agent(self, machine_id):
        if isinstance(machine_id, bool) or not isinstance(machine_id, int) or not 0 < machine_id < 2**31:
            raise ValueError('Invalid guest machine identifier')
        token = self.call('POST', '/security/user/authenticate', raw=True, auth=self.credentials, params={'raw': 'true'})
        if re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token) is None:
            raise RuntimeError('Monitoring API authentication was not confirmed')
        headers = {'Authorization': 'Bearer '+token}
        name = 'agent_'+str(machine_id)
        result = self.call('GET', '/agents', headers=headers, params={'name': name})
        agents = result.get('affected_items')
        if not isinstance(agents, list) or result.get('total_failed_items', 0) != 0:
            raise RuntimeError('Monitoring agent inventory was not confirmed')
        if not agents:
            return True
        if len(agents) != 1 or not isinstance(agents[0], dict) or agents[0].get('name') != name:
            raise RuntimeError('Monitoring returned an unexpected agent identity')
        agent_id = str(agents[0].get('id', ''))
        if not agent_id.isascii() or not agent_id.isdigit() or not 0 < int(agent_id) < 2**31:
            raise RuntimeError('Monitoring returned an invalid agent identifier')
        result = self.call('DELETE', '/agents', headers=headers, params={'agents_list': agent_id, 'status': 'all', 'older_than': '0s'})
        removed = result.get('affected_items')
        if not isinstance(removed, list) or result.get('total_failed_items', 0) != 0 or agent_id not in [str(item) for item in removed]:
            raise RuntimeError('Monitoring agent deletion was not confirmed')
        return True

    def close(self):
        self.session.close()
