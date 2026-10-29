"""Review and transactionally install backend-only code updates.

Infrastructure, schema, dependencies and web deployment require a separate,
reviewed migration. The installer is never used as an updater.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def plan(repo, target):
    old = git(repo, 'rev-parse', 'HEAD').decode().strip()
    new = git(repo, 'rev-parse', '--verify', '--end-of-options', target + '^{commit}').decode().strip()
    if git(repo, 'status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Commit or restore tracked local changes before planning an update')
    changes = [os.fsdecode(name) for name in git(repo, 'diff', '--name-only', '-z', old, new).split(b'\0') if name]
    backend = [name for name in changes if name.startswith('backend/') and name.endswith('.py') and '/tests/' not in name]
    review = [name for name in changes if name not in backend and not (
        name.startswith(('tests/', 'docs/', '.github/', 'tools/')) or name in ('README.md', 'Makefile', 'requirements-test.txt'))]
    return {'schema': 1, 'from': old, 'to': new, 'backend_files': backend,
            'requires_separate_migration': review, 'supported': bool(backend) and not review}


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def payload(repo, revision, name):
    mode = git(repo, 'ls-tree', revision, '--', name).split(b' ', 1)[0]
    if not mode:
        return None
    if mode != b'100644':
        raise RuntimeError('Only regular Python source files can be updated: ' + name)
    data = git(repo, 'show', revision + ':' + name)
    compile(data, name, 'exec')
    return data


def install(repo, revision, names):
    # Stage and validate every file before changing any installed code.
    data = {name: payload(repo, revision, name) for name in names}
    for name in names:
        destination = repo / name
        if destination.is_symlink() or any(p.is_symlink() for p in destination.parents if p != repo.parent):
            raise RuntimeError('Refusing symlink in installation path')
    for name, body in data.items():
        destination = repo / name
        if body is None:
            destination.unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            temporary.chmod(0o644)
            os.replace(temporary, destination)


@contextmanager
def lock(state):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state.is_symlink() or state.stat().st_mode & 0o077 or state.stat().st_uid != os.geteuid():
        raise RuntimeError('Update state must be a private directory (0700)')
    with (state / 'update.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Host:
    """Installed-host operations, injected by transaction tests."""
    units = ('pool_manager', 'cleanup', 'backend')

    def __init__(self, repo, health_url, ca):
        if os.geteuid() != 0 or not Path('/etc/pve/local').is_dir():
            raise RuntimeError('Apply/rollback requires root on the installed Proxmox host')
        self.host_lock = open('/run/heist-update.lock', 'a')
        fcntl.flock(self.host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if Path('/run/heist-maintenance').exists():
            raise RuntimeError('Maintenance marker already exists; resolve the previous transaction first')
        from dotenv import dotenv_values
        self.config = dotenv_values(repo / 'backend/.env')
        self.marker = Path('/run/heist-maintenance')
        self.active = None
        self.health_url, self.ca = health_url, ca
        if not health_url.startswith('https://') or not Path(ca).is_file():
            raise RuntimeError('Supply HTTPS readiness URL and its trusted CA file')

    def idle(self):
        import psycopg2
        with psycopg2.connect(host=self.config['DB_HOST'], dbname=self.config['DB_NAME'],
                user=self.config['DB_USER'], password=self.config['DB_PASSWORD'], port=self.config.get('DB_PORT', '5432'), connect_timeout=5) as db:
            with db.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM users WHERE running_challenge IS NOT NULL')
                users = cursor.fetchone()[0]
                cursor.execute('SELECT count(*) FROM challenges')
                instances = cursor.fetchone()[0]
        if users or instances:
            raise RuntimeError('Drain running/provisioning challenges before updating')

    def stop(self):
        self.marker.touch(mode=0o600, exist_ok=True)
        if self.active is None:
            self.active = [unit for unit in self.units if subprocess.run(
                ['systemctl', 'is-active', '--quiet', unit], check=False).returncode == 0]
        subprocess.run(['systemctl', 'stop', *self.units], check=True)

    def start(self):
        # Preserve which services were active; backend must be active to verify.
        subprocess.run(['systemctl', 'start', 'backend'], check=True)

    def finish(self):
        for unit in reversed(self.active):
            subprocess.run(['systemctl', 'start', unit], check=True)
        self.marker.unlink()

    def healthy(self):
        import requests
        deadline = time.monotonic() + 60
        while True:
            try:
                response = requests.get(self.health_url, verify=self.ca, timeout=5,
                    headers={'Authentication-Token': self.config['BACKEND_AUTHENTICATION_TOKEN']})
                if response.status_code == 200 and response.json().get('success') is True:
                    return
            except (requests.RequestException, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('Authenticated readiness did not pass')
            time.sleep(2)


def apply(repo, state, proposal, host):
    if not proposal['supported']:
        raise RuntimeError('This release requires a separate migration; see plan and docs/UPDATES.md')
    with lock(state):
        if (state / 'transaction.json').exists():
            raise RuntimeError('Use a fresh state directory for each update')
        current = plan(repo, proposal['to'])
        if current != proposal:
            raise RuntimeError('Release changed after review')
        # Both revisions must compile before we stop services or write anything.
        for name in proposal['backend_files']:
            payload(repo, proposal['from'], name)
            payload(repo, proposal['to'], name)
        host.idle()
        host.healthy()
        transaction = dict(proposal, status='PREPARED')
        write_json(state / 'transaction.json', transaction)
        git(repo, 'bundle', 'create', str(state / 'source.bundle'), '--all')
        try:
            host.stop()
            host.idle()  # Close the race with a launch during the first check.
            transaction['status'] = 'INSTALLING'
            write_json(state / 'transaction.json', transaction)
            install(repo, proposal['to'], proposal['backend_files'])
            host.start()
            host.healthy()
            host.finish()
            transaction['status'] = 'APPLIED'
        except Exception:
            host.stop()
            install(repo, proposal['from'], proposal['backend_files'])
            host.start()
            try:
                host.healthy()
                host.finish()
                transaction['status'] = 'ROLLED_BACK'
            except Exception:
                transaction['status'] = 'ROLLBACK_NEEDS_OPERATOR'
                raise
            finally:
                write_json(state / 'transaction.json', transaction)
            raise
        write_json(state / 'transaction.json', transaction)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply', 'wizard'))
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--target', required=True, help='Already fetched, reviewed commit/tag; never fetches automatically')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--health-url')
    parser.add_argument('--ca-file')
    args = parser.parse_args()
    proposal = plan(args.repository.resolve(), args.target)
    print(json.dumps(proposal, indent=2))
    if args.action == 'plan':
        return
    if not proposal['supported']:
        parser.error('Separate migration required; application update was not started')
    if args.action == 'wizard' and input('Type the target commit to apply this backend-only update: ').strip() != proposal['to']:
        parser.exit(message='Cancelled; nothing changed\n')
    if not args.state or not args.health_url or not args.ca_file:
        parser.error('--state, --health-url and --ca-file are required for updates')
    state = args.state.resolve()
    if not state.is_absolute() or args.repository.resolve() in state.parents:
        parser.error('Use an absolute private state directory outside the checkout')
    apply(args.repository.resolve(), state, proposal, Host(args.repository.resolve(), args.health_url, args.ca_file))
    print('Backend update verified. Installed files differ from Git HEAD; review and commit the deployment before planning another update.')


if __name__ == '__main__':
    main()
