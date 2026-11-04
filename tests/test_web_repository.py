import unittest
from unittest.mock import MagicMock
from heist.api.public.repository import Repository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.connection.autocommit = True
        self.repo = Repository(lambda: self.connection, enforce_role=False)

    def test_invalid_function_identifier_never_connects(self):
        for value in ('name); DROP TABLE users', 'public.users', None, ''):
            with self.assertRaises(ValueError):
                self.repo.call(value)
        self.assertIsNone(self.repo.connection)

    def test_connection_reuse_scalar_and_cleanup(self):
        self.connection.cursor.return_value.__enter__.return_value.fetchone.return_value = {'answer': 42}
        self.assertEqual(self.repo.scalar('get_answer'), 42)
        self.assertIs(self.repo.db(), self.connection)
        self.repo.close()
        self.repo.close()
        self.connection.close.assert_called_once()
        self.assertIsNone(self.repo.connection)

    def test_transaction_commits_or_rolls_back_and_restores_mode(self):
        with self.repo.transaction():
            self.assertFalse(self.connection.autocommit)
        self.connection.commit.assert_called_once()
        self.assertTrue(self.connection.autocommit)
        with self.assertRaises(RuntimeError):
            with self.repo.transaction():
                raise RuntimeError('failure')
        self.connection.rollback.assert_called_once()
        self.assertTrue(self.connection.autocommit)

    def test_nested_transactions_are_rejected(self):
        with self.repo.transaction():
            with self.assertRaises(RuntimeError):
                with self.repo.transaction():
                    pass

    def test_connection_initialization_failure_closes_the_unusable_connection(self):
        self.connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('failed SET')
        with self.assertRaises(RuntimeError):
            self.repo.db()
        self.connection.close.assert_called_once()
        self.assertIsNone(self.repo.connection)
