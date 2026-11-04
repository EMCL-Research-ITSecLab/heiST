"""Persistent web maintenance gate. Only this program's own chains are managed."""
from pathlib import Path
import subprocess
import os

CHAIN = 'HEIST_WEB_MAINT'
MARKER = Path('/var/lib/heist/maintenance')
PUBLIC_MARKER = Path('/run/heist-web-maintenance')


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


def sync_public_marker(enabled,path=PUBLIC_MARKER):
    path=Path(path)
    if path.is_symlink():
        raise ValueError('Maintenance marker must not be a symlink')
    if enabled:
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'w') as stream:
            stream.write('maintenance\n')
            stream.flush();os.fsync(stream.fileno())
    else:
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    enabled=MARKER.exists()
    if enabled:
        sync_public_marker(True)
    configure(enabled)
    if not enabled:
        sync_public_marker(False)
