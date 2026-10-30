"""Compatibility command; use `heist db backup` for explicit configuration."""
from heist.maintenance.database import main as database_main


def main(argv=None):
    import sys
    return database_main(['backup', *(sys.argv[1:] if argv is None else argv)])


if __name__ == '__main__':
    raise SystemExit(main())
