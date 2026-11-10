"""Compress closed rotated Suricata logs without touching active log files."""
import argparse
import fcntl
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import time


def fingerprint(path):
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def opened(identity, proc=Path('/proc')):
    for process in proc.glob('[0-9]*'):
        try:
            for descriptor in (process/'fd').iterdir():
                try:
                    info = descriptor.stat()
                    if (info.st_dev, info.st_ino) == identity[:2]:
                        return True
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            pass
    return False


def digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b''):
        value.update(block)
    return value.hexdigest()


def prepare(directory, *, minimum_free_bytes=8*1024**3, minimum_age=600, is_open=opened, now=time.time):
    root = Path(directory)
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Use a real rotated-log directory')
    totals = dict(compressed=0, already_compressed=0, skipped_open=0, skipped_young=0, skipped_capacity=0)
    with (root/'.prepare.lock').open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()
                 and re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:json|log)-\d{4}-\d{2}-\d{2}-\d+', p.name)
                 and not any(parent.is_symlink() for parent in p.parents)]
        for source in sorted(files, key=lambda p: p.stat().st_size):
            before = fingerprint(source)
            if is_open(before):
                totals['skipped_open'] += 1
                continue
            if now()-source.stat().st_mtime < minimum_age:
                totals['skipped_young'] += 1
                continue
            target = source.with_name(source.name+'.gz')
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise ValueError('Compressed log destination is not a regular file')
                with source.open('rb') as raw, gzip.open(target, 'rb') as compressed:
                    if digest(raw) != digest(compressed):
                        raise RuntimeError('Existing compressed log differs; original retained')
                totals['already_compressed'] += 1
            else:
                # Budget for an incompressible file, not an optimistic ratio.
                if shutil.disk_usage(root).free < before[2]+minimum_free_bytes+1024*1024:
                    totals['skipped_capacity'] += 1
                    continue
                descriptor, temporary = tempfile.mkstemp(prefix='.prepare-', dir=source.parent)
                try:
                    expected = hashlib.sha256()
                    with os.fdopen(descriptor, 'wb') as output:
                        with source.open('rb') as raw, gzip.GzipFile(fileobj=output, mode='wb', compresslevel=1) as compressed:
                            for block in iter(lambda: raw.read(1024*1024), b''):
                                expected.update(block)
                                compressed.write(block)
                        output.flush()
                        os.fsync(output.fileno())
                    with gzip.open(temporary, 'rb') as compressed:
                        if digest(compressed) != expected.hexdigest():
                            raise RuntimeError('Compressed log verification failed; original retained')
                    if is_open(before) or fingerprint(source) != before:
                        raise RuntimeError('Rotated log changed; original retained')
                    os.rename(temporary, target)
                    totals['compressed'] += 1
                finally:
                    Path(temporary).unlink(missing_ok=True)
            if is_open(before) or fingerprint(source) != before:
                raise RuntimeError('Rotated log is in use; original retained')
            directory_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
                source.unlink()
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/var/log/suricata/rotated'))
    args = parser.parse_args()
    import json
    print(json.dumps(prepare(args.directory)))


if __name__ == '__main__':
    main()
