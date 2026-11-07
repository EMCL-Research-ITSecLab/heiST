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
