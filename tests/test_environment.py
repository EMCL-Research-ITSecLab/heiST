import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from heist.environment import environment_file, load_backend_env
from heist.rollout.host import prediction_cron


class EnvironmentTests(unittest.TestCase):
    def test_real_platform_entrypoint_imports_resolve_without_provisioning(self):
        import subprocess
        import sys
        script = '''
import importlib
from unittest.mock import patch
services = {
 'heist.platform.challenges.launch': 'launch_challenge',
 'heist.platform.challenges.stop': 'stop_challenge',
 'heist.platform.images.import_templates': 'import_machine_templates',
 'heist.platform.images.delete_templates': 'delete_machine_templates',
 'heist.platform.users.vpn_config': 'get_user_config',
 'heist.platform.users.delete_vpn': 'delete_user_config',
}
with patch('os.makedirs', side_effect=AssertionError('Import created a directory')), \\
     patch('subprocess.run', side_effect=AssertionError('Import executed a command')), \\
     patch('requests.sessions.Session.request', side_effect=AssertionError('Import contacted infrastructure')):
    for module, name in services.items():
        assert callable(getattr(importlib.import_module(module), name)), module
print('All six platform entry points resolve safely')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('All six platform entry points', result.stdout)

    def test_canonical_config_precedes_legacy_without_copying_private_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch('heist.environment.ROOT', Path(folder)):
            root=Path(folder);(root/'backend').mkdir();(root/'backend/.env').write_text('DB_NAME=legacy\n')
            self.assertEqual(environment_file('backend'), root/'backend/.env')
            (root/'config').mkdir();(root/'config/backend.env').write_text('DB_NAME=canonical\n')
            load_backend_env();self.assertEqual(os.environ['DB_NAME'],'canonical')
            self.assertEqual((root/'backend/.env').read_text(),'DB_NAME=legacy\n')

    def test_resource_paths_translate_but_private_key_paths_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch('heist.environment.ROOT', Path(folder)):
            root=Path(folder);(root/'backend').mkdir();(root/'heist/platform/pools').mkdir(parents=True)
            private=root/'backend/certificates/backend.key'
            (root/'backend/.env').write_text(f'BACKEND_FILES_DIR={root}/backend\nBACKEND_CERTIFICATE_KEY_FILE={private}\n')
            load_backend_env();self.assertEqual(os.environ['BACKEND_FILES_DIR'],str(root/'heist/platform'))
            self.assertEqual(os.environ['BACKEND_CERTIFICATE_KEY_FILE'],str(private))

    def test_prediction_job_is_guarded_and_layout_translation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'heist/platform/pools').mkdir(parents=True);(root/'heist/platform/pools/prediction.py').touch()
            original=f'30 5 * * * root /usr/bin/python3 {root}/backend/pool_size_prediction.py >> /var/log/pool.log 2>&1\n'
            guarded=prediction_cron(original,root,root/'maintenance')
            self.assertIn('-m heist.platform.pools.prediction',guarded)
            self.assertIn('test ! -e',guarded)
            self.assertEqual(prediction_cron(guarded,root,root/'maintenance'),guarded)

    def test_image_builder_help_never_imports_or_starts_a_builder(self):
        from tools.images.__main__ import main
        with patch('tools.images.__main__.importlib.import_module') as load:
            with self.assertRaises(SystemExit) as error:main(['windows','--help'])
            self.assertEqual(error.exception.code,0);load.assert_not_called()

    def test_internal_imports_and_declared_module_entrypoints_exist(self):
        import ast
        import re
        root = Path(__file__).resolve().parents[1]
        for source in (root/'heist').rglob('*.py'):
            for node in ast.walk(ast.parse(source.read_text())):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('heist.'):
                    names.append(node.module)
                # Apache's heist.conf is a configuration filename, not a Python
                # entry point. Keep real imports checked even with that name.
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and node.value != 'heist.conf'
                        and re.fullmatch(r'heist(?:\.[a-z_]+)+', node.value)):
                    names.append(node.value)
                for module in names:
                    if source.relative_to(root).parts[:2] == ('heist', 'rollout') and module in {'heist.backend', 'heist.backend.pool_size_prediction'}:
                        continue  # Supported source namespaces during rollback of older installations.
                    path = root.joinpath(*module.split('.'))
                    self.assertTrue(path.with_suffix('.py').is_file() or (path/'__init__.py').is_file(), f'{source}: unresolved internal module {module}')

    def test_legacy_database_backup_schedule_preserves_other_jobs_and_uses_current_cli(self):
        from heist.rollout.backup_cron import rewrite
        original="MAILTO=operator@example.test\n# keep\n*/15 * * * * /usr/bin/echo -e '\\n' | /root/heiST/.venv/bin/python3 /root/heiST/setup/backup_db.py > /dev/null\n0 1 * * * /usr/local/bin/other-backup\n"
        actual=rewrite(original,Path('/root/heiST'),Path('/var/lib/heist/maintenance'),Path('/var/lib/heist'))
        self.assertIn('MAILTO=operator@example.test\n# keep\n',actual)
        self.assertIn('0 1 * * * /usr/local/bin/other-backup\n',actual)
        command=actual.splitlines()[2].split(None,5)[5]
        self.assertIn('test ! -e /var/lib/heist/maintenance && cd /root/heiST &&',command)
        self.assertIn('-m heist.maintenance.database backup --config /root/heiST/setup/.env',command)
        self.assertNotIn('setup/backup_db.py',actual)
        self.assertEqual(rewrite(actual,Path('/root/heiST'),Path('/var/lib/heist/maintenance'),Path('/var/lib/heist')),actual)
        with self.assertRaisesRegex(RuntimeError,'preserve it for review'):
            rewrite('*/15 * * * * custom /root/heiST/setup/backup_db.py --custom\n',Path('/root/heiST'),Path('/marker'),Path('/state'))

    def test_backup_schedule_receipt_precedes_write_and_recovery_preserves_operator_edits(self):
        from heist.rollout import backup_cron
        from types import SimpleNamespace
        before='*/15 * * * * /root/heiST/.venv/bin/python3 /root/heiST/setup/backup_db.py > /dev/null\n'
        adapter=SimpleNamespace(installation=Path('/root/heiST'),marker=Path('/marker'),state=Path('/state'))
        transaction=SimpleNamespace(data={'checkpoint_ready':True,'backup_directory':'/backups'})
        transaction.save=lambda **values:transaction.data.update(values)
        def write(content):
            self.assertEqual(transaction.data['backup_cron']['before'],before)
            self.assertEqual(transaction.data['backup_cron']['after'],content)
        with patch.object(backup_cron,'read',return_value=before),patch.object(backup_cron,'write_json') as receipt,patch.object(backup_cron,'install',side_effect=write) as install:
            backup_cron.migrate(adapter,transaction)
            install.assert_called_once()
            receipt.assert_called_once_with(Path('/backups/root-crontab.json'),transaction.data['backup_cron'])
        after=transaction.data['backup_cron']['after']
        with patch.object(backup_cron,'read',return_value=after),patch.object(backup_cron,'install') as install:
            backup_cron.restore(transaction,transaction)
            install.assert_called_once_with(before)
        with patch.object(backup_cron,'read',return_value=after+'# local edit\n'),patch.object(backup_cron,'install') as install:
            with self.assertRaisesRegex(RuntimeError,'operator edit'):backup_cron.restore(transaction,transaction)
            install.assert_not_called()
        with patch.object(backup_cron,'read',return_value=before):backup_cron.verify(transaction,target=False)
        with patch.object(backup_cron,'read',return_value=after):
            with self.assertRaisesRegex(RuntimeError,'differs'):backup_cron.verify(transaction,target=False)

    def test_backup_cron_capture_is_idempotent_and_refuses_changes_during_checkpoint(self):
        from heist.rollout import backup_cron
        from types import SimpleNamespace
        transaction=SimpleNamespace(data={'checkpoint_ready':True,'backup_directory':'/backups'})
        transaction.save=lambda **values:transaction.data.update(values)
        with patch.object(backup_cron,'read',return_value='original\n') as read:
            backup_cron.capture(transaction);backup_cron.capture(transaction)
            read.assert_called_once()
        adapter=SimpleNamespace(installation=Path('/root/heiST'),marker=Path('/marker'),state=Path('/state'))
        with patch.object(backup_cron,'read',return_value='operator edit\n'),patch.object(backup_cron,'install') as install:
            with self.assertRaisesRegex(RuntimeError,'operator edit'):backup_cron.migrate(adapter,transaction)
            install.assert_not_called()

    def test_failed_rollback_restores_the_newer_safety_checkpoint_schedule(self):
        from heist.rollout import backup_cron
        from types import SimpleNamespace
        older=SimpleNamespace(data={'backup_cron':{'before':'legacy\n','after':'current\n'}})
        safety=SimpleNamespace(data={})
        safety.save=lambda **values:safety.data.update(values)
        with patch.object(backup_cron,'read',return_value='current\n'):backup_cron.capture(safety)
        def ambiguous_install(value):
            self.assertEqual(safety.data['resume_backup_cron'],value)
            raise RuntimeError('Connection lost after cron write')
        with patch.object(backup_cron,'read',return_value='current\n'),patch.object(backup_cron,'install',side_effect=ambiguous_install):
            with self.assertRaisesRegex(RuntimeError,'Connection lost'):backup_cron.restore(safety,older)
        with patch.object(backup_cron,'read',return_value='legacy\n'),patch.object(backup_cron,'install') as install:
            backup_cron.restore(safety,safety)
            install.assert_called_once_with('current\n')
        with patch.object(backup_cron,'read',return_value='current\n'):backup_cron.verify(safety,target=False)
