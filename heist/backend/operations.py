"""Read-only operator diagnostics. No shell commands or deployment controls from HTTP input."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

from heist.remote import SSH

UNITS = ('backend.service', 'pool_manager.service', 'cleanup.service')
ROOT = Path(__file__).resolve().parents[2]


def service_states(run=subprocess.run):
    try:
        result = run(['systemctl', 'show', '--property=Id,ActiveState,SubState', *UNITS],
                     check=True, capture_output=True, text=True, timeout=3)
        found = {}
        for group in result.stdout.strip().split('\n\n'):
            values = dict(line.split('=', 1) for line in group.splitlines() if '=' in line)
            if values.get('Id') in UNITS:
                found[values['Id']] = {'unit': values['Id'], 'state': values.get('ActiveState', 'unknown'),
                                        'detail': values.get('SubState', 'unknown')}
        return [found.get(unit, {'unit': unit, 'state': 'unknown', 'detail': 'unavailable'}) for unit in UNITS]
    except (OSError, subprocess.SubprocessError):
        return [{'unit': unit, 'state': 'unknown', 'detail': 'unavailable'} for unit in UNITS]


def release_status(directory):
    """Exclude checkpoint locations, request payloads, credentials and failure logs."""
    result = {'version': 'unknown', 'commit': None, 'active_transaction': None}
    installed = Path(directory)/'installed.json'
    try:
        if installed.stat().st_size > 65536:
            raise ValueError('Oversized release receipt')
        value = json.loads(installed.read_text())
        version, commit = value.get('version'), value.get('commit')
        if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
            result['version'] = version
        if isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{40}', commit):
            result['commit'] = commit
    except (OSError, ValueError, TypeError):
        pass
    try:
        pointer = json.loads((Path(directory)/'active.json').read_text())['transaction']
        if isinstance(pointer, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', pointer):
            result['active_transaction'] = pointer
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def archive_status(settings, *, now=None, read_remote=None):
    """Read a bounded receipt from the separate archive VM over pinned SSH."""
    host = settings.get('HEIST_ARCHIVE_STATUS_HOST')
    remote = settings.get('HEIST_ARCHIVE_STATUS_FILE')
    if not host or not remote:
        return {'status': 'not configured', 'last_success_at': None}
    try:
        if not Path(remote).is_absolute() or '..' in Path(remote).parts:
            raise ValueError('Invalid archive status path')
        if read_remote is None:
            def read_remote():
                return SSH(host, settings.get('HEIST_ARCHIVE_STATUS_USER', 'heist-archive')).run(
                    ['head', '-c', '65537', '--', remote], timeout=5).stdout
        body = read_remote()
        if len(body) > 65536:
            raise ValueError('Oversized archive receipt')
        data = json.loads(body)
        if data.get('schema') != 1 or data.get('status') not in ('running', 'failed', 'success'):
            raise ValueError('Unsupported archive receipt')
        now = now or datetime.now(timezone.utc)
        updated = datetime.fromisoformat(data.get('completed_at') or data['started_at'])
        if updated.tzinfo is None or (updated-now).total_seconds() > 300:
            raise ValueError('Invalid archive receipt clock')
        maximum_age = int(settings.get('HEIST_ARCHIVE_MAX_AGE_SECONDS', 1800))
        if not 60 <= maximum_age <= 86400:
            raise ValueError('Invalid archive receipt age limit')
        status = 'stale' if (now-updated).total_seconds() > maximum_age else data['status']
        last_success = data.get('last_success_at')
        if last_success is not None:
            timestamp = datetime.fromisoformat(last_success)
            if timestamp.tzinfo is None or timestamp > updated:
                raise ValueError('Invalid archive success timestamp')
            last_success = timestamp.isoformat()
        counters = {key: value for key, value in data.get('counters', {}).items()
                    if key in ('copied', 'verified', 'bytes', 'removed_remote') and type(value) is int and value >= 0}
        source = data.get('source', '')
        if not isinstance(source, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', source):
            raise ValueError('Invalid archive source')
        return {'status': status, 'source': source, 'last_success_at': last_success,
                'updated_at': updated.isoformat(), 'counters': counters}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        return {'status': 'unavailable', 'last_success_at': None}


def collect(connection, settings, maintenance_file, *, services=None, archive=None):
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'database': 'unavailable',
              'maintenance': Path(maintenance_file).exists(), 'lifecycle': {},
              'services': services() if services else service_states(),
              'archive': archive() if archive else archive_status(settings),
              'release': release_status(settings.get('HEIST_STATE_DIRECTORY', '/var/lib/heist'))}
    try:
        result['source_version'] = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    except (OSError, ValueError, KeyError):
        result['source_version'] = 'unknown'
    db = None
    try:
        db = connection()
        db.set_session(readonly=True)
        with db.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '3s'")
            cursor.execute('SELECT lifecycle_state::text, count(*) FROM challenges GROUP BY lifecycle_state')
            result['lifecycle'] = {state: count for state, count in cursor.fetchall()}
        result['database'] = 'ready'
    except Exception:
        result['database'] = 'unavailable'
    finally:
        if db is not None:
            db.close()
    usage = shutil.disk_usage('/')
    result['storage'] = {'total_bytes': usage.total, 'free_bytes': usage.free, 'used_percent': round(usage.used/usage.total*100, 1)}
    return result
