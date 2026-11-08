"""Add local VPN revocation management without replacing the installed CA."""
from pathlib import Path
import shlex
import socket
import stat
import subprocess
import time

from heist.files import sha256, write_file
from heist.platform.users.vpn_files import Settings, ca_lock, easy_rsa, read_private

UNIT = 'openvpn@server'


def configuration(body, settings):
    required = {
        'crl-verify': ['crl-verify', str(settings.root/'crl.pem')],
        'management': ['management', str(settings.management), 'unix'],
        'management-client-user': ['management-client-user', 'root'],
    }
    seen = set()
    for line in body.decode('utf-8').splitlines():
        fields = shlex.split(line, comments=True)
        if not fields:
            continue
        if fields[0].startswith('<') or fields[0] == 'config':
            raise RuntimeError('VPN configuration must use reviewed external key files without includes')
        if fields[0] in required:
            if fields[0] in seen or fields != required[fields[0]]:
                raise RuntimeError('Review conflicting VPN management/revocation configuration')
            seen.add(fields[0])
    missing = [' '.join(value) for name,value in required.items() if name not in seen]
    return body if not missing else body.rstrip()+b'\n'+('\n'.join(missing)+'\n').encode()


def inspect(settings=None):
    settings = settings or Settings()
    path = settings.root/'server.conf'
    if settings.root.is_symlink() or path.is_symlink() or not path.is_file():
        raise RuntimeError('Require the installed regular OpenVPN server configuration')
    configuration(read_private(path), settings)
    names = ('pki/ca.crt', 'pki/private/ca.key', 'pki/issued/server.crt',
             'pki/private/server.key', 'ta.key')
    result = {}
    for name in names:
        path = settings.ca/name
        read_private(path)  # Refuse symlinks/special files before hashing.
        result[str(path)] = sha256(path)
    return result


def verify_identity(expected):
    for name,digest in expected.items():
        path = Path(name)
        read_private(path)
        if sha256(path) != digest:
            raise RuntimeError('Installed VPN CA/server identity changed')


def prepare(transaction, *, settings=None):
    settings = settings or Settings()
    expected = transaction.data['vpn_identity']
    verify_identity(expected)
    path = settings.root/'server.conf'
    body = configuration(read_private(path), settings)
    mode = stat.S_IMODE(path.stat().st_mode)
    with ca_lock(settings):
        # gen-crl changes only public CRL state/counter; existing CA and client
        # keys stay in place and are never copied into the rollout journal.
        easy_rsa(settings, 'gen-crl')
        crl = settings.ca/'pki/crl.pem'
        subprocess.run(['openssl', 'crl', '-in', str(crl), '-noout', '-verify',
                        '-CAfile', str(settings.ca/'pki/ca.crt')],
                       check=True, capture_output=True, timeout=15)
        public = read_private(crl)
        from hashlib import sha256 as digest
        hashes = dict(transaction.data.get('target_configuration_hashes', {}))
        hashes.update({str(path): digest(body).hexdigest(),
                       str(settings.root/'crl.pem'): digest(public).hexdigest()})
        # Persist expected bytes before either recoverable host write.
        transaction.save(target_configuration_hashes=hashes)
        write_file(settings.root/'crl.pem', public, mode=0o644)
        write_file(path, body, mode=mode)
    verify_identity(expected)


def configure(transaction, *, settings=None):
    settings = settings or Settings()
    prepare(transaction, settings=settings)
    subprocess.run(['systemctl', 'restart', UNIT], check=True, capture_output=True, timeout=60)
    ready(settings)


def ready(settings=None, *, timeout=30):
    settings = settings or Settings()
    deadline = time.monotonic()+timeout
    while True:
        try:
            if not stat.S_ISSOCK(settings.management.lstat().st_mode):
                raise RuntimeError('VPN management endpoint is not a socket')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(settings.management))
                with client.makefile('rb') as stream:
                    line=stream.readline(65537)
                    if len(line)>65536 or not line.endswith(b'\n') or not line.startswith(b'>INFO:'):
                        raise RuntimeError('VPN management greeting was not recognized')
            return
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise RuntimeError('VPN local management did not become ready') from None
            time.sleep(.1)
