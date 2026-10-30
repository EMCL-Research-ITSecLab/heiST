"""Persistent web maintenance gate. Only this program's own chains are managed."""
from pathlib import Path
import subprocess

CHAIN = 'HEIST_WEB_MAINT'
MARKER = Path('/var/lib/heist/maintenance')


def configure(enabled, run=subprocess.run):
    for binary in ('iptables', 'ip6tables'):
        present = run([binary, '-w', '5', '-C', 'INPUT', '-j', CHAIN],
                      capture_output=True).returncode == 0
        exists = run([binary, '-w', '5', '-S', CHAIN],
                     capture_output=True).returncode == 0
        if enabled:
            rules = [
                '*filter',
                ':' + CHAIN + ' - [0:0]',
                '-F ' + CHAIN,
                '-A ' + CHAIN + ' ! -i lo -p tcp -m multiport --dports 80,443 '
                '-m comment --comment heist-maintenance-v1 -j REJECT',
            ]
            if not present:
                rules.append('-I INPUT 1 -j ' + CHAIN)
        elif present or exists:
            rules = ['*filter']
            if present:
                rules.append('-D INPUT -j ' + CHAIN)
            if exists:
                rules.extend(['-F ' + CHAIN, '-X ' + CHAIN])
        else:
            continue
        rules.append('COMMIT')
        run([binary + '-restore', '--noflush', '-w', '5'],
            input='\n'.join(rules) + '\n', text=True, check=True)


if __name__ == '__main__':
    configure(MARKER.exists())
