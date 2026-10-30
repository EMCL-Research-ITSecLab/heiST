#!/usr/bin/env python3
"""Copy closed gzip log archives over trusted SSH; remote removal is explicit."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
from stat import S_ISREG
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


def archive(ssh, remote_directory, destination, *, remove_remote=False):
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('Archive destination must not be a symlink')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_mode & 0o077:
        raise ValueError('Use a private archive directory with mode 0700')
    with ssh.open_sftp() as sftp:
        for entry in sorted(sftp.listdir_attr(remote_directory), key=lambda item: item.filename):
            name = entry.filename
            if not S_ISREG(entry.st_mode) or PurePosixPath(name).name != name or not name.endswith('.gz'):
                continue
            remote = str(PurePosixPath(remote_directory)/name)
            expected = remote_digest(ssh, remote)
            target = destination/name
            if target.is_symlink():
                raise ValueError('Archive file must not be a symlink')
            if not target.exists():
                descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=destination)
                os.close(descriptor)
                try:
                    sftp.get(remote, temporary)
                    if digest(temporary) != expected:
                        raise RuntimeError('Downloaded archive checksum differs')
                    with open(temporary, 'rb') as stream:
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            if digest(target) != expected:
                raise RuntimeError('An existing local archive differs; remote copy retained')
            current = sftp.stat(remote)
            if (current.st_size, current.st_mtime) != (entry.st_size, entry.st_mtime):
                raise RuntimeError('Remote archive changed; remote copy retained')
            if remove_remote:
                sftp.remove(remote)
            print(('Archived and removed remote: ' if remove_remote else 'Verified archive: ') + name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='root')
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--remote-directory', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--remove-remote', action='store_true', help='Remove a closed remote archive only after checksum verification')
    args = parser.parse_args(argv)
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
