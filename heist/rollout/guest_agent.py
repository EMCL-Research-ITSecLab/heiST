"""Standard-library agent for the declared web VM, delivered over authenticated SSH.

Importing it performs no work. The controller appends one explicit main action.
"""
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time

STATE = Path('/var/lib/heist')
PROGRAM = Path('/usr/local/lib/heist/maintenance_firewall.py')
UNIT = Path('/etc/systemd/system/heist-web-maintenance.service')
CRON_GUARD = Path('/etc/systemd/system/cron.service.d/heist-maintenance.conf')
APACHE_GUARD = Path('/etc/systemd/system/apache2.service.d/heist-maintenance.conf')


def capture_services():
    states = {}
    for unit in ('apache2', 'cron'):
        states[unit] = {
            name: subprocess.run(['systemctl', verb, '--quiet', unit],
                                 capture_output=True).returncode == 0
            for name, verb in [('active', 'is-active'), ('enabled', 'is-enabled')]
        }
    return states


def install_guard(config):
    STATE.mkdir(mode=0o700, exist_ok=True)
    (STATE / 'maintenance').touch(mode=0o600)
    PROGRAM.parent.mkdir(parents=True, exist_ok=True)
    if PROGRAM.exists() and PROGRAM.read_text() != config['program']:
        raise RuntimeError('An unknown maintenance guard already exists')
    PROGRAM.write_text(config['program'])
    PROGRAM.chmod(0o755)
    UNIT.write_text(
        '[Unit]\nDescription=heiST public web maintenance gate\n'
        'Before=apache2.service cron.service\n\n'
        '[Service]\nType=oneshot\nExecStart=/usr/bin/python3 ' + str(PROGRAM) + '\n'
        'RemainAfterExit=yes\n\n[Install]\nWantedBy=multi-user.target\n'
    )
    APACHE_GUARD.parent.mkdir(parents=True, exist_ok=True)
    APACHE_GUARD.write_text('[Unit]\nRequires=heist-web-maintenance.service\n'
                            'After=heist-web-maintenance.service\n')
    CRON_GUARD.parent.mkdir(parents=True, exist_ok=True)
    CRON_GUARD.write_text('[Unit]\nConditionPathExists=!/var/lib/heist/maintenance\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'heist-web-maintenance'], check=True)
    subprocess.run(['python3', str(PROGRAM)], check=True)


def quiesce():
    subprocess.run(['systemctl', 'disable', '--now', 'apache2', 'cron'], check=True)
    deadline = time.monotonic() + 120
    while True:
        workers = []
        for process in Path('/proc').glob('[0-9]*'):
            try:
                arguments = (process / 'cmdline').read_bytes().split(bytes([0]))
                if b'/var/www/html/backend/worker/worker.php' in arguments:
                    workers.append(process.name)
            except OSError:
                pass
        if not workers:
            return
        if time.monotonic() > deadline:
            raise RuntimeError('Existing PHP workers did not finish')
        time.sleep(1)


def deploy():
    with tempfile.TemporaryDirectory(prefix='heist-web-') as directory:
        stage = Path(directory)
        with tarfile.open(fileobj=sys.stdin.buffer, mode='r|gz') as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not member.isfile():
                    raise RuntimeError('Unsafe web package member')
                target = stage / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
        metadata = json.loads((stage / 'deployment.json').read_text())
        root = Path(metadata['root'])
        for name in set(metadata['before']) | set(metadata['after']):
            destination = root / name
            if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
                raise RuntimeError('Symlink in managed web path')
            if name in metadata['before']:
                if (not destination.is_file() or
                    hashlib.sha256(destination.read_bytes()).hexdigest() != metadata['before'][name]):
                    raise RuntimeError('Installed web source changed: ' + name)
            elif destination.exists():
                raise RuntimeError('New web path collides with local data: ' + name)
            if name in metadata['after']:
                source = stage / 'files' / name
                if hashlib.sha256(source.read_bytes()).hexdigest() != metadata['after'][name]:
                    raise RuntimeError('Web package digest differs')
        for name in metadata['before']:
            if name not in metadata['after']:
                (root / name).unlink()
        for name in metadata['after']:
            source, destination = stage / 'files' / name, root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name('.' + destination.name + '.heist-new')
            shutil.copyfile(source, temporary)
            temporary.chmod(source.stat().st_mode & 0o777)
            os.replace(temporary, destination)
        environment = os.environ.copy()
        environment['COMPOSER_ALLOW_SUPERUSER'] = '1'
        subprocess.run(['composer', 'dump-autoload', '--no-dev', '--classmap-authoritative',
                        '--no-interaction', '--no-scripts', '--no-plugins'],
                       cwd=root, env=environment, check=True)
        subprocess.run(['apache2ctl', 'configtest'], check=True)
        subprocess.run(['systemctl', 'start', 'apache2'], check=True)


def health(config):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection('127.0.0.1', 443, context=context, timeout=10)
    try:
        connection.connect()
        expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(
            Path(config['certificate']).read_text())).hexdigest()
        actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise RuntimeError('Web TLS certificate differs')
        connection.request('GET', '/login')
        response = connection.getresponse()
        if response.status != 200 or b'login' not in response.read(2 * 1024**2).lower():
            raise RuntimeError('Web login health failed')
    finally:
        connection.close()


def finish(config):
    for name, state in config['services'].items():
        subprocess.run(['systemctl', 'enable' if state['enabled'] else 'disable', name], check=True)
        if state['active']:
            subprocess.run(['systemctl', 'start', name], check=True)
    if config['open']:
        (STATE / 'maintenance').unlink(missing_ok=True)
        if config['services']['cron']['active']:
            subprocess.run(['systemctl', 'start', 'cron'], check=True)
        subprocess.run(['python3', str(PROGRAM)], check=True)


def main(action):
    if action == 'capture':
        print(json.dumps(capture_services()))
    elif action == 'quiesce':
        quiesce()
    elif action == 'deploy':
        deploy()
    else:
        config = json.load(sys.stdin)
        {'guard': install_guard, 'health': health, 'finish': finish}[action](config)
