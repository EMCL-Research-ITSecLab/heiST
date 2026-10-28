"""Deny host services on the guest monitoring bridge in both IP families."""
import argparse
import re
import subprocess

CHAIN = 'HEIST_MON_HOST'


def install_host_input_filter(bridge, *, run=subprocess.run):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}', bridge):
        raise ValueError('Invalid monitoring bridge name')

    def checked(arguments):
        return run(arguments, check=True, capture_output=True)

    def ensure(binary, chain, rule, insert=False):
        check = run([binary, '-w', '10', '-C', chain, *rule], capture_output=True)
        if check.returncode == 0:
            return
        if check.returncode != 1:
            raise RuntimeError('Could not inspect monitoring host firewall rule')
        checked([binary, '-w', '10', '-I' if insert else '-A', chain, *(['1'] if insert else []), *rule])

    for binary in ('iptables', 'ip6tables'):
        created = run([binary, '-w', '10', '-N', CHAIN], capture_output=True)
        if created.returncode != 0:
            checked([binary, '-w', '10', '-S', CHAIN])
        # Close the chain before installing its jump; never flush a live chain
        # or any global policy. Repeated bridge-up calls do not add duplicates.
        ensure(binary, CHAIN, ['-j', 'DROP'])
        if binary == 'ip6tables':
            for kind in ('neighbor-solicitation', 'neighbor-advertisement'):
                ensure(binary, CHAIN, ['-p', 'ipv6-icmp', '--icmpv6-type', kind,
                                       '-m', 'hl', '--hl-eq', '255', '-j', 'ACCEPT'], insert=True)
        ensure(binary, 'INPUT', ['-i', bridge, '-j', CHAIN], insert=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', required=True)
    install_host_input_filter(parser.parse_args().bridge)
