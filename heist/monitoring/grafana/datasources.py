"""Reconcile the Wazuh source without replacing its UID or disabling TLS."""
import ipaddress
from pathlib import Path
import re


def update_wazuh(session, origin, settings):
    host = str(ipaddress.ip_address(settings['MONITORING_HOST']))
    host = '['+host+']' if ':' in host else host
    port = int(settings.get('WAZUH_MANAGER_PORT', '9200'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid indexer port')
    ca = Path(settings['WAZUH_INDEXER_CA_FILE'])
    if not ca.is_absolute() or ca.is_symlink() or '..' in ca.parts or ca.stat().st_size > 65536:
        raise ValueError('Use a bounded trusted indexer CA file')
    pem = ca.read_text()
    if 'PRIVATE KEY' in pem or '-----BEGIN CERTIFICATE-----' not in pem:
        raise ValueError('Provide only the public indexer CA certificate')
    user, password = settings['WAZUH_INDEXER_USER'], settings['WAZUH_INDEXER_PASSWORD']
    if not user or not password:
        raise ValueError('Configure indexer reader credentials')
    configuration = {'index': 'wazuh-alerts-*', 'timeField': 'timestamp',
                     'tlsSkipVerify': False, 'tlsAuth': False, 'tlsAuthWithCACert': True}
    if settings.get('WAZUH_INDEXER_SERVER_NAME'):
        from heist.security.tls import server_name
        configuration['serverName'] = server_name(settings['WAZUH_INDEXER_SERVER_NAME'])
    payload = {'name': 'Wazuh-2', 'type': 'elasticsearch', 'access': 'proxy',
               'url': 'https://'+host+':'+str(port), 'database': 'wazuh-alerts-*',
               'basicAuth': True, 'basicAuthUser': user, 'jsonData': configuration,
               'secureJsonData': {'basicAuthPassword': password, 'tlsCACert': pem}}
    existing = session.get(origin+'/api/datasources/name/Wazuh-2')
    try:
        if existing.status_code == 200:
            value = existing.json()
            uid = value.get('uid')
            if value.get('name') != 'Wazuh-2' or value.get('type') != 'elasticsearch' or not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', uid):
                raise ValueError('Unexpected existing Wazuh source')
            if not isinstance(value.get('jsonData', {}), dict):
                raise ValueError('Unexpected existing source configuration')
            payload['jsonData'] = {**value.get('jsonData', {}), **configuration}
            payload['isDefault'] = value.get('isDefault') is True
            if type(value.get('version')) is int:payload['version'] = value['version']
            payload['uid'] = uid
            response = session.put(origin+'/api/datasources/uid/'+uid, json=payload)
        elif existing.status_code == 404:
            response = session.post(origin+'/api/datasources', json=payload)
        else:
            raise RuntimeError('Grafana source lookup was not confirmed')
    finally:
        existing.close()
    try:
        if response.status_code not in (200, 201):
            raise RuntimeError('Grafana source update was not confirmed')
        uid = response.json().get('datasource', {}).get('uid')
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', uid):
            raise ValueError('Updated Grafana source UID was not confirmed')
        if 'uid' in payload and uid != payload['uid']:
            raise ValueError('Grafana source UID changed')
        return uid
    finally:
        response.close()
