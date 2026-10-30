"""Real PostgreSQL checks, explicitly opt-in with a disposable test database."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from heist.rollout.manifest import Migration, Plan
from heist.rollout.migrations import migrate


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
