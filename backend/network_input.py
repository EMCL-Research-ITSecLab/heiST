"""Owned per-bridge host-input chains; never flush global firewall policy."""
import ipaddress
import re
import subprocess


def chain_name(bridge):
    if not re.fullmatch(r'vrt[0-9a-fA-F]{1,12}', bridge):
        raise ValueError('Expected a generated challenge bridge')
    return 'HEIST_CIN_' + bridge


def inspect(run, binary, *arguments):
    result = run([binary, '-w', '10', *arguments], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Could not inspect challenge input policy')
    return result.returncode == 0


def install_network_input_filter(bridge, router, *, run=subprocess.run):
    chain = chain_name(bridge)
    router = str(ipaddress.IPv4Address(router))
    for binary in ('iptables', 'ip6tables'):
        jump = f'-i {bridge} -j {chain}'
        exists = inspect(run, binary, '-S', chain)
        present = exists and inspect(run, binary, '-C', 'INPUT', '-i', bridge, '-j', chain)
        # The restore transaction changes only this owned chain and jump. The
        # explicit flush removes a previous router when a bridge ID is reused.
        lines = ['*filter', ':' + chain + ' - [0:0]', '-F ' + chain]
        if binary == 'iptables':
            lines += [f'-A {chain} -p udp --sport 68 --dport 67 -j ACCEPT',
                      f'-A {chain} -d {router}/32 -p udp --dport 53 -j ACCEPT',
                      f'-A {chain} -d {router}/32 -p tcp --dport 53 -j ACCEPT']
        else:
            lines += [f'-A {chain} -p ipv6-icmp --icmpv6-type {kind} -m hl --hl-eq 255 -j ACCEPT'
                      for kind in ('neighbor-solicitation', 'neighbor-advertisement')]
        lines.append(f'-A {chain} -j DROP')
        if present:
            lines.append('-D INPUT ' + jump)
        lines += ['-I INPUT 1 ' + jump, 'COMMIT', '']
        run([binary + '-restore', '-w', '10', '--noflush'], input='\n'.join(lines),
            capture_output=True, text=True, check=True)


def remove_network_input_filter(bridge, *, run=subprocess.run):
    chain = chain_name(bridge)
    for binary in ('iptables', 'ip6tables'):
        if not inspect(run, binary, '-S', chain):
            continue
        lines = ['*filter']
        if inspect(run, binary, '-C', 'INPUT', '-i', bridge, '-j', chain):
            lines.append(f'-D INPUT -i {bridge} -j {chain}')
        lines += ['-F ' + chain, '-X ' + chain, 'COMMIT', '']
        run([binary + '-restore', '-w', '10', '--noflush'], input='\n'.join(lines),
            capture_output=True, text=True, check=True)
