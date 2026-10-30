"""Release plans are built from immutable Git content rather than working files."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from heist.rollout.manifest import build_plan, safe_relative


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Release test fixture')
        self.write('pyproject.toml', '[project]\nversion="0.1.0"\n')
        self.write('setup/requirements.txt', 'existing-package==1\n')
        self.write('webserver/html/composer.json', '{"require":{},"autoload":{}}')
        self.write('webserver/html/composer.lock', '{}')
        self.write('webserver/html/index.php', '<?php echo "ok";')
        self.write('webserver/html/tests/private.php', '<?php // test fixture')
        self.commit()
        self.source = self.git('rev-parse', 'HEAD').strip()
        self.write('pyproject.toml', '[project]\nversion="0.2.0"\n')
        sql = 'CREATE TABLE release_fixture(id int);'
        self.write('releases/schema.sql', sql)
        self.manifest = {'schema': 1, 'version': '0.2.0', 'supported_from': [self.source],
                         'migrations': [{'id': '0001', 'path': 'releases/schema.sql',
                                         'sha256': hashlib.sha256(sql.encode()).hexdigest()}],
                         'protected_tables': ['users']}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def write(self, name, body):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def plan(self):
        self.write('releases/release.json', json.dumps(self.manifest))
        self.commit()
        target = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', '-q', '--detach', self.source)
        return build_plan(self.root, target, 'releases/release.json', 'config')

    def test_plan_pins_versions_and_excludes_public_test_files(self):
        plan = self.plan()
        self.assertEqual(plan.source, self.source)
        self.assertEqual(plan.source_version, '0.1.0')
        self.assertEqual(plan.version, '0.2.0')
        self.assertIn('tests/private.php', plan.web_before)
        self.assertNotIn('tests/private.php', plan.web_after)
        self.assertEqual(len(plan.migrations), 1)

    def test_dependency_change_is_refused(self):
        self.write('setup/requirements.txt', 'new-package==2\n')
        with self.assertRaisesRegex(ValueError, 'dependency migration'):
            self.plan()

    def test_unknown_starting_commit_is_refused(self):
        self.manifest['supported_from'] = ['0'*40]
        with self.assertRaisesRegex(ValueError, 'upgrade path'):
            self.plan()

    def test_modified_sql_and_duplicate_migration_are_refused(self):
        self.manifest['migrations'][0]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.plan()

    def test_private_web_runtime_data_cannot_enter_release(self):
        self.write('webserver/html/uploads/student.txt', 'private fixture')
        with self.assertRaisesRegex(ValueError, 'Runtime data'):
            self.plan()

    def test_unsafe_relative_paths_are_refused(self):
        for name in ('', '../data', '/root/data', 'a/../b', './a', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_relative(name)
