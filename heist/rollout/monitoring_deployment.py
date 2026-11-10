"""Source-bound monitoring files shared by deployment and checkpoint recovery."""
import json
from pathlib import Path

from heist.remote import SSH
from .manifest import blob

CONFIGURATION = Path('/etc/heist/monitoring.json')
STATUS = Path('/var/lib/heist/monitoring/status.json')
UNITS = ('heist-monitoring.service', 'heist-monitoring.timer')


def paths(environment=None):
    result = [CONFIGURATION, *(Path('/etc/systemd/system')/unit for unit in UNITS)]
    extra = (environment or {}).get('HEIST_MONITORING_ENVIRONMENT_FILE')
    if extra:
        path = Path(extra)
        if not path.is_absolute() or '..' in path.parts or str(path) != extra:
            raise ValueError('Use a normalized monitoring environment path')
        result.append(path)
    return result


def configuration(deployment, environment):
    remotes = [{'role': vm.role, 'host': vm.host, 'user': vm.user} for vm in deployment.vms]
    host = environment.get('HEIST_ARCHIVE_STATUS_HOST')
    if host:
        user = environment.get('HEIST_ARCHIVE_MONITORING_USER', 'ubuntu')
        SSH(host, user)
        remotes.append({'role': 'archive', 'host': host, 'user': user})
    return {'remotes': remotes}


def files(adapter, target):
    """Assemble before the first write; the caller journals all returned hashes."""
    result = {CONFIGURATION: ((json.dumps(configuration(adapter.config, adapter.environment), indent=2)+'\n').encode(), 0o600)}
    for unit in UNITS:
        body = blob(adapter.installation, target, 'deploy/monitoring/systemd/'+unit).decode()
        body = body.replace('/root/heiST/backend/.env', '@@BACKEND_ENV@@')
        body = body.replace('/root/heiST', str(adapter.installation))
        body = body.replace('@@BACKEND_ENV@@', str(adapter.config.backend_env))
        result[Path('/etc/systemd/system')/unit] = (body.encode(), 0o644)
    return result


def target_services():
    return {'heist-monitoring.timer': {'installed': True, 'enabled': True, 'active': True},
            'heist-monitoring.service': {'installed': True, 'enabled': False, 'active': False}}
