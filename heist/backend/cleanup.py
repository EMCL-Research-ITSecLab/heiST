"""Startup cleanup with bounded retries, propagated failures and explicit resources."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import time

from heist.config import DatabaseSettings
from heist.runtime import cleanup_guard

CLEANUP_COMPLETE_FILE_PATH = '/var/lock/cleanup_complete.lock'


def wait_for_db_connection(timeout=120, *, connect=None, sleep=time.sleep, clock=time.monotonic):
    connect = connect or (lambda: DatabaseSettings.from_mapping().connect(autocommit=True))
    deadline = clock() + timeout
    while True:
        try:
            return connect()
        except Exception as error:
            if clock() >= deadline:
                raise TimeoutError('Database unavailable during startup cleanup') from error
            sleep(min(2, max(0, deadline - clock())))


def fetch_user_ids(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT id FROM users WHERE running_challenge IS NOT NULL')
        return [row[0] for row in cursor.fetchall()]


def fetch_remaining_challenge_ids(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM challenges WHERE lifecycle_state != 'EXPIRED'")
        return [row[0] for row in cursor.fetchall()]


def _parallel(function, identifiers):
    with ThreadPoolExecutor(max_workers=4) as workers:
        # Iterating consumes results so exceptions cannot be silently lost.
        list(workers.map(function, identifiers))


def cleanup_remaining_challenges(*, connect=None, stop=None, teardown=None, lock_path=None):
    if stop is None:
        from heist.backend.stop_challenge import stop_challenge
        stop = stop_challenge
    if teardown is None:
        from heist.backend.teardown_challenge import teardown_challenge
        teardown = teardown_challenge
    with cleanup_guard(lock_path or CLEANUP_COMPLETE_FILE_PATH):
        with closing(wait_for_db_connection(connect=connect)) as connection:
            _parallel(stop, fetch_user_ids(connection))
            _parallel(teardown, fetch_remaining_challenge_ids(connection))


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name('.env'))
    cleanup_remaining_challenges()


if __name__ == '__main__':
    main()
