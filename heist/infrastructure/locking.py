"""Shared/exclusive resource leases across local workers."""
from contextlib import contextmanager
import fcntl
import os
import math
import time

from heist.files import private_directory


class OperationBusy(RuntimeError):
    pass


@contextmanager
def operation_guard(directory, template_id, *, shared=False, timeout=0):
    if isinstance(template_id, bool) or not isinstance(template_id, int) or not 0 < template_id < 2**63:
        raise ValueError('Invalid exercise identifier')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 3600:
        raise ValueError('Use a bounded operation lock timeout')
    directory = private_directory(directory)
    descriptor = os.open(directory/(str(template_id)+'.lock'), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OperationBusy('A resource operation is still running') from None
                time.sleep(min(.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    # Never unlink lock files: waiters must keep using the same inode.
