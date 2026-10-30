"""Local PVE HTTPS requests return asynchronous UPIDs instead of CLI worker waits.

Root signs an ordinary short-lived PVE ticket with PVE's installed signer. The
cookie/CSRF token stay in process memory and are sent only after certificate
pinning. No passwords, API tokens or new dependencies are required.
"""
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import ssl
import subprocess
from urllib.parse import urlencode


class LocalAPI:
    def __init__(self):
        custom = Path('/etc/pve/local/pveproxy-ssl.pem')
        self.certificate = custom if custom.is_file() else Path('/etc/pve/local/pve-ssl.pem')

    def credentials(self):
        program = (
            'PVE::Cluster::cfs_update(); '
            'print encode_json({ticket=>PVE::AccessControl::assemble_ticket(q{root@pam}),'
            'csrf=>PVE::AccessControl::assemble_csrf_prevention_token(q{root@pam})});'
        )
        result = subprocess.run(['perl', '-MPVE::Cluster', '-MPVE::AccessControl', '-MJSON',
                                 '-e', program], check=True, capture_output=True, timeout=15)
        return json.loads(result.stdout)

    def request(self, method, path, arguments):
        if method not in ('GET', 'POST') or not path.startswith('/nodes/'):
            raise ValueError('Only node-scoped GET/POST operations are supported')
        credentials = self.credentials()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = http.client.HTTPSConnection('127.0.0.1', 8006, context=context, timeout=60)
        try:
            connection.connect()
            expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.certificate.read_text())).digest()
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()
            if not hmac.compare_digest(actual, expected):
                raise ssl.SSLError('Local Proxmox certificate differs from installed certificate')
            body = urlencode(arguments or {})
            endpoint = '/api2/json' + path
            if method == 'GET' and body:
                endpoint += '?' + body
                body = ''
            connection.request(method, endpoint, body=body, headers={
                'Cookie': 'PVEAuthCookie=' + credentials['ticket'],
                'CSRFPreventionToken': credentials['csrf'],
                'Content-Type': 'application/x-www-form-urlencoded',
            })
            response = connection.getresponse()
            payload = response.read(4 * 1024**2)
            if response.status != 200:
                # API error bodies may include private configuration. Keep them out
                # of generic exception traces; inspect the local PVE log instead.
                raise RuntimeError('Local Proxmox API returned HTTP ' + str(response.status))
            result = json.loads(payload)
            if 'data' not in result:
                raise RuntimeError('Missing local Proxmox API result')
            return result['data']
        finally:
            connection.close()
