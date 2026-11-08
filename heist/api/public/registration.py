"""Public registration settings; the lecture token never leaves the server."""
import hashlib
import json
from urllib.parse import urlsplit


def legal_settings(config):
    def url(key):
        value = config.get(key,'')
        if not isinstance(value,str) or len(value)>1024 or any(ord(c)<=32 for c in value):
            return ''
        try:
            parsed=urlsplit(value)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                return ''
            parsed.port
        except ValueError:
            return ''
        return value
    imprint,privacy,terms=url('IMPRINT_URL'),url('PRIVACY_URL'),url('TERMS_URL')
    revision=config.get('LEGAL_VERSION','')
    revision=revision if isinstance(revision,str) and 0<len(revision)<=128 else ''
    version=hashlib.sha256(json.dumps([revision,terms,privacy],ensure_ascii=True).encode()).hexdigest() if revision and terms and privacy else ''
    return {'imprint_url':imprint,'privacy_url':privacy,'terms_url':terms,'version':version}


def registration_enabled(config):
    token=config.get('LECTURE_SIGNUP_TOKEN')
    return bool(config.get('REGISTRATION_ENABLED') is True and isinstance(token,str) and token and len(token)<=256
                and token not in ('secret','dummy-token') and legal_settings(config)['version'])
