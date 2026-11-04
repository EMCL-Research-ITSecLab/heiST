"""Activation is durable even if the web process loses the successful response."""
from contextlib import closing
import os
import unittest

from heist.platform.challenges.ownership import finalize_launch
from tests import test_teardown_database as fixtures


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class InstanceActivationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.TeardownDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.TeardownDatabaseTests.tearDownClass.__func__)
    remove_database = classmethod(fixtures.TeardownDatabaseTests.remove_database.__func__)
    sql = fixtures.TeardownDatabaseTests.sql

    def setUp(self):
        fixtures.TeardownDatabaseTests.setUp(self)
        self.sql('UPDATE users SET running_challenge=%s WHERE id=%s', (self.instance, self.user_id))

    def test_retry_has_one_attempt_and_trace_and_does_not_extend_deadline(self):
        network = self.sql("INSERT INTO network_templates(challenge_template_id,name,accessible) VALUES (%s,'entry',TRUE) RETURNING id", (self.template,))[0][0]
        self.sql("INSERT INTO networks(network_template_id,challenge_id,subnet,host_device) VALUES (%s,%s,%s,'test0')", (network, self.instance, self.subnet))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            finalize_launch(connection, self.instance, self.user_id)
        self.sql("UPDATE challenges SET expires_at=expires_at-INTERVAL '5 minutes' WHERE id=%s", (self.instance,))
        deadline = self.sql('SELECT expires_at FROM challenges WHERE id=%s', (self.instance,))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            finalize_launch(connection, self.instance, self.user_id)
        self.assertEqual(self.sql('SELECT expires_at FROM challenges WHERE id=%s', (self.instance,)), deadline)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM completed_challenges WHERE user_id=%s AND challenge_template_id=%s', (self.user_id, self.template)), [(1,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM user_network_trace WHERE username=%s', (self.username,)), [(1,)])

    def test_changed_assignment_and_trace_failure_leave_no_partial_activation(self):
        self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s', (self.user_id,))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with self.assertRaises(RuntimeError):
                finalize_launch(connection, self.instance, self.user_id)
        self.sql('UPDATE users SET running_challenge=%s WHERE id=%s', (self.instance, self.user_id))
        before = self.sql('SELECT expires_at FROM challenges WHERE id=%s', (self.instance,))
        self.sql('ALTER TABLE instance_activations ADD CONSTRAINT injected_failure CHECK (user_id<0) NOT VALID')
        try:
            with closing(self.psycopg2.connect(**self.settings)) as connection:
                connection.autocommit = True
                with self.assertRaises(self.psycopg2.IntegrityError):
                    finalize_launch(connection, self.instance, self.user_id)
        finally:
            self.sql('ALTER TABLE instance_activations DROP CONSTRAINT injected_failure')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM completed_challenges WHERE user_id=%s', (self.user_id,)), [(0,)])
        self.assertEqual(self.sql('SELECT expires_at FROM challenges WHERE id=%s', (self.instance,)), before)
