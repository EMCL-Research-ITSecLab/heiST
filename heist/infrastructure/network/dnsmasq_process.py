"""Stop exactly one owned dnsmasq process without signaling a recycled PID."""
import os
from pathlib import Path
import select
import signal


def stop(pidfile, timeout=5):
    path = Path(pidfile)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    with os.fdopen(descriptor, 'r', encoding='ascii') as stream:
        value = stream.read(65).strip()
    if not value.isascii() or not value.isdigit() or not 1 < int(value) < 2**31 or len(value) > 16:
        raise ValueError('Invalid owned dnsmasq PID file')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('This platform requires Linux PID file descriptor support')
    if not 0 < timeout <= 30:
        raise ValueError('Invalid DNS process stop timeout')
    pid = int(value)
    try:
        handle = os.pidfd_open(pid)
    except ProcessLookupError:
        return False
    try:
        try:
            arguments = Path('/proc', str(pid), 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            return False
        if not arguments or Path(os.fsdecode(arguments[0])).name != 'dnsmasq' or os.fsencode('--pid-file='+str(path)) not in arguments:
            return False
        poll = select.poll()
        poll.register(handle, select.POLLIN)
        try:
            signal.pidfd_send_signal(handle, signal.SIGTERM)
        except ProcessLookupError:
            return False
        if not poll.poll(int(timeout*1000)):
            try:
                signal.pidfd_send_signal(handle, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not poll.poll(2000):
                raise TimeoutError('Owned dnsmasq process did not exit')
        return True
    finally:
        os.close(handle)
