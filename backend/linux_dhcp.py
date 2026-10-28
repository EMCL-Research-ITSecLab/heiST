"""Refresh late per-user DHCP routes before reporting a Linux launch ready."""
import ipaddress
import json
from pathlib import Path
import time
import uuid

from backend.qemu_ga_wrapper import GuestAgent


def add_user_route(config_path, machine_id, user_ip, gateway):
    user = str(ipaddress.IPv4Interface(str(user_ip)).ip) + '/32'
    gateway = str(ipaddress.IPv4Address(gateway))
    prefix = f'dhcp-option=tag:{int(machine_id)},option:classless-static-route,'
    path = Path(config_path)
    original = path.read_text().splitlines()
    routes, kept = {}, []
    for line in original:
        if not line.startswith(prefix):
            kept.append(line)
            continue
        fields = line[len(prefix):].split(',')
        if len(fields) % 2:
            raise ValueError('Malformed existing classless route option')
        for network, router in zip(fields[::2], fields[1::2]):
            routes[str(ipaddress.IPv4Network(network))] = str(ipaddress.IPv4Address(router))
    routes[user] = gateway
    kept.append(prefix + ','.join(value for pair in routes.items() for value in pair))
    path.write_text('\n'.join(kept) + '\n')


def renew_entrypoint(ga, connection, user_ip, *, timeout=60, clock=time.monotonic, sleep=time.sleep):
    def checked(argv):
        result = ga.exec(argv, timeout=30)
        if not result:
            raise RuntimeError('Linux DHCP refresh failed')
        return result.stdout

    links = json.loads(checked(['ip', '-j', 'link', 'show']))
    matches = [link['ifname'] for link in links
               if link.get('address', '').lower() == connection.client_mac.lower()]
    if len(matches) != 1 or connection.client_mac.lower().startswith('0a:01:'):
        raise RuntimeError('Expected one scenario entrypoint NIC')
    interface = matches[0]
    if ga.exec(['systemctl', 'is-active', '--quiet', 'NetworkManager'], timeout=15):
        identifier = str(uuid.UUID(checked(['nmcli', '-g', 'GENERAL.CON-UUID', 'device', 'show', interface]).strip()))
        checked(['nmcli', 'connection', 'up', 'uuid', identifier, 'ifname', interface])
    elif ga.exec(['systemctl', 'is-active', '--quiet', 'systemd-networkd'], timeout=15):
        checked(['networkctl', 'renew', interface])
    else:
        raise RuntimeError('Entrypoint requires NetworkManager or systemd-networkd DHCP')
    destination = ipaddress.IPv4Network(str(ipaddress.IPv4Interface(str(user_ip)).ip) + '/32')
    gateway = str(ipaddress.IPv4Address(connection.network.router_ip))
    deadline = clock() + timeout
    while True:
        routes = json.loads(checked(['ip', '-j', '-4', 'route', 'show']))
        for route in routes:
            if route.get('dst') == 'default':
                continue
            if (ipaddress.IPv4Network(route.get('dst', '0.0.0.0/0')) == destination
                    and route.get('dev') == interface and route.get('gateway') == gateway):
                return
        if clock() >= deadline:
            raise TimeoutError('The user VPN return route did not arrive through DHCP')
        sleep(1)


def renew_linux_entrypoints(challenge, user_ip, user_routes):
    for machine_id, connection in user_routes.items():
        machine = challenge.machines[machine_id]
        if getattr(machine.template, 'guest_os', 'linux').lower() == 'windows':
            continue
        with GuestAgent(vmid=machine_id) as ga:
            renew_entrypoint(ga, connection, user_ip)
