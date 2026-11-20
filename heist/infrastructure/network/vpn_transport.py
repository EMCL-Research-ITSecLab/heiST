"""Size challenge TCP for UDP VPN paths that silently discard large packets.

Own one mangle chain and two scoped jumps. Access remains governed by the
filter table. This also runs standalone from systemd without the app virtualenv.
"""
import argparse
import subprocess

CHAIN = 'HEIST_VPN_MSS'
# Leave room for IPv4/TCP headers and OpenVPN UDP overhead below 1280 bytes.
MSS = 1100
JUMPS = (
    f'-i tun0 -s 10.64.0.0/16 -d 10.128.0.0/9 -j {CHAIN}',
    f'-o tun0 -s 10.128.0.0/9 -d 10.64.0.0/16 -j {CHAIN}',
)


def exists(arguments, run):
    result = run(['iptables', '-w', '10', '-t', 'mangle', *arguments],
                 capture_output=True, text=True, timeout=15)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot inspect VPN transport policy')
    return result.returncode == 0


def configure(*, remove=False, run=subprocess.run):
    """Atomically replace/remove our chain; preserve unrelated rules."""
    present = exists(['-S', CHAIN], run)
    if remove and not present:
        return
    lines = ['*mangle']
    if not remove:
        lines += [f':{CHAIN} - [0:0]', f'-F {CHAIN}',
                  f'-A {CHAIN} -p tcp --tcp-flags SYN,RST SYN '
                  f'-m tcpmss --mss {MSS + 1}:65535 -j TCPMSS --set-mss {MSS}',
                  f'-A {CHAIN} -j RETURN']
    for jump in JUMPS:
        if present and exists(['-C', 'FORWARD', *jump.split()], run):
            lines.append('-D FORWARD ' + jump)
        if not remove:
            lines.append('-I FORWARD 1 ' + jump)
    if remove:
        lines += [f'-F {CHAIN}', f'-X {CHAIN}']
    lines += ['COMMIT', '']
    run(['iptables-restore', '-w', '10', '--noflush'], input='\n'.join(lines),
        capture_output=True, text=True, check=True, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'remove'))
    configure(remove=parser.parse_args().action == 'remove')


if __name__ == '__main__':
    main()
