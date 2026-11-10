"""Authenticated Wazuh inventory collection and instance-scoped projection."""
from datetime import datetime, timezone

from heist.infrastructure.monitoring.wazuh import Wazuh
from .health import check, receipt


def collect(settings, *, client_factory=Wazuh):
    required = ('MONITORING_HOST', 'WAZUH_API_USER', 'WAZUH_API_PASSWORD')
    if not all(settings.get(key) for key in required):
        return {'status': 'not configured', 'agents': []}, check('monitoring.wazuh.api', 'Wazuh API inventory', 'unknown', 'Configure authenticated Wazuh API access')
    client = None
    try:
        client = client_factory(settings['MONITORING_HOST'], settings.get('WAZUH_API_PORT', '55000'),
                                settings['WAZUH_API_USER'], settings['WAZUH_API_PASSWORD'],
                                pinned_certificate=settings.get('WAZUH_PINNED_CERTIFICATE_FILE'))
        agents = client.agents()
        return {'status': 'ready', 'agents': agents}, check('monitoring.wazuh.api', 'Wazuh API inventory', 'ok',
            f'Authenticated inventory: {len(agents)} managed agents. Command delivery requires a separate canary.')
    except (OSError, ValueError, RuntimeError):
        return {'status': 'unavailable', 'agents': []}, check('monitoring.wazuh.api', 'Wazuh API inventory', 'failed',
            'Inventory was not confirmed; check TLS, API permissions and the 256-agent inventory limit')
    finally:
        if client is not None:
            client.close()


def instance(machines, settings, *, snapshot=None, now=None):
    """Only call after SQL administrator and instance identity validation.

    Inventory names identify the current VM, not historical command ownership.
    No network lookup, user-supplied filter or other instance's agents escape.
    """
    now = now or datetime.now(timezone.utc)
    snapshot = receipt(settings, now=now) if snapshot is None else snapshot
    inventory = snapshot.get('agent_inventory', {})
    available = snapshot.get('status') not in ('stale', 'unavailable', 'not configured') and inventory.get('status') == 'ready'
    agents = {item['machine_id']: item for item in inventory.get('agents', [])} if available else {}
    result = []
    for machine in machines:
        agent = agents.get(machine['id'])
        status = agent['status'] if agent else 'missing' if available else 'unknown'
        keepalive = agent.get('last_keepalive') if agent else None
        if status == 'active':
            timestamp = datetime.fromisoformat(keepalive) if keepalive else None
            if timestamp is None or not -30 <= (now-timestamp).total_seconds() <= 180:
                status = 'stale'
        result.append({'machine_id': machine['id'], 'agent_status': status,
                       'last_keepalive': keepalive, 'vm_status': machine.get('status', 'unavailable')})
    # These are platform sensor observations, never a claim of per-network coverage.
    sensors = [item for item in snapshot.get('checks', []) if item['id'] in (
        'host.service.suricata-vpn.service', 'host.service.suricata-dmz.service',
        'host.service.suricata-backend.service', 'host.service.zeek.service')]
    if snapshot.get('status') == 'stale':
        sensors = [{**item, 'state': 'unknown', 'summary': 'Platform sensor evidence is stale'} for item in sensors]
    return {'status': 'ready' if available else 'stale' if snapshot.get('status') == 'stale' else inventory.get('status', 'unknown'),
            'checked_at': snapshot.get('checked_at'), 'machines': result, 'sensors': sensors,
            'command_delivery': 'unverified', 'network_coverage': 'unverified'}
