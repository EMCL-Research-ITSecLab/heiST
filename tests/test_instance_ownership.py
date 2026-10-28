"""Real PostgreSQL regressions; set TEST_DATABASE_URL to a disposable test DB.

Each test uses a private random schema and independent autocommit connections.
No application tables or rows are touched.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import threading
import unittest
import uuid

from backend.instance_ownership import assign_instance, take_ready_instance


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL is required')
class InstanceOwnershipTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.driver = psycopg2
        self.schema = 'ownership_test_' + uuid.uuid4().hex
        self.admin = psycopg2.connect(os.environ['TEST_DATABASE_URL'])
        self.admin.autocommit = True
        with self.admin.cursor() as cursor:
            cursor.execute('CREATE SCHEMA ' + self.schema)
        self.connection = self.connect()
        with self.connection.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE users (id bigint PRIMARY KEY, running_challenge bigint);
                CREATE TABLE challenges (
                    id bigint PRIMARY KEY, challenge_template_id bigint,
                    subnet inet, lifecycle_state text, pre_assigned_user_id bigint);
                INSERT INTO users VALUES (1, NULL), (2, NULL);
                INSERT INTO challenges VALUES
                    (10, 5, '10.128.0.0/28', 'READY', 1),
                    (11, 5, '10.128.0.16/28', 'READY', NULL);
            ''')

    def connect(self):
        connection = self.driver.connect(os.environ['TEST_DATABASE_URL'])
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('SET search_path TO ' + self.schema)
        return connection

    def tearDown(self):
        self.connection.close()
        with self.admin.cursor() as cursor:
            cursor.execute('DROP SCHEMA ' + self.schema + ' CASCADE')
        self.admin.close()

    def rows(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT id, running_challenge FROM users ORDER BY id')
            return cursor.fetchall()

    def migration(self):
        return (Path(__file__).resolve().parents[1] / 'database/migrations/'
                '20261028_exclusive_running_instances.sql').read_text()

    def test_cold_ready_instance_is_reserved_and_activated(self):
        self.assertEqual(take_ready_instance(self.connection, 5, 2)[0], 11)
        assign_instance(self.connection, 10, 1)
        self.assertEqual(self.rows(), [(1, 10), (2, None)])
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT lifecycle_state FROM challenges WHERE id=10')
            self.assertEqual(cursor.fetchone(), ('ACTIVE',))
        self.assertIsNone(take_ready_instance(self.connection, 5, 2))

    def test_another_users_reservation_cannot_be_assigned(self):
        before = self.rows()
        with self.assertRaises(RuntimeError):
            assign_instance(self.connection, 10, 2)
        self.assertEqual(self.rows(), before)

    def test_two_students_claim_distinct_pool_instances_concurrently(self):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE challenges SET pre_assigned_user_id=NULL')
        barrier = threading.Barrier(2)

        def launch(user):
            connection = self.connect()
            try:
                barrier.wait(timeout=10)
                row = take_ready_instance(connection, 5, user)
                self.assertIsNotNone(row)
                assign_instance(connection, row[0], user)
                return row[0]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as workers:
            instances = list(workers.map(launch, (1, 2)))
        self.assertEqual(set(instances), {10, 11})
        self.assertEqual({row[1] for row in self.rows()}, {10, 11})

    def test_concurrent_assignment_of_one_instance_has_one_winner(self):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE challenges SET pre_assigned_user_id=NULL')
        barrier = threading.Barrier(2)

        def claim(user):
            connection = self.connect()
            try:
                barrier.wait(timeout=10)
                try:
                    assign_instance(connection, 10, user)
                    return True
                except RuntimeError:
                    return False
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(claim, (1, 2))), [False, True])
        self.assertEqual(sum(row[1] == 10 for row in self.rows()), 1)

    def test_user_with_running_instance_cannot_claim_another(self):
        assign_instance(self.connection, 10, 1)
        with self.assertRaises(RuntimeError):
            assign_instance(self.connection, 11, 1)
        self.assertEqual(self.rows(), [(1, 10), (2, None)])

    def test_unique_index_blocks_duplicate_pointers_and_allows_nulls(self):
        with self.connection.cursor() as cursor:
            cursor.execute(self.migration())
            cursor.execute('UPDATE users SET running_challenge=10 WHERE id=1')
            with self.assertRaises(self.driver.errors.UniqueViolation):
                cursor.execute('UPDATE users SET running_challenge=10 WHERE id=2')
            cursor.execute('UPDATE users SET running_challenge=NULL')
        self.assertEqual(self.rows(), [(1, None), (2, None)])

    def test_migration_refuses_existing_shared_instances_without_changing_rows(self):
        with self.connection.cursor() as cursor:
            cursor.execute('UPDATE users SET running_challenge=10')
            with self.assertRaisesRegex(self.driver.Error, 'Shared running instances'):
                cursor.execute(self.migration())
            cursor.execute('ROLLBACK')
        self.assertEqual(self.rows(), [(1, 10), (2, 10)])
