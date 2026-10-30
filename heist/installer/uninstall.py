"""Retired legacy uninstaller: it removed shared host networking and fixed VM IDs."""
import sys


def uninstall():
    raise RuntimeError('The legacy uninstaller is retired. Preserve backups and use the recovery procedure in docs/UPDATES.md; do not flush shared host configuration.')


def main():
    print('Automated uninstall is unavailable. See docs/UPDATES.md for recovery and clean-host reprovisioning.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
