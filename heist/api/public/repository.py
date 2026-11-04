"""Per-request restricted-role database access with explicit transaction ownership."""
from contextlib import contextmanager
import re

from psycopg2 import sql
from psycopg2.extras import RealDictCursor


class Repository:
    def __init__(self, connect):
        self.connect = connect
        self.connection = None

    def db(self):
        if self.connection is None:
            connection = self.connect()
            try:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '5s'")
            except BaseException:
                connection.close()
                raise
            self.connection = connection
        return self.connection

    def call(self, function, *arguments, one=False):
        if not isinstance(function, str) or not re.fullmatch('[a-z][a-z0-9_]*', function):
            raise ValueError('Invalid stored function identifier')
        statement = sql.SQL('SELECT * FROM {}.{}({})').format(sql.Identifier('api'), sql.Identifier(function),
                    sql.SQL(',').join(sql.Placeholder() for _ in arguments))
        with self.db().cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(statement, arguments)
            if one:
                value = cursor.fetchone()
                return dict(value) if value is not None else None
            return [dict(value) for value in cursor.fetchall()]

    def scalar(self, function, *arguments, default=None):
        value = self.call(function, *arguments, one=True)
        return next(iter(value.values())) if value else default

    @contextmanager
    def transaction(self):
        db = self.db()
        if not db.autocommit:
            raise RuntimeError('Nested application transactions are not supported')
        db.autocommit = False
        try:
            yield self
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.autocommit = True

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
