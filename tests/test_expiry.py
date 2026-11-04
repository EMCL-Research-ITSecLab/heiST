"""Real assignment/expiry locking; no firewall or live student data is touched."""
from contextlib import closing
import os
import unittest
from unittest.mock import Mock, patch

from heist.platform.challenges import expiry, stop
from tests import test_teardown_database as fixtures


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class ExpiryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.TeardownDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.TeardownDatabaseTests.tearDownClass.__func__)
    remove_database = classmethod(fixtures.TeardownDatabaseTests.remove_database.__func__)
    sql = fixtures.TeardownDatabaseTests.sql

    def setUp(self):
        fixtures.TeardownDatabaseTests.setUp(self)
        self.sql('UPDATE users SET running_challenge=%s WHERE id=%s', (self.instance, self.user_id))
        self.sql("UPDATE challenges SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 minute' WHERE id=%s", (self.instance,))

    def connection(self):
        return closing(self.psycopg2.connect(**self.settings))

    def test_expired_assignment_is_unassigned_atomically_and_cannot_stop_a_new_instance(self):
        with patch.object(stop, 'db_connection_context', self.connection), patch.object(stop, 'remove_user_iptables_rules') as firewall:
            self.assertTrue(stop.stop_challenge(self.user_id, expected_challenge_id=self.instance, only_if_expired=True))
            firewall.assert_called_once()
            self.assertFalse(stop.stop_challenge(self.user_id, expected_challenge_id=self.instance, only_if_expired=True))
        self.assertEqual(self.sql('SELECT running_challenge FROM users WHERE id=%s', (self.user_id,)), [(None,)])
        self.assertEqual(self.sql('SELECT lifecycle_state FROM challenges WHERE id=%s', (self.instance,)), [('EXPIRED',)])

    def test_extension_or_assignment_change_wins_over_stale_expiry_observation(self):
        with patch.object(stop, 'db_connection_context', self.connection), patch.object(stop, 'remove_user_iptables_rules') as firewall:
            self.sql("UPDATE challenges SET expires_at=CURRENT_TIMESTAMP+INTERVAL '1 hour' WHERE id=%s", (self.instance,))
            self.assertFalse(stop.stop_challenge(self.user_id, expected_challenge_id=self.instance, only_if_expired=True))
            self.assertFalse(stop.stop_challenge(self.user_id, expected_challenge_id=self.instance+1, only_if_expired=True))
            firewall.assert_not_called()
        self.assertEqual(self.sql('SELECT running_challenge FROM users WHERE id=%s', (self.user_id,)), [(self.instance,)])
        self.assertEqual(self.sql('SELECT lifecycle_state FROM challenges WHERE id=%s', (self.instance,)), [('ACTIVE',)])

    def test_failed_firewall_cleanup_preserves_assignment_and_failed_sweep_is_visible(self):
        with patch.object(stop, 'db_connection_context', self.connection), patch.object(stop, 'remove_user_iptables_rules', side_effect=OSError('firewall unavailable')):
            with self.assertRaises(OSError):
                stop.stop_challenge(self.user_id, expected_challenge_id=self.instance, only_if_expired=True)
        self.assertEqual(self.sql('SELECT running_challenge FROM users WHERE id=%s', (self.user_id,)), [(self.instance,)])
        with self.connection() as connection:
            failure = Mock(side_effect=OSError('backend down'))
            with self.assertRaises(RuntimeError):
                expiry.sweep(connection, stop=failure)
            self.assertIn(self.user_id, [call.args[0] for call in failure.call_args_list])
            success = Mock(return_value=True)
            self.assertGreaterEqual(expiry.sweep(connection, stop=success), 1)
            success.assert_any_call(self.user_id, expected_challenge_id=self.instance, only_if_expired=True)
