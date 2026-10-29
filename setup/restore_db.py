"""Compatibility command; restores require --confirm-database and a safety backup."""
from heist.maintenance.database import main as database_main


def main(argv=None):
    import sys
    return database_main(['restore', *(sys.argv[1:] if argv is None else argv)])


if __name__ == '__main__':
    raise SystemExit(main())
