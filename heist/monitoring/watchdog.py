"""Off-host health observer. Never depends on the heiST HTTP API or UI."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess

from heist.remote import SSH
from .health import JOBS, LIMIT, ROLE_UNITS, check, publish, sanitize

REQUIRED = tuple(role+'.service.'+unit for role, units in ROLE_UNITS.items() for unit in units if unit not in JOBS)+(
    'monitoring.wazuh.manager', 'monitoring.wazuh.indexer', 'monitoring.wazuh.dashboard',
    'monitoring.grafana.dashboards', 'database.connections', 'host.proxmox.storage',
    'host.backup.database', 'monitoring.prometheus.targets')


def evaluate(body, *, now=None):
    """Unknown coverage remains unknown; missing critical service evidence fails."""
    now = now or datetime.now(timezone.utc)
    try:
        if len(body) > LIMIT:
            raise ValueError('Oversized source receipt')
        source = sanitize(json.loads(body), now=now)
        if source['status'] == 'stale':
            raise ValueError('Stale source receipt')
        states = {item['id']: item['state'] for item in source['checks']}
        missing = sum(states.get(name) not in ('ok', 'warning') for name in REQUIRED)
        failed = sum(item['state'] == 'failed' for item in source['checks'])
        unknown = sum(item['state'] == 'unknown' for item in source['checks'])
        critical = bool(missing or failed)
        state = 'failed' if critical else 'unknown' if unknown else 'warning' if source['status'] == 'warning' else 'ok'
        summary = f'{failed} failed source checks; {missing} critical services unverified; {unknown} checks unknown'
        checks = [check('watchdog.source', 'Platform heartbeat', 'ok', 'Fresh source receipt obtained over pinned SSH'),
                  check('watchdog.platform', 'Observed platform health', state, summary)]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        critical = True
        checks = [check('watchdog.source', 'Platform heartbeat', 'failed', 'Source receipt is unavailable, invalid, stale or has an invalid clock')]
    return {'schema': 1, 'checked_at': now.isoformat(), 'checks': checks}, critical


def observe(config, credentials, *, run=subprocess.run, now=None):
    if not isinstance(config, dict) or set(config) != {'schema', 'host', 'user', 'status_file'} or config['schema'] != 1:
        raise ValueError('Invalid watchdog configuration')
    SSH(config['host'], config['user'])  # Shared host/user validation; no host-key enrollment.
    path = Path(config['status_file'])
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Use an absolute source receipt path')
    remote = shlex.join(['head', '-c', str(LIMIT+1), '--', str(path)])
    argv = ['ssh', '-T', '-F', '/dev/null', '-o', 'ForwardAgent=no', '-o', 'IdentityAgent=none',
            '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile='+str(Path(credentials)/'known_hosts'),
            '-i', str(Path(credentials)/'identity'), '-l', config['user'], '--', config['host'], remote]
    try:
        result = run(argv, capture_output=True, timeout=12, check=True)
        return evaluate(result.stdout, now=now)
    except (OSError, subprocess.SubprocessError):
        return evaluate(b'', now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    credentials = os.environ.get('CREDENTIALS_DIRECTORY')
    if not credentials:
        parser.error('Run with systemd LoadCredential identity and known_hosts')
    value, critical = observe(json.loads(args.config.read_text()), credentials)
    publish(args.output, value)
    print(json.dumps(sanitize(value)))
    return 1 if critical else 0


if __name__ == '__main__':
    raise SystemExit(main())
