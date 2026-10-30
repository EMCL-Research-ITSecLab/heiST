from contextlib import contextmanager
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from heist.config import DatabaseSettings
from heist.maintenance.database import Backups, PostgreSQL
from heist.remote import SSH
from heist.runtime import cleanup_guard, cleanup_is_complete
from heist.backend.cleanup import cleanup_remaining_challenges, wait_for_db_connection


class ConfigurationTests(unittest.TestCase):
    def test_password_is_not_in_repr_and_port_is_explicit(self):
        settings=DatabaseSettings.from_mapping({'DB_PASSWORD':'private-test-value','DB_PORT':'6543'})
        self.assertNotIn('private-test-value',repr(settings))
        with patch('psycopg2.connect') as driver:
            connection=settings.connect(autocommit=True)
        self.assertEqual(driver.call_args.kwargs['port'],6543)
        self.assertTrue(connection.autocommit)

    def test_invalid_port_is_rejected_before_connecting(self):
        with self.assertRaises(ValueError):DatabaseSettings(port=0)

    def test_settings_do_not_capture_environment_at_import(self):
        with patch.dict('os.environ',{'DB_NAME':'first'}):first=DatabaseSettings.from_mapping()
        with patch.dict('os.environ',{'DB_NAME':'second'}):second=DatabaseSettings.from_mapping()
        self.assertEqual((first.name,second.name),('first','second'))


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)/'backups'
        self.database=Mock();self.database.settings=DatabaseSettings()
        self.database.dump.side_effect=lambda stream:stream.write(b'PGDMP-test-payload')
        self.backups=Backups(self.database,self.directory)

    def test_backup_is_published_with_verified_digest_and_private_permissions(self):
        path=self.backups.create()
        self.assertEqual(path.read_bytes(),b'PGDMP-test-payload')
        self.assertEqual((self.directory/'latest.backup').resolve(),path)
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(path.parent.stat().st_mode&0o777,0o700)
        self.assertEqual(json.loads((path.parent/'metadata.json').read_text())['bytes'],path.stat().st_size)
        self.database.validate.assert_called_once()

    def test_failed_dump_does_not_replace_previous_backup_or_pointer(self):
        previous=self.backups.create()
        self.database.dump.side_effect=RuntimeError('dump failed')
        with self.assertRaisesRegex(RuntimeError,'dump failed'):self.backups.create()
        self.assertEqual((self.directory/'latest.backup').resolve(),previous)
        self.assertEqual(len(list(self.directory.iterdir())),2)

    def test_truncated_backup_cannot_be_published(self):
        self.database.dump.side_effect=lambda stream:stream.write(b'bad')
        with self.assertRaises(ValueError):self.backups.create()
        self.assertFalse((self.directory/'latest.backup').exists())

    def test_restore_refuses_corrupt_backup_before_checkpoint_or_database_write(self):
        path=self.backups.create();path.write_bytes(b'PGDMP-corrupt')
        self.database.reset_mock()
        with self.assertRaisesRegex(ValueError,'checksum'):self.backups.restore(path)
        self.database.dump.assert_not_called();self.database.restore.assert_not_called()

    def test_restore_preserves_a_safety_backup_and_resolves_latest_before_replacing_it(self):
        path=self.backups.create()
        checkpoint=self.backups.restore(self.directory/'latest.backup')
        self.database.restore.assert_called_once_with(path)
        self.assertNotEqual(path,checkpoint)
        self.assertTrue(checkpoint.is_file())

    def test_failed_pre_restore_backup_blocks_restore(self):
        path=self.backups.create();self.database.dump.side_effect=RuntimeError('no backup')
        with self.assertRaisesRegex(RuntimeError,'no backup'):self.backups.restore(path)
        self.database.restore.assert_not_called()

    def test_restore_command_is_transactional_and_does_not_create_remote_temp_files(self):
        path=self.backups.create();ssh=Mock()
        PostgreSQL(DatabaseSettings(),ssh).restore(path)
        command=ssh.run.call_args.args[0]
        self.assertIn('--single-transaction',command);self.assertIn('--exit-on-error',command)
        self.assertNotIn('/tmp',str(command))


class RuntimeTests(unittest.TestCase):
    def test_cleanup_readiness_is_false_during_work_and_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cleanup.lock'
            with cleanup_guard(path):self.assertFalse(cleanup_is_complete(path))
            self.assertTrue(cleanup_is_complete(path))
            with self.assertRaises(RuntimeError):
                with cleanup_guard(path):raise RuntimeError('teardown failed')
            self.assertFalse(cleanup_is_complete(path))

    def test_cleanup_closes_database_and_propagates_worker_failure(self):
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            db=MagicMock();db.cursor.return_value.__enter__.return_value.fetchall.return_value=[(1,)]
            path=Path(directory)/'cleanup.lock'
            with self.assertRaisesRegex(RuntimeError,'stop failed'):
                cleanup_remaining_challenges(connect=lambda:db,stop=Mock(side_effect=RuntimeError('stop failed')),
                    teardown=Mock(),lock_path=path)
            db.close.assert_called_once();self.assertFalse(cleanup_is_complete(path))

    def test_database_retry_has_a_deadline(self):
        with self.assertRaises(TimeoutError):
            wait_for_db_connection(timeout=1,connect=Mock(side_effect=OSError('offline')),
                clock=Mock(side_effect=[0,2]),sleep=Mock())


class EntryPointTests(unittest.TestCase):
    def test_installer_help_and_import_never_bootstrap_or_generate_scripts(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-c',
            'import heist.installer.cli; import heist.installer.bootstrap; print("imports safe")'],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'imports safe')
        result=subprocess.run([sys.executable,'-m','heist','install','--help'],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('bootstrap',result.stdout)

    def test_ssh_quotes_remote_arguments_and_refuses_option_like_hosts(self):
        with self.assertRaises(ValueError):SSH('-oProxyCommand=bad')
        with patch('heist.remote.subprocess.run') as run:
            SSH('database.test').run(['pg_dump','--dbname','a; echo unsafe'])
        self.assertIn("'a; echo unsafe'",run.call_args.args[0][-1])
        self.assertIn('StrictHostKeyChecking=yes',run.call_args.args[0])
