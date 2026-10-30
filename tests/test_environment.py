import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from heist.environment import environment_file, load_backend_env
from heist.rollout.host import prediction_cron


class EnvironmentTests(unittest.TestCase):
    def test_canonical_config_precedes_legacy_without_copying_private_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch('heist.environment.ROOT', Path(folder)):
            root=Path(folder);(root/'backend').mkdir();(root/'backend/.env').write_text('DB_NAME=legacy\n')
            self.assertEqual(environment_file('backend'), root/'backend/.env')
            (root/'config').mkdir();(root/'config/backend.env').write_text('DB_NAME=canonical\n')
            load_backend_env();self.assertEqual(os.environ['DB_NAME'],'canonical')
            self.assertEqual((root/'backend/.env').read_text(),'DB_NAME=legacy\n')

    def test_resource_paths_translate_but_private_key_paths_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), patch('heist.environment.ROOT', Path(folder)):
            root=Path(folder);(root/'backend').mkdir();(root/'heist/backend').mkdir(parents=True)
            private=root/'backend/certificates/backend.key'
            (root/'backend/.env').write_text(f'BACKEND_FILES_DIR={root}/backend\nBACKEND_CERTIFICATE_KEY_FILE={private}\n')
            load_backend_env();self.assertEqual(os.environ['BACKEND_FILES_DIR'],str(root/'heist/backend'))
            self.assertEqual(os.environ['BACKEND_CERTIFICATE_KEY_FILE'],str(private))

    def test_prediction_job_is_guarded_and_layout_translation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'heist/backend').mkdir(parents=True);(root/'heist/backend/pool_size_prediction.py').touch()
            original=f'30 5 * * * root /usr/bin/python3 {root}/backend/pool_size_prediction.py >> /var/log/pool.log 2>&1\n'
            guarded=prediction_cron(original,root,root/'maintenance')
            self.assertIn('-m heist.backend.pool_size_prediction',guarded)
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
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r'heist(?:\.[a-z_]+)+', node.value):
                    names.append(node.value)
                for module in names:
                    path = root.joinpath(*module.split('.'))
                    self.assertTrue(path.with_suffix('.py').is_file() or (path/'__init__.py').is_file(), f'{source}: unresolved internal module {module}')
