"""Compatibility API for explicitly scoped database connections.

The calling service loads its environment at startup. This module does not
mutate configuration, log credentials or cache environment variables at import.
"""
from contextlib import contextmanager
from heist.config import DatabaseSettings


def get_db_connection():
    return DatabaseSettings.from_mapping().connect(autocommit=True)


@contextmanager
def db_connection_context():
    """Close the connection on every exit; preserve the existing autocommit API."""
    connection = get_db_connection()
    try:
        yield connection
    finally:
        connection.close()
