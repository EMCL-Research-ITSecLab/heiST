"""Per-request restricted-role database access with explicit transaction ownership."""
from contextlib import contextmanager
import re

from psycopg2 import sql
from psycopg2.extras import RealDictCursor


class Repository:
    def __init__(self, connect, *, enforce_role=True):
        self.connect = connect
        self.connection = None
        self.enforce_role = enforce_role

    def db(self):
        if self.connection is None:
            connection = self.connect()
            try:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '5s'")
                    if self.enforce_role:
                        cursor.execute('''
                            SELECT NOT EXISTS (
                                SELECT 1 FROM pg_roles p WHERE
                                    (p.rolsuper OR p.rolcreatedb OR p.rolcreaterole OR p.rolreplication OR p.rolbypassrls)
                                    AND pg_has_role(current_user, p.oid, 'MEMBER')
                            )
                            AND NOT EXISTS(SELECT 1 FROM pg_database d WHERE d.datname=current_database() AND pg_has_role(current_user,d.datdba,'MEMBER'))
                            AND NOT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=current_user)
                            AND NOT has_schema_privilege(current_user,'public','CREATE')
                            AND NOT has_schema_privilege(current_user,'api','CREATE')
                            AND NOT has_table_privilege(current_user,'public.users','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                        ''')
                        if cursor.fetchone() != (True,):
                            raise PermissionError('The public API requires a restricted database role')
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
