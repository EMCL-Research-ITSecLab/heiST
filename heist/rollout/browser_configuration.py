"""Whitelist web-role configuration; privileged host settings never travel with it."""
import json
from pathlib import Path
import re

from heist.security.tls import server_name
from heist import legal
from .browser_role import validate

KEYS = frozenset(('DB_HOST','DB_NAME','DB_PORT','DB_USER','DB_PASSWORD',
                  'WEB_SESSION_SECRET','BACKEND_HOST','BACKEND_PORT',
                  'BACKEND_AUTHENTICATION_TOKEN','HEIST_BACKEND_CA_FILE',
                  'HEIST_BACKEND_SERVER_NAME','HEIST_WEB_DATA_ROOT',
                  'HEIST_WEB_MAINTENANCE_FILE','HEIST_WEB_PORT','LECTURE_SIGNUP_TOKEN',
                  'HEIST_IMPRINT_URL','HEIST_PRIVACY_URL','HEIST_TERMS_URL','HEIST_LEGAL_VERSION','HEIST_REGISTRATION_ENABLED'))


def configuration(host, *, role, password, session_secret, backend_server_name,
                  ca_file='/etc/heist/backend-ca.crt'):
    validate(role,password)
    if not isinstance(session_secret,str) or re.fullmatch('[a-f0-9]{64}',session_secret) is None:
        raise ValueError('Use a persistent generated browser session secret')
    path=Path(ca_file)
    if not path.is_absolute() or '..' in path.parts or str(path)!=ca_file:
        raise ValueError('Use a normalized trusted backend CA path')
    values={'DB_HOST':server_name(host['DB_HOST']),'DB_NAME':host['DB_NAME'],
            'DB_USER':role,'DB_PASSWORD':password,'DB_PORT':host.get('DB_PORT','5432'),
            'BACKEND_HOST':server_name(host.get('BACKEND_HOST','10.0.0.1')),
            'BACKEND_PORT':host.get('BACKEND_PORT','8000'),
            'BACKEND_AUTHENTICATION_TOKEN':host['BACKEND_AUTHENTICATION_TOKEN'],
            'HEIST_BACKEND_SERVER_NAME':server_name(backend_server_name),
            'HEIST_BACKEND_CA_FILE':ca_file,'WEB_SESSION_SECRET':session_secret,
            'HEIST_WEB_DATA_ROOT':'/var/lib/heist-web',
            'HEIST_WEB_MAINTENANCE_FILE':'/run/heist-web-maintenance','HEIST_WEB_PORT':'8001',
            'LECTURE_SIGNUP_TOKEN':host.get('LECTURE_SIGNUP_TOKEN',''),
            'HEIST_IMPRINT_URL':host.get('HEIST_IMPRINT_URL',legal.IMPRINT_URL), 'HEIST_PRIVACY_URL':host.get('HEIST_PRIVACY_URL',legal.PRIVACY_URL),
            'HEIST_TERMS_URL':host.get('HEIST_TERMS_URL',legal.TERMS_URL),
            'HEIST_LEGAL_VERSION':host.get('HEIST_LEGAL_VERSION',legal.LEGAL_VERSION),
            'HEIST_REGISTRATION_ENABLED':host.get('HEIST_REGISTRATION_ENABLED','true')}
    for key in ('DB_PORT','BACKEND_PORT'):
        port=values[key]
        if not isinstance(port,str) or not port.isascii() or not port.isdigit() or not 1<=int(port)<=65535:
            raise ValueError('Invalid service port')
    if not values['DB_NAME'] or not values['BACKEND_AUTHENTICATION_TOKEN']:
        raise ValueError('Declare browser database and internal service authentication')
    serialize(values)
    return values


def serialize(values):
    if set(values)!=KEYS:
        raise ValueError('Browser configuration must contain only its declared role settings')
    for value in values.values():
        if not isinstance(value,str) or len(value)>1024 or any(ord(character)<32 or ord(character)==127 for character in value):
            raise ValueError('Invalid browser environment value')
    # EnvironmentFile double quotes retain literal dollars/backticks. No shell
    # evaluates this file; only quotes/backslashes require escaping here.
    return ''.join(key+'='+json.dumps(values[key],ensure_ascii=False)+'\n' for key in sorted(values))


REGISTRATION_KEYS = frozenset(('LECTURE_SIGNUP_TOKEN', 'HEIST_IMPRINT_URL',
    'HEIST_PRIVACY_URL', 'HEIST_TERMS_URL', 'HEIST_LEGAL_VERSION', 'HEIST_REGISTRATION_ENABLED'))


def preserved_registration_settings(installation, host, checkpoint_hashes):
    """Carry only missing browser registration settings from the saved installer.

    Legacy backend environments omit the lecture token. Explicit backend values,
    including an empty token or disabled registration, always take precedence.
    Read only a source whose bytes are already bound to the recovery checkpoint.
    """
    from dotenv import dotenv_values
    from heist.files import sha256
    missing = REGISTRATION_KEYS - host.keys()
    if not missing:
        return {}
    root = Path(installation)
    for path in (root/'config/installer.env', root/'setup/.env'):
        if path.is_symlink() or path.parent.is_symlink():
            raise RuntimeError('Installer configuration must not use symlinks')
        if not path.exists():
            continue
        if not path.is_file() or checkpoint_hashes.get(str(path)) != sha256(path):
            raise RuntimeError('Installer configuration differs from the recovery checkpoint')
        values = dotenv_values(path, interpolate=False)
        result = {key: values[key] for key in missing if values.get(key) is not None}
        if any(not isinstance(value, str) or len(value) > 1024 or
               any(ord(character) < 32 or ord(character) == 127 for character in value)
               for value in result.values()):
            raise ValueError('Invalid preserved browser registration setting')
        return result
    return {}


def legacy_database_role(installation, host, checkpoint_hashes=None):
    """Read only the dedicated role name from the reviewed installer settings."""
    from dotenv import dotenv_values
    from heist.files import sha256
    from .browser_role import validate_legacy
    root=Path(installation)
    for path in (root/'config/installer.env',root/'setup/.env'):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise RuntimeError('Legacy installer settings must not use symlinks')
        if not path.exists():continue
        if not path.is_file() or (checkpoint_hashes is not None and checkpoint_hashes.get(str(path))!=sha256(path)):
            raise RuntimeError('Legacy installer settings differ from the checkpoint')
        name=dotenv_values(path,interpolate=False).get('WEBSERVER_DATABASE_USER')
        validate_legacy(name)
        if name==host.get('DB_USER'):
            raise RuntimeError('Legacy PHP must use a database role distinct from the backend')
        return name
    raise RuntimeError('Require reviewed legacy PHP database-role settings before migration')
