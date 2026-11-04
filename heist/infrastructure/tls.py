"""Explicit HTTPS peer identity while retaining certificate verification."""
import hashlib
from pathlib import Path
import re
import ssl

import requests

from heist.security.tls import server_name as validate_name


class TLSIdentityAdapter(requests.adapters.HTTPAdapter):
    def __init__(self,server_name):
        self.server_name=validate_name(server_name)
        super().__init__()

    def init_poolmanager(self,*args,**kwargs):
        kwargs.update(assert_hostname=self.server_name,server_hostname=self.server_name)
        return super().init_poolmanager(*args,**kwargs)


class PinnedCertificateAdapter(requests.adapters.HTTPAdapter):
    """Trust a leaf obtained over a separately authenticated administration channel."""
    def __init__(self,certificate):
        path=Path(certificate)
        if not path.is_absolute() or '..' in path.parts or path.is_symlink():
            raise ValueError('Use an absolute trusted certificate file')
        if path.stat().st_size>65536:
            raise ValueError('Pinned certificate file exceeds size limit')
        match=re.search(r'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----',path.read_text())
        if not match:
            raise ValueError('Pinned certificate is not PEM')
        self.fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(match[0])).hexdigest()
        super().__init__()

    def init_poolmanager(self,*args,**kwargs):
        # Fingerprint authenticates the exact installed leaf even for legacy
        # service certificates without SANs. CA/expiry verification stays on.
        kwargs.update(assert_hostname=False,assert_fingerprint=self.fingerprint)
        return super().init_poolmanager(*args,**kwargs)
