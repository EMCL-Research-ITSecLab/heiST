"""Run the real delivery verifier periodically from an off-host operator machine."""
import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import uuid


def verify(output_root, arguments, *, run=subprocess.run):
    """Serialize runs; retain diagnostics, but discard successful copied SQL data."""
    root = Path(output_root)
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('Use an absolute private evidence directory')
    if any(a.split('=', 1)[0] in ('--output', '--publish') for a in arguments):
        raise ValueError('The scheduler supplies --output and --publish')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError('Evidence directory must be owned by this account and private')
    with (root/'.lock').open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        output = root/(stamp+'-'+uuid.uuid4().hex[:12])
        run([sys.executable, '-m', 'tools.monitoring.verify_delivery', *arguments,
             '--output', str(output), '--publish'], check=True)
        # Only remove this run's successfully verified backup. Failed runs keep
        # all diagnostics; receipts/checksums remain, and no older run is touched.
        (output/'database-restore/database.backup').unlink(missing_ok=True)
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('verifier_arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.verifier_arguments
    if not arguments or arguments[0] != '--':
        parser.error('Separate the verifier arguments with --')
    os.umask(0o077)
    print('Delivery verification completed: '+str(verify(args.output_root, arguments[1:])), flush=True)


if __name__ == '__main__':
    main()
