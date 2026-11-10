"""Authenticated, bounded read probes for Grafana and telemetry storage."""
from datetime import datetime, timezone
import ipaddress
from pathlib import Path
import re

import requests

from heist.infrastructure.tls import PinnedCertificateAdapter
from .health import check

TITLES = ('Suricata VPN Dashboard', 'Suricata DMZ Dashboard', 'Suricata BACKEND Dashboard',
          'Zeek Network Monitoring Dashboard', 'System Monitoring', 'Systemd Services Monitoring')


class HTTPS:
    def __init__(self, settings, prefix, port, *, session=None):
        host = settings.get('MONITORING_HOST', '')
        try:
            address = ipaddress.ip_address(host)
            host = '['+str(address)+']' if address.version == 6 else str(address)
        except ValueError:
            if not host or any(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) is None for part in host.split('.')):
                raise ValueError('Invalid monitoring host') from None
        port = settings.get('CLICKHOUSE_HTTPS_PORT' if prefix == 'CLICKHOUSE' else prefix+'_PORT', str(port))
        if not str(port).isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid monitoring port')
        self.origin = 'https://'+host+':'+str(port)
        self.certificate = settings.get(prefix+'_CA_FILE') or True
        if self.certificate is not True and (not Path(self.certificate).is_absolute() or '..' in Path(self.certificate).parts):
            raise ValueError('Use an absolute CA file')
        pinned = settings.get(prefix+'_PINNED_CERTIFICATE_FILE')
        adapter = PinnedCertificateAdapter(pinned) if pinned else None
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.auth = (settings[prefix+'_USER'], settings[prefix+'_PASSWORD'])
        if pinned:
            self.session.mount(self.origin+'/', adapter)
            self.certificate = pinned

    def get(self, path, *, params=None):
        response = self.session.get(self.origin+path, params=params, verify=self.certificate,
                                    allow_redirects=False, timeout=(3, 5), stream=True)
        try:
            if response.status_code != 200:
                raise RuntimeError('Monitoring query was not confirmed')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError('Oversized monitoring response')
            import json
            return json.loads(data)
        finally:
            response.close()

    def close(self):
        self.session.close()


def grafana(settings, *, client_factory=HTTPS):
    if not settings.get('GRAFANA_USER') or not settings.get('GRAFANA_PASSWORD'):
        return [check('monitoring.grafana.api', 'Grafana API', 'unknown', 'Configure authenticated Grafana HTTPS access')]
    client = None
    try:
        client = client_factory(settings, 'GRAFANA', 3000)
        health = client.get('/api/health')
        if not isinstance(health, dict) or health.get('database') != 'ok':
            raise ValueError('Grafana database is unavailable')
        dashboards = client.get('/api/search', params={'type': 'dash-db', 'limit': 100})
        if not isinstance(dashboards, list) or len(dashboards) >= 100:
            raise ValueError('Invalid or incomplete dashboard inventory')
        names = {item.get('title') for item in dashboards if isinstance(item, dict)}
        missing = len(set(TITLES)-names)
        return [check('monitoring.grafana.api', 'Grafana API', 'ok', 'Authenticated HTTPS and Grafana database health confirmed'),
                check('monitoring.grafana.expected', 'Expected Grafana dashboards', 'failed' if missing else 'ok',
                      f'{6-missing} of 6 expected dashboards present; panel query correctness still requires a canary')]
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, requests.RequestException):
        return [check('monitoring.grafana.api', 'Grafana API', 'failed', 'HTTPS, authentication or dashboard inventory was not confirmed')]
    finally:
        if client is not None:
            client.close()


def clickhouse(settings, *, client_factory=HTTPS, now=None):
    """Read fresh sensor stats from the sink, without fetching student events.

    This establishes heartbeat ingestion only, not complete mirror/packet delivery.
    """
    if not settings.get('CLICKHOUSE_USER') or not settings.get('CLICKHOUSE_PASSWORD'):
        return [check('monitoring.clickhouse.api', 'ClickHouse ingestion', 'unknown', 'Configure authenticated ClickHouse HTTPS access')]
    now = now or datetime.now(timezone.utc)
    client = None
    try:
        client = client_factory(settings, 'CLICKHOUSE', 8443)
        result = []
        for role in ('vpn', 'dmz', 'backend'):
            # Table identifiers are fixed constants; users cannot supply SQL.
            query = ('SELECT count() AS samples, max(toUnixTimestamp(timestamp)) AS latest '
                     'FROM suricata.'+role+"_eve_logs WHERE event_type='stats' "
                     'AND timestamp >= now()-INTERVAL 5 MINUTE FORMAT JSONEachRow')
            # The response is one JSON object because the aggregate has no GROUP BY.
            # Match HTTP GET's readonly mode while allowing bounded query settings.
            # Use a SELECT-only account; readonly=2 is not a privilege boundary.
            row = client.get('/', params={'query': query, 'readonly': 2, 'max_execution_time': 3,
                                          'max_result_rows': 1, 'max_result_bytes': 1024})
            if not isinstance(row, dict) or not str(row.get('samples', '')).isdigit() or not str(row.get('latest', '')).isdigit():
                raise ValueError('Invalid ingestion result')
            samples, latest = int(row['samples']), int(row['latest'])
            fresh = samples > 0 and -30 <= now.timestamp()-latest <= 180
            result.append(check('monitoring.clickhouse.'+role, 'ClickHouse '+role+' heartbeat', 'ok' if fresh else 'failed',
                                'Recent sensor statistics reached ClickHouse; packet completeness is unverified' if fresh else 'No recent sensor heartbeat reached this table; inspect sensor, shipper and sink'))
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, requests.RequestException):
        return [check('monitoring.clickhouse.api', 'ClickHouse ingestion', 'failed', 'Authenticated, read-only ingestion query was not confirmed')]
    finally:
        if client is not None:
            client.close()
