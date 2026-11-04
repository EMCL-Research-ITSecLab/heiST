"""Bounded expiry sweep; recheck ownership and expiry under database row locks."""
import os
from pathlib import Path

from heist.infrastructure.database import db_connection_context
from heist.files import maintenance_lock
from .stop import stop_challenge


def expired_assignments(connection, limit=100):
    with connection.cursor() as cursor:
        cursor.execute('''SELECT u.id, c.id FROM public.users u
                          JOIN public.challenges c ON c.id=u.running_challenge
                          WHERE c.expires_at <= CURRENT_TIMESTAMP
                          ORDER BY c.expires_at, c.id LIMIT %s''', (limit,))
        return cursor.fetchall()


def sweep(connection, *, stop=stop_challenge):
    stopped, failed = 0, 0
    for user, challenge in expired_assignments(connection):
        try:
            stopped += bool(stop(user, expected_challenge_id=challenge, only_if_expired=True))
        except Exception:
            # Continue independent users, but fail the service so operators see
            # the incomplete sweep. Do not include names, IPs or credentials.
            failed += 1
    if failed:
        raise RuntimeError(f'Expiry incomplete: {failed} assignments require another sweep')
    return stopped


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    maintenance = Path(os.environ.get('HEIST_MAINTENANCE_FILE', '/run/heist-maintenance'))
    if maintenance.exists():
        return 0
    with maintenance_lock(os.environ.get('HEIST_EXPIRY_STATE', '/var/lib/heist/expiry')):
        with db_connection_context() as connection:
            print(f'Expired assignments stopped: {sweep(connection)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
