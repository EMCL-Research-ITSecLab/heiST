"""Cross-process cleanup readiness with a lock held for the entire operation."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


def _write_state(stream, state):
    stream.seek(0)
    stream.truncate()
    stream.write(state + '\n')
    stream.flush()
    os.fsync(stream.fileno())


@contextmanager
def cleanup_guard(path):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError('Cleanup lock must be a caller-owned, non-writable regular file')
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _write_state(stream, 'running')
        try:
            yield
        except BaseException:
            _write_state(stream, 'failed')
            raise
        else:
            _write_state(stream, 'complete')


def cleanup_is_complete(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as stream:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return stream.read().strip() == 'complete'
    except (OSError, BlockingIOError):
        return False
