"""Private VPN filesystem, CA locking and bounded local management operations."""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time

from heist.files import write_file


@dataclass(frozen=True)
class Settings:
    root: Path = Path('/etc/openvpn')
    lock: Path = Path('/var/lock/easy_rsa.lock')
    management: Path = Path('/run/openvpn/heist-management.sock')

    @property
    def ca(self):
        return self.root/'easy-rsa'


def identifier(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValueError('Invalid VPN account identifier')
    return str(value)


def read_private(path, limit=2*1024*1024):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('VPN material must be a regular file')
        data = stream.read(limit+1)
    if not data or len(data) > limit:
        raise ValueError('VPN material is empty or exceeds its limit')
    return data


def atomic_file(path, data, mode=0o600):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_file(path, data, mode=mode)


@contextmanager
def ca_lock(settings, *, timeout=30):
    if not settings.root.is_absolute() or settings.root.is_symlink() or not settings.lock.is_absolute():
        raise ValueError('Configure private absolute VPN paths')
    # The parent may intentionally be /var/lock -> /run/lock; never follow the
    # final lock-file component itself. The root-owned parent is trusted.
    descriptor = os.open(settings.lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Invalid CA lock file')
        os.fchmod(stream.fileno(), 0o600)
        deadline = time.monotonic()+timeout
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('VPN certificate authority is busy') from None
                time.sleep(.05)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def easy_rsa(settings, *arguments):
    environment = dict(os.environ, EASYRSA=str(settings.ca), EASYRSA_PKI=str(settings.ca/'pki'), EASYRSA_BATCH='1')
    if arguments and arguments[0] == 'build-client-full':
        # Inherited CA setup variables must never give multiple users the same CN.
        environment['EASYRSA_REQ_CN'] = arguments[1]
    subprocess.run([str(settings.ca/'easyrsa'), '--batch', *arguments], cwd=settings.ca,
                   env=environment, check=True, capture_output=True, timeout=120)


def certificate_states(settings, name):
    path = settings.ca/'pki/index.txt'
    # An empty, existing CA index means no certificates have been issued yet.
    # A missing index must fail; it cannot prove that an account has no keys.
    if path.is_file() and not path.is_symlink() and path.stat().st_size == 0:
        return []
    index = read_private(path, limit=16*1024*1024).decode('utf-8')
    return [line.split('\t', 1)[0] for line in index.splitlines()
            if re.search(r'(?:^|/)CN='+re.escape(name)+r'(?:/|$)', line.split('\t')[-1])]


def valid_certificate(settings, name):
    return 'V' in certificate_states(settings, name)


def endpoint(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 253:
        raise ValueError('Configure the public VPN_SERVER_IP endpoint')
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        if all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in value.split('.')):
            return value
        raise ValueError('Invalid public VPN endpoint') from None


def require_revocation_configuration(settings):
    lines = [line.split('#', 1)[0].strip() for line in read_private(settings.root/'server.conf').decode().splitlines()]
    required = {'crl-verify '+str(settings.root/'crl.pem'), 'management '+str(settings.management)+' unix', 'management-client-user root'}
    if not required.issubset(set(lines)):
        raise RuntimeError('VPN revocation and local management must be configured before account removal')


def publish_crl(settings):
    """Regenerate, verify and durably replace the CRL; caller holds the CA lock."""
    easy_rsa(settings, 'gen-crl')
    generated = settings.ca/'pki/crl.pem'
    subprocess.run(['openssl', 'crl', '-in', str(generated), '-noout', '-verify', '-CAfile', str(settings.ca/'pki/ca.crt')],
                   check=True, capture_output=True, timeout=15)
    atomic_file(settings.root/'crl.pem', read_private(generated), mode=0o644)


def disconnect(settings, name):
    """Kill exactly this certificate CN and verify it has no connected sessions.

    CRL publication precedes this operation, preventing reconnects. Management is
    a root-only UNIX socket; no TCP listener or general remote command is used.
    """
    if not settings.management.is_absolute() or not stat.S_ISSOCK(settings.management.lstat().st_mode):
        raise RuntimeError('VPN management socket is unavailable')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(settings.management))
        with client.makefile('rb') as stream:
            deadline = time.monotonic()+10
            budget = 2*1024*1024
            def line():
                nonlocal budget
                if time.monotonic() >= deadline or budget <= 0:
                    raise TimeoutError('VPN management response exceeded its budget')
                value = stream.readline(min(65537, budget+1))
                budget -= len(value)
                if not value or len(value) > 65536 or not value.endswith(b'\n') or budget < 0:
                    raise RuntimeError('Invalid VPN management response')
                return value.decode('utf-8').strip()
            while not line().startswith('>INFO:'):
                pass
            client.sendall(('kill '+name+'\n').encode('ascii'))
            result = line()
            if not (result.startswith('SUCCESS: common name ') or result == "ERROR: common name '"+name+"' not found"):
                raise RuntimeError('VPN client could not be disconnected')
            client.sendall(b'status 3\n')
            saw_header, still_connected = False, False
            while True:
                value = line()
                if value == 'END':
                    break
                fields = value.split('\t')
                if fields[0] == 'HEADER' and len(fields) > 2 and fields[1] == 'CLIENT_LIST':
                    saw_header = fields[2] == 'Common Name'
                if fields[0] == 'CLIENT_LIST' and len(fields) > 1 and fields[1] == name:
                    still_connected = True
            if not saw_header or still_connected:
                raise RuntimeError('VPN client disconnection could not be verified')
