"""Pool workers recover after a database connection fails between cycles."""
import unittest
from unittest.mock import MagicMock, patch

from heist.platform.pools.manager import PoolManager
from heist.config import DatabaseSettings


class PoolConnectionRecoveryTests(unittest.TestCase):
    def test_constructing_the_manager_does_not_keep_database_connections(self):
        with patch('heist.infrastructure.database.get_db_connection') as connect:
            PoolManager()
        connect.assert_not_called()

    def test_failed_cycle_closes_connection_and_next_cycle_uses_a_fresh_one(self):
        for operation in ('check_and_maintain_pool', 'teardown_expired_challenges'):
            with self.subTest(operation=operation):
                manager = PoolManager()
                broken, healthy = MagicMock(), MagicMock()
                broken.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('database restarted')
                cursor = healthy.cursor.return_value.__enter__.return_value
                cursor.fetchall.return_value = []
                with patch('heist.infrastructure.database.get_db_connection', side_effect=[broken, healthy]) as connect:
                    with self.assertRaisesRegex(RuntimeError, 'database restarted'):
                        getattr(manager, operation)()
                    broken.close.assert_called_once_with()
                    getattr(manager, operation)()
                    self.assertEqual(connect.call_count, 2)
                    healthy.close.assert_called_once_with()
                if operation == 'check_and_maintain_pool':
                    statement = cursor.execute.call_args.args[0]
                    self.assertIn('is_active = TRUE', statement)
                    self.assertIn('marked_for_deletion = FALSE', statement)

    def test_database_connections_detect_broken_idle_tcp_peers(self):
        connection = MagicMock()
        with patch('psycopg2.connect', return_value=connection) as connect:
            self.assertIs(DatabaseSettings(host='database.test').connect(autocommit=True), connection)
        settings = connect.call_args.kwargs
        self.assertEqual({key: settings[key] for key in ('keepalives', 'keepalives_idle', 'keepalives_interval', 'keepalives_count')},
                         {'keepalives': 1, 'keepalives_idle': 30, 'keepalives_interval': 10, 'keepalives_count': 3})
        self.assertTrue(connection.autocommit)
