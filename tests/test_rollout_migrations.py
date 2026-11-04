"""Real PostgreSQL checks, explicitly opt-in with a disposable test database."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from heist.rollout.manifest import Migration, Plan
from heist.rollout.migrations import migrate


class BrowserRoleValidationTests(unittest.TestCase):
    def test_migration_requires_an_explicit_browser_binding_before_connecting(self):
        settings=Mock()
        with self.assertRaises(ValueError):
            migrate(settings,SimpleNamespace(schema=3))
        with self.assertRaises(ValueError):
            migrate(settings,SimpleNamespace(schema=1),web_role='heist_web_test',web_password='a'*64)
        settings.connect.assert_not_called()

    def test_invalid_role_and_password_are_refused_before_any_database_command(self):
        from heist.rollout.browser_role import create
        for role,password in (('postgres','a'*64),('heist_web_test;DROP ROLE postgres','a'*64),
                              ('heist_web_test','short'),('heist_web_test','a'*64+'\n')):
            cursor=Mock()
            with self.subTest(role=role),self.assertRaises(ValueError):
                create(cursor,role,password)
            cursor.execute.assert_not_called()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'disposable PostgreSQL database not configured')
class MigrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.settings = SimpleNamespace(connect=lambda: psycopg2.connect(os.environ['TEST_DATABASE_URL']))
        self.schema = 'rollout_test_' + uuid.uuid4().hex
        self.identifier = self.schema
        connection = self.settings.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute('CREATE SCHEMA ' + self.schema)
            connection.commit()
        finally:
            connection.close()
        self.addCleanup(self.cleanup_database)
        self.plan = Plan(1, '/fixture', 'old', 'new', '0.2.0', 'manifest', 'sha', 'config',
                         (Migration(self.identifier, 'schema.sql', 'original'),), (), ())

    def cleanup_database(self):
        connection = self.settings.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA ' + self.schema + ' CASCADE')
                cursor.execute("SELECT to_regclass('public.heist_schema_migrations')")
                if cursor.fetchone()[0]:
                    cursor.execute('DELETE FROM public.heist_schema_migrations WHERE id LIKE %s', (self.identifier + '%',))
            connection.commit()
        finally:
            connection.close()

    def query(self, statement):
        connection = self.settings.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement)
                return cursor.fetchall()
        finally:
            connection.close()

    def test_repeating_identical_migration_does_not_reexecute_sql(self):
        sql = 'CREATE TABLE ' + self.schema + '.marker(id int); INSERT INTO ' + self.schema + '.marker VALUES (1);'
        with patch('heist.rollout.migrations.blob', return_value=sql.encode()) as read:
            migrate(self.settings, self.plan)
            migrate(self.settings, self.plan)
            read.assert_called_once()
        self.assertEqual(self.query('SELECT count(*) FROM '+self.schema+'.marker'), [(1,)])

    def test_applied_checksum_drift_is_refused(self):
        with patch('heist.rollout.migrations.blob', return_value=b'SELECT 1;'):
            migrate(self.settings, self.plan)
        from dataclasses import replace
        changed = replace(self.plan, migrations=(Migration(self.identifier, 'schema.sql', 'changed'),))
        with self.assertRaisesRegex(RuntimeError, 'checksum changed'):
            migrate(self.settings, changed)

    def test_failing_later_sql_rolls_back_earlier_ddl_and_ledger(self):
        from dataclasses import replace
        failing = replace(self.plan, migrations=self.plan.migrations +
                          (Migration(self.identifier+'_bad', 'bad.sql', 'bad'),))
        with patch('heist.rollout.migrations.blob', side_effect=[
                ('CREATE TABLE '+self.schema+'.marker(id int);').encode(),
                b'SELECT * FROM nonexistent_rollout_fixture_relation;']):
            with self.assertRaises(Exception):
                migrate(self.settings, failing)
        self.assertEqual(self.query("SELECT to_regclass('"+self.schema+".marker')"), [(None,)])

    def test_browser_role_login_and_guc_are_bound_to_the_same_migration_transaction(self):
        from dataclasses import replace
        import secrets
        import psycopg2
        from psycopg2.extensions import parse_dsn
        from psycopg2 import sql
        role='heist_web_'+uuid.uuid4().hex
        password=secrets.token_urlsafe(48)
        plan=replace(self.plan,schema=3)
        try:
            statement='CREATE TABLE '+self.schema+".role_binding AS SELECT current_setting('heist.web_api_role') AS name"
            with patch('heist.rollout.migrations.blob',return_value=statement.encode()):
                migrate(self.settings,plan,web_role=role,web_password=password)
            self.assertEqual(self.query('SELECT name FROM '+self.schema+'.role_binding'),[(role,)])
            self.assertEqual(self.query("SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname='"+role+"'"),[(False,False,False,False,False,False,32)])
            parameters=parse_dsn(os.environ['TEST_DATABASE_URL'])
            parameters.update(user=role,password=password)
            connection=psycopg2.connect(**parameters)
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT current_user')
                    self.assertEqual(cursor.fetchone(),(role,))
            finally:connection.close()
            with self.assertRaises(psycopg2.OperationalError):
                psycopg2.connect(**{**parameters,'password':secrets.token_urlsafe(48)})
            with patch('heist.rollout.migrations.blob',return_value=b'SELECT 1'),self.assertRaisesRegex(RuntimeError,'already exists'):
                migrate(self.settings,plan,web_role=role,web_password=password)
        finally:
            connection=self.settings.connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,))
                    if cursor.fetchone():
                        cursor.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                        cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                connection.commit()
            finally:connection.close()

    def test_failed_browser_migration_does_not_leave_a_login_role_behind(self):
        from dataclasses import replace
        import secrets
        role='heist_web_'+uuid.uuid4().hex
        with patch('heist.rollout.migrations.blob',return_value=b'SELECT * FROM nonexistent_browser_release_fixture'):
            with self.assertRaises(Exception):
                migrate(self.settings,replace(self.plan,schema=3),web_role=role,web_password=secrets.token_urlsafe(48))
        self.assertEqual(self.query("SELECT count(*) FROM pg_roles WHERE rolname='"+role+"'"),[(0,)])
