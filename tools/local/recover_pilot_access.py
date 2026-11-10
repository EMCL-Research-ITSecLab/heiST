"""Recover SSH on an offline disposable OVA copy through its local serial console.

No private key or password is sent through QMP, command arguments or stdout.
The sealed OVA is never edited. This is fixture instrumentation, not proof that
an unmodified appliance's distributed SSH access works.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.local.nested_pilot import management_network


def validate(work, *, proc=Path('/proc')):
    work = Path(work).resolve()
    config = json.loads((work/'pilot.json').read_text())
    if (config.get('production_accepted') is not False or config.get('cold_import') != 'PREPARED_NOT_BOOTED'
            or not re.fullmatch('[a-f0-9]{64}', config.get('source_ova_sha256', ''))
            or (work/'network-mode').read_text().strip() != 'offline-pilot'):
        raise ValueError('Console recovery requires an offline disposable cold import')
    pid = int((work/'qemu.pid').read_text())
    arguments = (proc/str(pid)/'cmdline').read_bytes().decode().split('\0')
    def option(name):
        return arguments[arguments.index(name)+1] if arguments.count(name) == 1 else None
    if (not Path(arguments[0]).name.startswith('qemu-system-') or option('-pidfile') != str(work/'qemu.pid')
            or option('-netdev') != management_network(config, online=False)
            or option('-chardev') != f'socket,id=console,path={work}/console.sock,server=on,wait=off,logfile={work}/serial.log,logappend=on'
            or not any('file='+str(work/'disk.qcow2')+',format=qcow2,' in value for value in arguments)):
        raise ValueError('Running QEMU identity or isolation differs from the disposable workspace')
    return work


def receive(connection, matches, *, timeout=30):
    deadline = time.monotonic()+timeout
    data = bytearray()
    while time.monotonic() < deadline:
        connection.settimeout(min(1, max(0.01, deadline-time.monotonic())))
        try:
            chunk = connection.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            raise RuntimeError('Disposable serial console closed')
        data.extend(chunk)
        # Never print or store console contents: login output can contain secrets.
        if len(data) > 65536:
            del data[:-8192]
        for marker in matches:
            if marker in data:
                return marker
    raise RuntimeError('Disposable serial console did not reach the expected state')


def authorize(connection, password, public_key):
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]{40,100}(?: [A-Za-z0-9_.-]{1,100})?', public_key):
        raise ValueError('Use the generated single-line disposable Ed25519 public key')
    if not password or '\n' in password or '\r' in password or len(password) > 1024:
        raise ValueError('Invalid console password file')
    connection.sendall(b'\n')
    state = receive(connection, (b'login:', b'root@heist-pilot:'))
    if state == b'login:':
        connection.sendall(b'root\n')
        receive(connection, (b'Password:',))
        connection.sendall(password.encode()+b'\n')
        state = receive(connection, (b'Login incorrect', b'root@heist-pilot:'))
        if state == b'Login incorrect':
            raise RuntimeError('Disposable console authentication failed; no retry was attempted')
    key = shlex.quote(public_key)
    command = ("test -f /root/pilot-cloud-init-ready && test \"$(hostname)\" = heist-pilot "
               "&& test ! -L /root/.ssh "
               "&& { test ! -L /root/.ssh/authorized_keys || { "
               "test \"$(readlink -f /root/.ssh/authorized_keys)\" = /etc/pve/priv/authorized_keys "
               "&& test \"$(stat -c %a /etc/pve/priv/authorized_keys)\" = 600; }; } "
               "&& install -d -m 0700 /root/.ssh && umask 077 "
               "&& { test -e /root/.ssh/authorized_keys || : > /root/.ssh/authorized_keys; } "
               "&& { grep -qxF -- "+key+" /root/.ssh/authorized_keys || printf '%s\\n' "+key+" >> /root/.ssh/authorized_keys; } "
               "&& { test -L /root/.ssh/authorized_keys || chmod 0600 /root/.ssh/authorized_keys; } "
               "&& printf '\\nHEIST-ACCESS-%s\\n' RECOVERED\n")
    connection.sendall(command.encode())
    # The full success marker is not present verbatim in the echoed command.
    receive(connection, (b'HEIST-ACCESS-RECOVERED\r\n', b'HEIST-ACCESS-RECOVERED\n'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--console-password-file', required=True, type=Path)
    args = parser.parse_args(argv)
    work = validate(args.work)
    # Read credentials only after proving this process is the offline local copy.
    password = args.console_password_file.read_text().strip()
    public_key = (work/'id_ed25519.pub').read_text().strip()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(work/'console.sock'))
        authorize(connection, password, public_key)
    receipt = {'schema': 1, 'completed_at': datetime.now(timezone.utc).isoformat(),
               'method': 'offline-copy serial console', 'public_key_sha256': hashlib.sha256(public_key.encode()).hexdigest(),
               'sealed_ova_changed': False, 'production_changed': False}
    (work/'access-recovery.json').write_text(json.dumps(receipt, indent=2)+'\n')
    (work/'access-recovery.json').chmod(0o600)
    print('Authorized the disposable replacement key; verify SSH with the existing pinned host key next.')


if __name__ == '__main__':
    main()
