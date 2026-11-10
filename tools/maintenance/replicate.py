#!/usr/bin/env python3
"""Replicate closed logs and verified database generations over pinned SSH."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import shutil
import sys
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
from stat import S_ISREG, S_ISDIR
import tempfile


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def remote_digest(ssh, path):
    _, output, error = ssh.exec_command(shlex.join(['sha256sum', '--', path]), timeout=120)
    result = output.read().decode().split()
    if output.channel.recv_exit_status() != 0 or not result or not re.fullmatch('[a-fA-F0-9]{64}', result[0]):
        raise RuntimeError('Remote checksum could not be verified')
    return result[0].lower()


def archive(ssh, remote_directory, destination, *, remove_remote=False, minimum_free_bytes=0):
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('Archive destination must not be a symlink')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077:
        raise ValueError('Use a private archive directory with mode 0700')
    totals = {'copied': 0, 'verified': 0, 'bytes': 0, 'removed_remote': 0}
    with ssh.open_sftp() as sftp:
        for entry in sorted(sftp.listdir_attr(remote_directory), key=lambda item: item.filename):
            name = entry.filename
            if not S_ISREG(entry.st_mode) or PurePosixPath(name).name != name or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.gz', name):
                continue
            remote = str(PurePosixPath(remote_directory)/name)
            expected = remote_digest(ssh, remote)
            target = destination/name
            if target.is_symlink():
                raise ValueError('Archive file must not be a symlink')
            if not target.exists():
                if shutil.disk_usage(destination).free < entry.st_size + minimum_free_bytes:
                    raise OSError('Archive filesystem free-space threshold reached')
                descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=destination)
                os.close(descriptor)
                try:
                    sftp.get(remote, temporary)
                    if digest(temporary) != expected:
                        raise RuntimeError('Downloaded archive checksum differs')
                    with open(temporary, 'rb') as stream:
                        os.fsync(stream.fileno())
                    current = sftp.lstat(remote)
                    if (not S_ISREG(current.st_mode) or
                            (current.st_size, current.st_mtime) != (entry.st_size, entry.st_mtime)):
                        raise RuntimeError('Remote archive changed; incomplete local copy not published')
                    os.replace(temporary, target)
                    totals['copied'] += 1
                    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            if digest(target) != expected:
                raise RuntimeError('An existing local archive differs; remote copy retained')
            current = sftp.lstat(remote)
            if not S_ISREG(current.st_mode):
                raise RuntimeError('Remote archive is no longer a regular file')
            if (current.st_size, current.st_mtime) != (entry.st_size, entry.st_mtime):
                raise RuntimeError('Remote archive changed; remote copy retained')
            if remove_remote:
                if remote_digest(ssh, remote) != expected:
                    raise RuntimeError('Remote archive checksum changed; remote copy retained')
                sftp.remove(remote)
                totals['removed_remote'] += 1
            totals['verified'] += 1
            totals['bytes'] += entry.st_size
            print(('Archived and removed remote: ' if remove_remote else 'Verified archive: ') + name)

    return totals


def write_status(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.status-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def archive_tree(ssh, remote_directory, destination, *, remove_remote=False, minimum_free_bytes=0):
    """Include dated rotation directories, without following remote links."""
    totals = dict(copied=0, verified=0, bytes=0, removed_remote=0)
    pending = [(remote_directory, Path(destination), 0)]
    visited = 0
    while pending:
        remote, local, depth = pending.pop()
        if depth > 8 or visited >= 10000:
            raise ValueError('Log archive directory limit reached')
        visited += 1
        counts = archive(ssh, remote, local, remove_remote=remove_remote,
                         minimum_free_bytes=minimum_free_bytes)
        for key in totals:
            totals[key] += counts[key]
        with ssh.open_sftp() as sftp:
            for entry in sftp.listdir_attr(remote):
                if S_ISDIR(entry.st_mode) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', entry.filename):
                    pending.append((str(PurePosixPath(remote)/entry.filename), local/entry.filename, depth+1))
    return totals


def archive_database(ssh, remote_directory, destination, *, remove_remote=False, minimum_free_bytes=0):
    """Publish only complete immutable pg_dump generations; keep source copies."""
    if remove_remote:
        raise ValueError('Database replication never removes source backups')
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('Backup destination must not be a symlink')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077:
        raise ValueError('Use a private backup directory')
    totals = dict(copied=0, verified=0, bytes=0, removed_remote=0)
    with ssh.open_sftp() as sftp:
        for entry in sorted(sftp.listdir_attr(remote_directory), key=lambda item: item.filename):
            name = entry.filename
            if not S_ISDIR(entry.st_mode) or not re.fullmatch(r'\d{8}T\d{6}Z-[A-Za-z0-9_-]{1,32}-[a-f0-9]{12}', name):
                continue
            remote = str(PurePosixPath(remote_directory)/name)
            meta_entry = sftp.lstat(remote+'/metadata.json')
            dump_entry = sftp.lstat(remote+'/database.backup')
            if not S_ISREG(meta_entry.st_mode) or not S_ISREG(dump_entry.st_mode) or meta_entry.st_size > 65536:
                raise ValueError('Backup generation contains an invalid file')
            with sftp.open(remote+'/metadata.json', 'rb') as stream:
                body = stream.read(65537)
            metadata = json.loads(body)
            size, checksum = metadata.get('bytes'), metadata.get('sha256')
            if (metadata.get('schema') != 1 or type(size) is not int or size < 5
                    or size != dump_entry.st_size or not isinstance(checksum, str)
                    or not re.fullmatch('[a-f0-9]{64}', checksum)):
                raise ValueError('Backup integrity metadata is invalid')
            target = destination/name
            if target.is_symlink():
                raise ValueError('Backup generation must not be a symlink')
            if not target.exists():
                if shutil.disk_usage(destination).free < size + minimum_free_bytes:
                    raise OSError('Backup filesystem free-space threshold reached')
                with tempfile.TemporaryDirectory(prefix='.pending-', dir=destination) as temporary:
                    stage = Path(temporary)
                    dump = stage/'database.backup'
                    sftp.get(remote+'/database.backup', str(dump))
                    dump.chmod(0o600)
                    if dump.stat().st_size != size or digest(dump) != checksum:
                        raise RuntimeError('Downloaded database backup checksum differs')
                    with dump.open('rb') as stream:
                        if stream.read(5) != b'PGDMP':
                            raise ValueError('Backup is not a custom-format PostgreSQL archive')
                        os.fsync(stream.fileno())
                    write_status(stage/'metadata.json', metadata)
                    if remote_digest(ssh, remote+'/database.backup') != checksum:
                        raise RuntimeError('Source database backup changed during replication')
                    os.rename(stage, target)
                    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                totals['copied'] += 1
            local_dump, local_meta = target/'database.backup', target/'metadata.json'
            if (local_dump.is_symlink() or local_meta.is_symlink() or not local_dump.is_file()
                    or not local_meta.is_file() or local_dump.stat().st_size != size
                    or digest(local_dump) != checksum or json.loads(local_meta.read_text()) != metadata):
                raise RuntimeError('Existing backup generation differs; source retained')
            totals['verified'] += 1
            totals['bytes'] += size
    return totals


def load_configuration(path):
    config = json.loads(Path(path).read_text())
    required = {'schema', 'source', 'host', 'user', 'remote_directory', 'destination', 'remove_remote', 'minimum_free_bytes'}
    if not required <= set(config) or set(config)-required-{'kind', 'recursive', 'public_status'} or config['schema'] != 1:
        raise ValueError('Unsupported archive configuration')
    if not isinstance(config['source'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', config['source']):
        raise ValueError('Invalid source identifier')
    if not isinstance(config['host'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', config['host']):
        raise ValueError('Invalid source hostname')
    if not isinstance(config['user'], str) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', config['user']):
        raise ValueError('Invalid SSH account')
    if type(config['remove_remote']) is not bool or type(config['minimum_free_bytes']) is not int or config['minimum_free_bytes'] < 0:
        raise ValueError('Invalid archive retention/capacity settings')
    for name in ('destination', 'remote_directory', *(['public_status'] if 'public_status' in config else [])):
        value = config[name]
        if not isinstance(value, str):
            raise ValueError('Archive directories must be absolute paths')
        candidate = PurePosixPath(value)
        if not candidate.is_absolute() or '..' in candidate.parts or str(candidate) != value or any(ord(c) < 32 for c in value):
            raise ValueError('Archive directories must be normalized absolute paths')
    if config.get('kind', 'logs') not in ('logs', 'database') or type(config.get('recursive', False)) is not bool:
        raise ValueError('Unsupported replication kind or recursion setting')
    if config.get('kind') == 'database' and config['remove_remote']:
        raise ValueError('Database replication never removes source backups')
    return config


def run_configuration(config, identity, known_hosts, *, connect=None, clock=None):
    """Run on the archive VM. One lock and one private receipt per source."""
    clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
    destination = Path(config['destination'])
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError('Archive destination must not contain symlinks')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_uid != os.geteuid() or destination.stat().st_mode & 0o077:
        raise ValueError('Archive destination must be private and owned by the service account')
    descriptor = os.open(destination/'.archive.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status_path = destination/'status.json'
        def publish(status):
            write_status(status_path, status)
            if config.get('public_status'):
                public = Path(config['public_status'])
                if any(path.is_symlink() for path in (public, *public.parents)):
                    raise ValueError('Status path must not contain symlinks')
                write_status(public, status)
                public.chmod(0o644)
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        if previous and previous.get('source') != config['source']:
            raise ValueError('Do not share one archive destination between sources')
        status = {'schema': 1, 'source': config['source'], 'status': 'running', 'started_at': clock(),
                  'last_success_at': previous.get('last_success_at')}
        publish(status)
        try:
            if shutil.disk_usage(destination).free < config['minimum_free_bytes']:
                raise OSError('Archive filesystem free-space threshold reached')
            if connect is None:
                import paramiko
                def connect():
                    client = paramiko.SSHClient()
                    client.load_host_keys(str(known_hosts))
                    client.set_missing_host_key_policy(paramiko.RejectPolicy())
                    try:
                        client.connect(config['host'], username=config['user'], key_filename=str(identity),
                                       look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=15, auth_timeout=15)
                    except BaseException:
                        client.close()
                        raise
                    return client
            with connect() as ssh:
                transfer = archive_database if config.get('kind') == 'database' else archive_tree if config.get('recursive') else archive
                totals = transfer(ssh, config['remote_directory'], destination, remove_remote=config['remove_remote'], minimum_free_bytes=config['minimum_free_bytes'])
            status.update(status='success', completed_at=clock(), counters=totals)
            status['last_success_at'] = status['completed_at']
            publish(status)
            return status
        except Exception as error:
            status.update(status='failed', completed_at=clock(), error=type(error).__name__)
            publish(status)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Archive VM configuration; SSH credentials come from systemd')
    parser.add_argument('--host')
    parser.add_argument('--user', default='root')
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--remote-directory')
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--remove-remote', action='store_true', help='Remove a closed remote archive only after checksum verification')
    args = parser.parse_args(argv)
    if args.config:
        if any((args.host, args.identity, args.remote_directory, args.destination, args.known_hosts, args.remove_remote)):
            parser.error('--config cannot be combined with direct-copy options')
        credentials = os.environ.get('CREDENTIALS_DIRECTORY')
        if not credentials:
            parser.error('--config requires systemd LoadCredential identity and known_hosts')
        run_configuration(load_configuration(args.config), Path(credentials)/'identity', Path(credentials)/'known_hosts')
        return 0
    if not all((args.host, args.identity, args.remote_directory, args.destination)):
        parser.error('Direct copies require --host, --identity, --remote-directory and --destination')
    import paramiko
    with paramiko.SSHClient() as ssh:
        ssh.load_system_host_keys()
        if args.known_hosts:
            ssh.load_host_keys(str(args.known_hosts))
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.connect(args.host, username=args.user, key_filename=str(args.identity),
                    timeout=15, banner_timeout=15, auth_timeout=15)
        archive(ssh, args.remote_directory, args.destination, remove_remote=args.remove_remote)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
