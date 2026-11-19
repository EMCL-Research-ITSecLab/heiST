"""Per-link DHCP resolvers and authoritative local exercise hostnames."""
import ipaddress
import os
import re


def fallback_servers(value=None):
    # Isolated guests must not fail over to unreachable/public resolvers.
    # Operators can explicitly configure reachable resolvers when needed.
    if value is None:
        value = os.getenv('CHALLENGE_DNS_FALLBACK', '')
    return [str(ipaddress.IPv4Address(item.strip())) for item in value.split(',') if item.strip()]


def connection_dns_servers(connection, fallback):
    local = (connection.client_ip if getattr(connection.machine.template, 'ad_role', 'none') == 'dc'
             else connection.network.router_ip)
    return ','.join(dict.fromkeys([str(ipaddress.IPv4Address(local)), *fallback]))


def hostname_records(domain, address):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', domain):
        raise ValueError('Invalid exercise hostname')
    address = str(ipaddress.IPv4Address(address))
    # dnsmasq >=2.86 otherwise forwards AAAA queries for an IPv4-only record.
    return f'address=/{domain}/{address}\nlocal=/{domain}/\n'
