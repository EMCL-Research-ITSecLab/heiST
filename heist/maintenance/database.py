"""Stream verified PostgreSQL backups and perform explicit transactional restores."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from heist.config import DatabaseSettings
from heist.files import fsync_directory, maintenance_lock, private_directory, sha256, write_json
from heist.remote import SSH


@dataclass(frozen=True)
class PostgreSQL:
    settings: DatabaseSettings
    ssh: SSH
    os_user: str = 'postgres'

    def command(self, program, *arguments):
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*', self.os_user):
            raise ValueError('Invalid PostgreSQL OS user')
        prefix = ['runuser', '-u', self.os_user, '--'] if self.ssh.user == 'root' else []
        return prefix + [program, *arguments]

    def dump(self, stream):
        self.ssh.run(self.command('pg_dump', '--format=custom', '--no-password',
            '--port', str(self.settings.port), '--dbname', self.settings.name), stdout=stream)

    def validate(self, path):
        with Path(path).open('rb') as stream:
            self.ssh.run(self.command('pg_restore', '--list'), stdin=stream, stdout=subprocess.DEVNULL)

    def restore(self, path):
        with Path(path).open('rb') as stream:
            self.ssh.run(self.command('pg_restore', '--single-transaction', '--exit-on-error',
                '--clean', '--if-exists', '--no-password', '--port', str(self.settings.port),
                '--dbname', self.settings.name), stdin=stream, stdout=subprocess.DEVNULL)


@dataclass
class Backups:
    database: PostgreSQL
    directory: Path

    def create(self, label='backup'):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', label):
            raise ValueError('Backup label must be 1–32 ASCII letters, digits, underscores or hyphens')
        directory = private_directory(self.directory)
        generation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + label + '-' + uuid.uuid4().hex[:12]
        destination = directory / generation
        with tempfile.TemporaryDirectory(prefix='.pending-', dir=directory) as temporary:
            stage = Path(temporary)
            dump = stage / 'database.backup'
            with dump.open('xb') as stream:
                dump.chmod(0o600)
                self.database.dump(stream)
                stream.flush()
                os.fsync(stream.fileno())
            with dump.open('rb') as stream:
                if stream.read(5) != b'PGDMP':
                    raise ValueError('pg_dump did not produce a custom-format archive')
            self.database.validate(dump)
            write_json(stage / 'metadata.json', {
                'schema': 1, 'database': self.database.settings.name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'bytes': dump.stat().st_size, 'sha256': sha256(dump),
            })
            os.rename(stage, destination)
            fsync_directory(directory)
        pointer = directory / ('.latest-' + uuid.uuid4().hex)
        try:
            pointer.symlink_to(Path(generation) / 'database.backup')
            os.replace(pointer, directory / 'latest.backup')
            fsync_directory(directory)
        finally:
            pointer.unlink(missing_ok=True)
        return destination / 'database.backup'

    def restore(self, path, *, allow_unverified=False):
        path = Path(path).resolve(strict=True)
        if not path.is_file():
            raise ValueError('Restore source must be a regular archive')
        with path.open('rb') as stream:
            if stream.read(5) != b'PGDMP':
                raise ValueError('Restore source is not a custom-format PostgreSQL archive')
        metadata_path = path.parent / 'metadata.json'
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
            if metadata['database'] != self.database.settings.name:
                raise ValueError('Archive database name differs from configured target')
            if metadata['bytes'] != path.stat().st_size or metadata['sha256'] != sha256(path):
                raise ValueError('Restore archive checksum/size differs')
        elif not allow_unverified:
            raise ValueError('Archive has no integrity metadata; explicitly authorize legacy archives')
        self.database.validate(path)
        checkpoint = self.create('before-restore')
        try:
            self.database.restore(path)
        except (subprocess.SubprocessError, OSError) as error:
            raise RuntimeError('Restore failed or its outcome is unknown; do not retry blindly. Safety backup: ' + str(checkpoint)) from error
        return checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'restore'))
    parser.add_argument('archive', nargs='?', type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2] / 'setup/.env')
    parser.add_argument('--directory', type=Path, default=Path('/var/backups/heist/database'))
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/heist'))
    parser.add_argument('--ssh-user', default='root')
    parser.add_argument('--label', default='backup')
    parser.add_argument('--confirm-database')
    parser.add_argument('--allow-unverified', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'restore' and args.archive is None:
        parser.error('restore requires an archive')
    from dotenv import dotenv_values
    values = {**dotenv_values(args.config), **os.environ}
    settings = DatabaseSettings.from_mapping(values, prefix='DATABASE_')
    if args.action == 'restore' and args.confirm_database != settings.name:
        parser.error('--confirm-database must exactly match the configured database')
    manager = Backups(PostgreSQL(settings, SSH(settings.host, args.ssh_user)), args.directory)
    with maintenance_lock(args.state_dir):
        if args.action == 'backup':
            print(manager.create(args.label))
        else:
            checkpoint = manager.restore(args.archive, allow_unverified=args.allow_unverified)
            print('Restore finished; safety backup:', checkpoint)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
