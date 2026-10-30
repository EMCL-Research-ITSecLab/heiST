"""Configure only the dedicated monitoring NIC before Linux enrollment."""
import ipaddress
import json
from pathlib import Path
import time


def prepare_monitoring_network(ga, address, gateway, *, timeout=30, clock=time.monotonic, sleep=time.sleep):
    address = str(ipaddress.IPv6Address(address))
    gateway = str(ipaddress.IPv6Address(gateway))

    def checked(argv, operation):
        result = ga.exec(argv, timeout=15)
        if not result:
            raise RuntimeError('Monitoring network operation failed: ' + operation)
        return result.stdout

    links = json.loads(checked(['ip', '-j', 'link', 'show'], 'inventory'))
    matches = [link['ifname'] for link in links if link.get('address', '').lower().startswith('0a:01:')]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one dedicated monitoring NIC')
    interface = matches[0]
    checked(['ip', 'link', 'set', 'dev', interface, 'up'], 'enable NIC')
    checked(['sysctl', '-w', f'net/ipv6/conf/{interface}/disable_ipv6=0'], 'enable IPv6')
    checked(['ip', '-6', 'addr', 'replace', address + '/64', 'dev', interface], 'assign IPv6')
    deadline = clock() + timeout
    while True:
        state = json.loads(checked(['ip', '-j', '-6', 'addr', 'show', 'dev', interface], 'address readiness'))
        for link in state:
            for entry in link.get('addr_info', []):
                if entry.get('family') != 'inet6' or str(ipaddress.IPv6Address(entry['local'])) != address:
                    continue
                flags = entry.get('flags', [])
                if entry.get('dadfailed') or 'dadfailed' in flags:
                    raise RuntimeError('Monitoring IPv6 duplicate address detection failed')
                if not entry.get('tentative') and 'tentative' not in flags:
                    checked(['ip', '-6', 'route', 'replace', 'default', 'via', gateway, 'dev', interface], 'assign route')
                    return interface
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError('Monitoring IPv6 address did not become usable')
        sleep(min(0.25, remaining))


def persist_monitoring_network(ga, address, gateway, interface):
    """Restore only the MAC-selected link before Wazuh on subsequent boots."""
    def checked(argv):
        result = ga.exec(argv, timeout=30)
        if not result:
            raise RuntimeError('Could not persist monitoring network configuration')
        return result.stdout

    links = json.loads(checked(['ip', '-j', 'link', 'show', 'dev', interface]))
    if len(links) != 1 or not links[0].get('address', '').lower().startswith('0a:01:'):
        raise RuntimeError('Refusing to persist a non-monitoring link')
    config = {'mac': links[0]['address'].lower(), 'address': str(ipaddress.IPv6Address(address)),
              'gateway': str(ipaddress.IPv6Address(gateway))}
    checked(['mkdir', '-p', '/etc/systemd/system/wazuh-agent.service.d'])
    ga.write_file('/usr/local/sbin/heist-monitoring-network.py',
                  Path(__file__).with_name('monitoring_boot.py').read_text(), unix_mode=0o755)
    ga.write_file('/etc/heist-monitoring-network.json', json.dumps(config) + '\n', unix_mode=0o600)
    ga.write_file('/etc/systemd/system/heist-monitoring-network.service', '''[Unit]
Description=Restore the dedicated heiST monitoring link
After=network.target systemd-networkd.service NetworkManager.service
Before=wazuh-agent.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/sbin/heist-monitoring-network.py
RemainAfterExit=yes
TimeoutStartSec=45
[Install]
WantedBy=multi-user.target
''', unix_mode=0o644)
    ga.write_file('/etc/systemd/system/wazuh-agent.service.d/20-heist-network.conf',
                  '[Unit]\nRequires=heist-monitoring-network.service\nAfter=heist-monitoring-network.service\n', unix_mode=0o644)
    checked(['sh', '-c', 'if command -v restorecon >/dev/null 2>&1; then restorecon -F '
             '/usr/local/sbin/heist-monitoring-network.py '
             '/etc/systemd/system/heist-monitoring-network.service '
             '/etc/systemd/system/wazuh-agent.service.d/20-heist-network.conf; fi'])
    checked(['systemctl', 'daemon-reload'])
    checked(['systemctl', 'enable', 'heist-monitoring-network.service'])
    checked(['systemctl', 'restart', 'heist-monitoring-network.service'])
