"""Bounded, read-only platform probes; safe to stream to an infrastructure VM.

This file uses only the standard library. Never import provisioning modules here:
some legacy installers change requests/TLS behaviour at import time.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import tempfile
import socket
import ssl
import tomllib
from urllib.parse import urlsplit


ROLE_UNITS = {
    'host': ('backend.service', 'pool_manager.service', 'cleanup.service',
             'pveproxy.service', 'pvedaemon.service', 'pvestatd.service', 'pve-cluster.service',
             'dnsmasq-backend.service', 'openvpn@server.service',
             'suricata-vpn.service', 'suricata-dmz.service', 'suricata-backend.service',
             'vector-vpn.service', 'vector-dmz.service', 'vector-backend.service', 'vector-zeek.service',
             'zeek.service', 'heist-expiry.timer', 'heist-log-prepare.timer',
             'heist-expiry.service', 'heist-log-prepare.service', 'node_exporter.service', 'prometheus-pve-exporter.service'),
    'monitoring': ('grafana-server.service', 'clickhouse-server.service', 'docker.service',
                   'prometheus.service', 'node_exporter.service', 'banner-server.service'),
    'web': ('heist-web.service', 'apache2.service', 'heist-artifacts.service', 'node_exporter.service', 'apache_exporter.service'),
    'database': ('postgresql.service', 'node_exporter.service', 'postgres_exporter.service'),
    'archive': ('heist-log-archive@database.timer', 'heist-log-archive@proxmox-logs.timer',
                'heist-log-archive@database.service', 'heist-log-archive@proxmox-logs.service'),
}
ROLES = tuple(ROLE_UNITS)
STATES = ('ok', 'warning', 'failed', 'unknown')
LIMIT = 65536
JOBS = {'heist-expiry.service', 'heist-log-prepare.service',
        'heist-log-archive@database.service', 'heist-log-archive@proxmox-logs.service'}


def check(identifier, label, state, summary):
    return {'id': identifier, 'label': label, 'state': state, 'summary': summary}


def command(arguments, *, run=subprocess.run, timeout=5):
    """Only callers choose fixed argument vectors; command output stays private."""
    try:
        result = run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
        return result if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def services(role, *, run=subprocess.run):
    units = ROLE_UNITS[role]
    try:
        # systemctl may return nonzero for a missing unit while reporting the
        # remaining units correctly. Preserve those observations.
        result = run(['systemctl', 'show', '--property=Id,LoadState,ActiveState,SubState,Result,ExecMainStartTimestamp', *units],
                     capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        result = None
    found = {}
    if result:
        for group in result.stdout.split('\n\n'):
            values = dict(line.split('=', 1) for line in group.splitlines() if '=' in line)
            if values.get('Id') in units:
                found[values['Id']] = values
    checks = []
    for unit in units:
        value = found.get(unit, {})
        active = value.get('ActiveState')
        state = 'ok' if active == 'active' and value.get('LoadState') == 'loaded' else 'failed' if active in ('inactive', 'failed') or value.get('LoadState') == 'not-found' else 'unknown'
        if unit in JOBS and active == 'inactive' and value.get('LoadState') == 'loaded' and value.get('Result') == 'success':
            state = 'ok' if value.get('ExecMainStartTimestamp') not in (None, '', 'n/a') else 'unknown'
        summary = {'ok': 'Active', 'failed': 'Required unit is stopped, failed or missing',
                   'unknown': 'Service state could not be verified'}[state]
        if state == 'ok' and unit in JOBS and active == 'inactive':
            summary = 'Last job completed successfully; timer and delivery are checked separately'
        checks.append(check(role+'.service.'+unit, unit, state, summary))
    return checks


def eve_health(role, *, root=Path('/var/log/suricata'), now=None):
    """Read only a bounded tail and return counters, never addresses or payloads.

    Stats are a heartbeat even for quiet networks. A recent flow is not proof of
    packet completeness. Old/missing stats are unknown, not a false outage.
    """
    now = now or datetime.now(timezone.utc)
    state, summary = 'unknown', 'No recent sensor statistics; ingestion and coverage are unverified'
    try:
        with (root/('eve_'+role+'.json')).open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-512*1024))
            lines = stream.read(512*1024).splitlines()
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get('event_type') != 'stats':
                    continue
                at = datetime.fromisoformat(event['timestamp'])
                if at.tzinfo is None or not -30 <= (now-at).total_seconds() <= 180:
                    break
                stats = event['stats']
                if role == 'backend' and isinstance(stats.get('ips'), dict):
                    packets = stats['decoder']['pkts']
                    if type(packets) is not int or packets < 0:
                        break
                    state = 'ok'
                    summary = f'Recent NFQUEUE stats: {packets} decoded packets. Queue loss, rule attachment and downstream ingestion remain unverified.'
                    break
                capture = stats['capture']
                packets, dropped = capture['kernel_packets'], capture['kernel_drops']
                if type(packets) is not int or type(dropped) is not int or min(packets, dropped) < 0:
                    break
                state = 'warning' if dropped else 'ok'
                summary = f'Recent stats: {packets} kernel packets; {dropped} cumulative kernel drops. Mirroring and downstream ingestion remain unverified.'
                break
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return check('host.eve.'+role, 'Suricata '+role+' heartbeat', state, summary)


def capture_configuration(*, root=Path('/etc/suricata')):
    """The generated AF_PACKET sensors must use distinct fanout groups."""
    import re
    try:
        groups = []
        for filename in ('suricata-ctf.yaml', 'suricata-dmz.yaml'):
            body = (root/filename).read_text()
            values = re.findall(r'^\s*cluster-id:\s*(\d+)\s*(?:#.*)?$', body, re.MULTILINE)
            if not values:
                raise ValueError('No fanout group')
            groups.append(set(values))
        collision = bool(groups[0] & groups[1])
        return check('host.capture.fanout', 'Suricata capture configuration', 'failed' if collision else 'ok',
                     'VPN and DMZ reuse a fanout group; check generated configuration' if collision else 'VPN and DMZ fanout groups are distinct; runtime capture still requires a canary')
    except (OSError, ValueError):
        return check('host.capture.fanout', 'Suricata capture configuration', 'unknown', 'Capture configuration could not be verified')


def sensor_interfaces(*, config_root=Path('/etc/suricata'), net_root=Path('/sys/class/net')):
    import re
    checks = []
    for role, filename in (('vpn', 'suricata-ctf.yaml'), ('dmz', 'suricata-dmz.yaml')):
        state, summary = 'unknown', 'Configured capture interface could not be verified'
        try:
            names = set(re.findall(r'^\s*-\s*interface:\s*([A-Za-z0-9_.:-]{1,15})\s*(?:#.*)?$',
                                   (config_root/filename).read_text(), re.MULTILINE))
            if len(names) == 1:
                flags = int((net_root/names.pop()/'flags').read_text().strip(), 16)
                state = 'ok' if flags & 1 else 'failed'
                summary = 'Capture interface exists and is administratively up; mirror delivery is unverified' if flags & 1 else 'Capture interface is administratively down'
        except FileNotFoundError:
            state, summary = 'failed', 'Capture configuration or its interface is missing'
        except (OSError, ValueError):
            pass
        checks.append(check('host.interface.'+role, 'Suricata '+role+' interface', state, summary))
    return checks


def dashboards(path=Path('/var/lib/grafana/grafana.db')):
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2) as db:
            db.execute('PRAGMA query_only=ON')
            count = db.execute('SELECT count(*) FROM dashboard WHERE is_folder=0').fetchone()[0]
        return check('monitoring.grafana.dashboards', 'Grafana dashboards', 'ok' if count else 'failed',
                     f'{count} dashboards stored; data-source queries still require validation' if count else 'No dashboards stored; provision and verify the expected dashboards')
    except (OSError, ValueError, sqlite3.Error):
        return check('monitoring.grafana.dashboards', 'Grafana dashboards', 'unknown', 'Dashboard inventory could not be verified')


def containers(*, run=subprocess.run):
    result = command(['docker', 'ps', '--all', '--format', '{{.Names}}\t{{.State}}\t{{.Status}}'], run=run)
    rows = [line.split('\t') for line in result.stdout.splitlines()] if result else []
    checks = []
    for component in ('manager', 'indexer', 'dashboard'):
        matches = [r for r in rows if len(r) == 3 and r[0] == 'single-node-wazuh.'+component+'-1']
        state = 'unknown' if result is None else 'failed'
        if len(matches) == 1 and matches[0][1] == 'running' and '(unhealthy)' not in matches[0][2] and '(health: starting)' not in matches[0][2]:
            state = 'ok'
        checks.append(check('monitoring.wazuh.'+component, 'Wazuh '+component, state,
                            'Container running; API and event delivery require separate checks' if state == 'ok' else 'Required Wazuh container is missing, stopped, unhealthy or unverified'))
    return checks


def resources(role, *, proc=Path('/proc'), statvfs=os.statvfs, load=os.getloadavg, cpus=os.cpu_count):
    checks = []
    try:
        info = {line.split(':', 1)[0]: int(line.split()[1]) for line in (proc/'meminfo').read_text().splitlines()}
        total, available = info['MemTotal'], info['MemAvailable']
        if total <= 0 or not 0 <= available <= total:
            raise ValueError('Invalid memory counters')
        percent = round((total-available)/total*100, 1)
        checks.append(check(role+'.memory', role.capitalize()+' memory', 'failed' if percent >= 95 else 'warning' if percent >= 85 else 'ok',
                            f'{percent}% unavailable according to MemAvailable; application limits need separate validation'))
    except (OSError, ValueError, KeyError, IndexError):
        checks.append(check(role+'.memory', role.capitalize()+' memory', 'unknown', 'Memory counters could not be verified'))
    try:
        usage = statvfs('/')
        if usage.f_files <= 0:
            raise ValueError('No inode accounting')
        percent = round((usage.f_files-usage.f_favail)/usage.f_files*100, 1)
        checks.append(check(role+'.inodes', role.capitalize()+' root inodes', 'failed' if percent >= 95 else 'warning' if percent >= 85 else 'ok', f'{percent}% of root filesystem inodes used'))
    except (OSError, ValueError):
        checks.append(check(role+'.inodes', role.capitalize()+' root inodes', 'unknown', 'Inode counters could not be verified'))
    try:
        average, count = load()[0], cpus()
        if not count or average < 0:
            raise ValueError('Invalid load counters')
        checks.append(check(role+'.load', role.capitalize()+' system load', 'failed' if average > count*4 else 'warning' if average > count*2 else 'ok',
                            f'One-minute load {average:.2f} on {count} CPUs; this is not a CPU utilization percentage'))
    except (OSError, ValueError):
        checks.append(check(role+'.load', role.capitalize()+' system load', 'unknown', 'System load could not be verified'))
    return checks


def prometheus_targets(*, connection=None, now=None):
    """Loopback-only query on the monitoring VM; no TLS bypass or remote URLs."""
    from http.client import HTTPConnection, HTTPException
    now = now or datetime.now(timezone.utc)
    expected = {'monitoring-vm', 'proxmox-node', 'proxmox-pve', 'apache', 'webserver-node', 'database-node', 'postgres'}
    client = connection or HTTPConnection('127.0.0.1', 9090, timeout=3)
    try:
        client.request('GET', '/api/v1/targets?state=active')
        response = client.getresponse()
        body = response.read(LIMIT+1)
        if response.status != 200 or len(body) > LIMIT:
            raise ValueError('Prometheus query not confirmed')
        value = json.loads(body)
        targets = value['data']['activeTargets']
        if value.get('status') != 'success' or not isinstance(targets, list) or len(targets) > 64:
            raise ValueError('Invalid target inventory')
        jobs, failed = set(), 0
        for target in targets:
            jobs.add(target['labels']['job'])
            at = datetime.fromisoformat(target['lastScrape'])
            if target['health'] != 'up' or at.tzinfo is None or not -30 <= (now-at).total_seconds() <= 180:
                failed += 1
        missing = len(expected-jobs)
        state = 'failed' if failed or missing else 'ok'
        summary = f'{len(targets)} active targets; {failed} down/stale; {missing} expected jobs missing. This validates scraping, not every metric or alert rule.'
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError):
        state, summary = 'failed', 'Prometheus loopback target inventory could not be verified'
    finally:
        client.close()
    return check('monitoring.prometheus.targets', 'Prometheus metric delivery', state, summary)


def proxmox_storage(*, run=subprocess.run, node=None):
    node = node or socket.gethostname().split('.')[0]
    result = command(['pvesh', 'get', '/nodes/'+node+'/storage', '--output-format', 'json'], run=run)
    try:
        if result is None or len(result.stdout) > LIMIT:
            raise ValueError('Storage inventory unavailable')
        stores = json.loads(result.stdout)
        if not isinstance(stores, list) or not 1 <= len(stores) <= 64:
            raise ValueError('Invalid storage inventory')
        stores = [store for store in stores if store.get('enabled', 1)]
        if not stores:
            raise ValueError('No enabled stores')
        inactive, maximum = 0, 0
        for store in stores:
            if store.get('active') != 1:
                inactive += 1
                continue
            used, total = store['used'], store['total']
            if type(used) is not int or type(total) is not int or used < 0 or total <= 0:
                raise ValueError('Invalid storage counters')
            maximum = max(maximum, used/total*100)
        state = 'failed' if inactive or maximum >= 95 else 'warning' if maximum >= 85 else 'ok'
        summary = f'{len(stores)} enabled stores; {inactive} inactive; highest reported data usage {maximum:.1f}%. Thin-pool metadata requires separate validation.'
    except (ValueError, KeyError, TypeError, AttributeError):
        state, summary = 'unknown', 'Proxmox storage capacity could not be verified'
    return check('host.proxmox.storage', 'Proxmox storage capacity', state, summary)


def database_backup(*, root=Path('/var/backups/heist/database'), now=None):
    """A successful empty archive run cannot hide a stopped source backup job."""
    import re
    now = now or datetime.now(timezone.utc)
    try:
        target = (root/'latest.backup').readlink()
        if (target.is_absolute() or len(target.parts) != 2 or target.name != 'database.backup'
                or not re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9_-]{1,32}-[a-f0-9]{12}', target.parts[0])):
            raise ValueError('Invalid published generation')
        generation, dump = root/target.parts[0], root/target
        metadata = generation/'metadata.json'
        if generation.is_symlink() or dump.is_symlink() or metadata.is_symlink():
            raise ValueError('Unexpected backup symlink')
        with metadata.open('rb') as stream:
            body = stream.read(LIMIT+1)
        if len(body) > LIMIT:
            raise ValueError('Oversized backup metadata')
        value = json.loads(body)
        if (value.get('schema') != 1 or type(value.get('bytes')) is not int or value['bytes'] < 5
                or dump.stat().st_size != value['bytes'] or not re.fullmatch('[a-f0-9]{64}', value.get('sha256', ''))):
            raise ValueError('Incomplete backup generation')
        at = datetime.fromisoformat(value['created_at'])
        if at.tzinfo is None or not -30 <= (now-at).total_seconds() <= 1800:
            raise ValueError('Source backup is stale')
        with dump.open('rb') as stream:
            if stream.read(5) != b'PGDMP':
                raise ValueError('Not a PostgreSQL custom archive')
        state, summary = 'ok', 'Published source backup is less than 30 minutes old; archive checksums and independent restore are separate checks'
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        state, summary = 'failed', 'No fresh complete source database backup was confirmed; inspect the backup schedule and generation metadata'
    return check('host.backup.database', 'Database backup freshness', state, summary)


def vector_transport(*, run=subprocess.run, connect=socket.create_connection, context=ssl.create_default_context):
    """Verify configured sink trust without sending authentication or log events."""
    import re
    verified, failed, unknown = 0, 0, 0
    for name in ('vpn', 'dmz', 'backend', 'zeek'):
        result = command(['systemctl', 'show', 'vector-'+name+'.service', '--property=ExecStart', '--value'], run=run)
        match = re.search(r'(?:--config|-c)\s+(/[A-Za-z0-9_./-]+)', result.stdout) if result else None
        if not match:
            unknown += 1
            continue
        try:
            with Path(match[1]).open('rb') as stream:
                body = stream.read(LIMIT+1)
            if len(body) > LIMIT:
                raise ValueError('Oversized sink configuration')
            sink = tomllib.loads(body.decode())['sinks']['clickhouse']
            endpoint = urlsplit(sink['endpoint'])
            tls = sink['tls']
            ca = Path(tls['ca_file'])
            if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password
                    or not ca.is_absolute() or '..' in ca.parts
                    or tls.get('verify_certificate', True) is not True or tls.get('verify_hostname', True) is not True):
                raise ValueError('Require certificate and hostname verification')
            trust = context(cafile=str(ca))
            with connect((endpoint.hostname, endpoint.port or 443), timeout=3) as connection:
                with trust.wrap_socket(connection, server_hostname=endpoint.hostname):
                    pass
            verified += 1
        except (OSError, ValueError, KeyError, TypeError):
            failed += 1
    state = 'failed' if failed else 'unknown' if unknown else 'ok'
    return check('host.vector.transport', 'Vector sink TLS', state,
                 f'{verified} verified sink connections; {failed} failed; {unknown} unverified. Authentication and event delivery require separate checks.')


def local_snapshot(role, *, run=subprocess.run):
    checks = services(role, run=run)
    checks.extend(resources(role))
    usage = shutil.disk_usage('/')
    percent = round(usage.used/usage.total*100, 1)
    checks.append(check(role+'.storage', role.capitalize()+' root storage',
                        'failed' if percent >= 95 else 'warning' if percent >= 85 else 'ok',
                        f'{percent}% used; {usage.free//(1024**3)} GiB free. Other capture mounts require separate capacity checks.'))
    clock = command(['timedatectl', 'show', '--property=NTPSynchronized', '--value'], run=run)
    checks.append(check(role+'.clock', role.capitalize()+' clock synchronization',
                        'ok' if clock and clock.stdout.strip() == 'yes' else 'unknown',
                        'System reports synchronized time' if clock and clock.stdout.strip() == 'yes' else 'Clock synchronization was not confirmed'))
    if role == 'host':
        checks.append(proxmox_storage(run=run))
        checks.append(database_backup())
        checks.append(vector_transport(run=run))
        checks.extend(eve_health(name) for name in ('vpn', 'dmz', 'backend'))
        checks.append(capture_configuration())
        checks.extend(sensor_interfaces())
    if role == 'monitoring':
        checks.append(prometheus_targets())
        checks.extend(containers(run=run))
        checks.append(dashboards())
    if role == 'database':
        ready = command(['pg_isready', '--quiet'], run=run)
        checks.append(check('database.connections', 'PostgreSQL connections', 'ok' if ready else 'failed',
                            'Local server accepts connections; application query is checked separately' if ready else 'Local database readiness was not confirmed'))
    checks.append(check(role+'.end_to_end', role.capitalize()+' end-to-end validation', 'unknown',
                        'A correlated canary and recovery test are required; service state alone does not verify delivery'))
    return {'schema': 1, 'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks}


def sanitize(value, *, now=None, maximum_age=180):
    """Receipt trust boundary shared by SSH collection and the administrator API."""
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise ValueError('Invalid monitoring receipt')
    now = now or datetime.now(timezone.utc)
    at = datetime.fromisoformat(value['checked_at'])
    if at.tzinfo is None or (at-now).total_seconds() > 30:
        raise ValueError('Invalid monitoring clock')
    items = value['checks']
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('Invalid check inventory')
    checks, identifiers = [], set()
    import re
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid check')
        identifier = item.get('id')
        if not isinstance(identifier, str) or re.fullmatch(r'[A-Za-z0-9@_.-]{1,120}', identifier) is None or identifier in identifiers:
            raise ValueError('Invalid check identity')
        identifiers.add(identifier)
        if item.get('state') not in STATES or any(not isinstance(item.get(key), str) or len(item[key]) > limit for key, limit in (('label', 120), ('summary', 400))):
            raise ValueError('Invalid check fields')
        checks.append({key: item[key] for key in ('id', 'label', 'state', 'summary')})
    state = 'failed' if any(c['state'] == 'failed' for c in checks) else 'warning' if any(c['state'] == 'warning' for c in checks) else 'unknown' if any(c['state'] == 'unknown' for c in checks) else 'ok'
    if (now-at).total_seconds() > maximum_age:
        state = 'stale'
    result = {'schema': 1, 'status': state, 'checked_at': at.isoformat(), 'checks': checks}
    inventory = value.get('agent_inventory')
    if inventory is not None:
        result['agent_inventory'] = sanitize_agents(inventory, now)
    return result


def sanitize_agents(value, now):
    if not isinstance(value, dict) or value.get('status') not in ('ready', 'unavailable', 'not configured'):
        raise ValueError('Invalid agent inventory')
    agents = value.get('agents')
    if not isinstance(agents, list) or len(agents) > 256 or (value['status'] != 'ready' and agents):
        raise ValueError('Invalid inventory size')
    result, seen = [], set()
    for agent in agents:
        identifier = agent.get('machine_id') if isinstance(agent, dict) else None
        if type(identifier) is not int or not 0 < identifier < 2**31 or identifier in seen:
            raise ValueError('Invalid agent identity')
        seen.add(identifier)
        if agent.get('status') not in ('active', 'disconnected', 'pending', 'never_connected'):
            raise ValueError('Invalid agent state')
        item = {'machine_id': identifier, 'status': agent['status']}
        for key in ('last_keepalive', 'registered_at'):
            timestamp = agent.get(key)
            if timestamp is not None:
                at = datetime.fromisoformat(timestamp)
                if at.tzinfo is None or (at-now).total_seconds() > 30:
                    raise ValueError('Invalid agent timestamp')
                timestamp = at.isoformat()
            item[key] = timestamp
        result.append(item)
    return {'status': value['status'], 'agents': result}


def receipt(settings, *, now=None):
    filename = settings.get('HEIST_MONITORING_STATUS_FILE')
    if not filename:
        return {'status': 'not configured', 'checks': []}
    try:
        path = Path(filename)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('Invalid status path')
        with path.open('rb') as stream:
            body = stream.read(LIMIT+1)
        if len(body) > LIMIT:
            raise ValueError('Oversized monitoring receipt')
        return sanitize(json.loads(body), now=now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'unavailable', 'checks': []}


def remote_checks(config):
    """Fixed roles, pinned SSH, no repairs and no credentials returned to callers."""
    if not isinstance(config, dict) or set(config) - {'remotes'}:
        raise ValueError('Invalid monitoring configuration')
    remotes = config.get('remotes', [])
    if not isinstance(remotes, list) or len(remotes) > 4:
        raise ValueError('Invalid monitoring hosts')
    checks, seen = [], set()
    for remote in remotes:
        role = remote['role']
        if role not in ROLES[1:] or role in seen:
            raise ValueError('Duplicate or invalid remote role')
        seen.add(role)
        try:
            from heist.remote import SSH
            ssh = SSH(remote['host'], remote.get('user', 'ubuntu'))
            arguments = ([] if ssh.user == 'root' else ['sudo', '-n'])+['python3', '-', '--role', role]
            result = ssh.run(arguments,
                             input=Path(__file__).read_bytes(), timeout=15)
            if len(result.stdout) > LIMIT:
                raise ValueError('Oversized remote receipt')
            value = sanitize(json.loads(result.stdout))
            if value['status'] == 'stale' or any(not c['id'].startswith(role+'.') for c in value['checks']):
                raise ValueError('Invalid remote role receipt')
            checks.extend(value['checks'])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            checks.append(check(role+'.connection', role.capitalize()+' monitoring connection', 'unknown', 'Pinned SSH collection was not confirmed'))
    for role in ROLES[1:]:
        if role not in seen:
            checks.append(check(role+'.connection', role.capitalize()+' monitoring connection', 'unknown', 'Configure this role to collect its health checks'))
    return checks


def publish(path, value):
    """Atomic, private snapshot; a crashed collector leaves the old receipt stale."""
    path = Path(path)
    body = json.dumps(sanitize(value)).encode()+b'\n'
    if len(body) > LIMIT:
        raise ValueError('Oversized monitoring receipt')
    descriptor, temporary = tempfile.mkstemp(prefix='.status-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=ROLES, default='host')
    parser.add_argument('--config', type=Path, help='Private JSON remote-role configuration (host only)')
    parser.add_argument('--output', type=Path, help='Status file in an existing private directory')
    parser.add_argument('--environment', type=Path, help='Existing private backend environment (host only)')
    args = parser.parse_args(argv)
    if (args.config or args.environment) and args.role != 'host':
        parser.error('Remote collection is available only on the host role')
    value = local_snapshot(args.role)
    if args.role == 'host':
        value['checks'].extend(remote_checks(json.loads(args.config.read_text()) if args.config else {}))
        if args.environment:
            from dotenv import dotenv_values
            from heist.monitoring.agents import collect
            from heist.monitoring.pipeline import grafana, clickhouse
            settings = dict(dotenv_values(args.environment))
            extra = settings.get('HEIST_MONITORING_ENVIRONMENT_FILE')
            if extra:
                if not Path(extra).is_absolute() or '..' in Path(extra).parts or not Path(extra).is_file():
                    raise ValueError('Use an existing absolute monitoring environment path')
                settings.update(dotenv_values(extra))
            inventory, status = collect(settings)
            value['agent_inventory'] = inventory
            value['checks'].append(status)
            value['checks'].extend(grafana(settings))
            value['checks'].extend(clickhouse(settings))
    value['checked_at'] = datetime.now(timezone.utc).isoformat()
    if args.output:
        publish(args.output, value)
    else:
        print(json.dumps(sanitize(value)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
