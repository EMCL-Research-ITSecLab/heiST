"""Restore the dedicated guest monitoring link at boot; contains no credentials."""
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import time


def restore(configuration, *, run=subprocess.check_output, sleep=time.sleep, clock=time.monotonic,
            find=shutil.which):
    address = str(ipaddress.IPv6Address(configuration['address']))
    gateway = str(ipaddress.IPv6Address(configuration['gateway']))
    mac = configuration['mac'].lower()
    if not mac.startswith('0a:01:'):
        raise ValueError('Expected a dedicated monitoring MAC')
    links = json.loads(run(['ip', '-j', 'link', 'show'], text=True))
    matches = [link['ifname'] for link in links if link.get('address', '').lower() == mac]
    if len(matches) != 1:
        raise RuntimeError('Dedicated monitoring link is absent or ambiguous')
    interface = matches[0]
    # NetworkManager can auto-activate an unconfigured wired profile after
    # network.target and erase an address installed directly with ip. Give
    # only this exact monitoring link to our boot service before assigning it.
    if find('nmcli'):
        try:
            run(['systemctl', 'is-active', 'NetworkManager'], text=True, timeout=10)
        except subprocess.CalledProcessError as error:
            if error.returncode not in (3, 4):
                raise
        else:
            run(['nmcli', 'device', 'set', interface, 'managed', 'no'], text=True, timeout=10)
    for command in (
        ['ip', 'link', 'set', 'dev', interface, 'up'],
        ['sysctl', '-w', f'net/ipv6/conf/{interface}/disable_ipv6=0'],
        ['ip', '-6', 'addr', 'replace', address + '/64', 'dev', interface],
    ):
        run(command, text=True)
    deadline = clock() + 30
    while True:
        state = json.loads(run(['ip', '-j', '-6', 'addr', 'show', 'dev', interface], text=True))
        for link in state:
            for entry in link.get('addr_info', []):
                if entry.get('family') != 'inet6' or str(ipaddress.IPv6Address(entry['local'])) != address:
                    continue
                flags = entry.get('flags', [])
                if entry.get('dadfailed') or 'dadfailed' in flags:
                    raise RuntimeError('Monitoring IPv6 duplicate address detection failed')
                if not entry.get('tentative') and 'tentative' not in flags:
                    run(['ip', '-6', 'route', 'replace', 'default', 'via', gateway, 'dev', interface], text=True)
                    return interface
        if clock() >= deadline:
            raise TimeoutError('Monitoring IPv6 did not become ready at boot')
        sleep(0.25)


if __name__ == '__main__':
    restore(json.loads(Path('/etc/heist-monitoring-network.json').read_text()))
