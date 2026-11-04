"""Validate explicit TLS identities independently of network address selection."""
import ipaddress
import re


def server_name(value):
    if not isinstance(value,str) or not value or len(value)>253:
        raise ValueError('Configure a valid TLS server name')
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in value.split('.')):
            raise ValueError('Configure a valid TLS server name') from None
    return value
