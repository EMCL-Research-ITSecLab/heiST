"""TLS health probes using a locally trusted, pinned certificate before sending headers."""
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import ssl
from urllib.parse import urlsplit


def certificate_fingerprint(pem):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def probe(url, certificate, *, headers=None, statuses=(200,), expect=None, ready_json=False, timeout=10):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.fragment:
        raise ValueError('A plain HTTPS endpoint is required')
    expected=certificate_fingerprint(Path(certificate).read_text())
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Legacy heiST uses self-signed certificates without SANs. Exact leaf pinning
    # authenticates that installed certificate; the pin is never fetched over HTTP.
    context.check_hostname=False
    context.verify_mode=ssl.CERT_NONE
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    connection=http.client.HTTPSConnection(parsed.hostname,parsed.port or 443,context=context,timeout=timeout)
    try:
        connection.connect()
        actual=hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(actual,expected):
            raise ssl.SSLError('Endpoint certificate differs from the trusted installed certificate')
        connection.request('GET',parsed.path or '/',headers=headers or {})
        response=connection.getresponse()
        body=response.read(2*1024**2)
        if response.status not in statuses or (expect is not None and expect not in body):
            raise RuntimeError('Health endpoint returned an unexpected status/body')
        if ready_json and response.status == 200:
            data = json.loads(body)
            if data.get('success') is not True or data.get('status') != 'ready':
                raise RuntimeError('Backend readiness response is not ready')
        return response.status
    finally:
        connection.close()
