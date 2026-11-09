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

    def frontend_target(self):
        self.manifest.update(schema=2, frontend=True)
        self.write('releases/release.json', json.dumps(self.manifest))
        self.commit()
        target = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', '-q', '--detach', self.source)
        return target

    def test_frontend_manifest_requires_bundle_before_planning(self):
        target = self.frontend_target()
        with self.assertRaisesRegex(ValueError, '--ui-bundle'):
            build_plan(self.root, target, 'releases/release.json', 'config')

    def test_frontend_bundle_is_bound_to_target_and_artifact_checksum(self):
        from tests.test_ui_assets import bundle
        from heist.ui_assets import digest
        target = self.frontend_target()
        artifact = self.root/'frontend.tar.gz'
        artifact.write_bytes(bundle(target))
        plan = build_plan(self.root, target, 'releases/release.json', 'config', artifact)
        self.assertEqual(plan.schema, 2)
        self.assertEqual(plan.ui_bundle, {'path': str(artifact), 'sha256': digest(artifact.read_bytes())})
        artifact.write_bytes(bundle(self.source))
        with self.assertRaisesRegex(ValueError, 'another source'):
            build_plan(self.root, target, 'releases/release.json', 'config', artifact)

    def test_legacy_rollout_adapter_cannot_deploy_standalone_frontend(self):
        from tests.test_ui_assets import bundle
        target = self.frontend_target()
        artifact = self.root/'frontend.tar.gz'
        artifact.write_bytes(bundle(target, standalone=True))
        with self.assertRaisesRegex(ValueError, 'browser-runtime deployment protocol'):
            build_plan(self.root, target, 'releases/release.json', 'config', artifact)

    def test_moving_unchanged_python_requirements_is_supported(self):
        (self.root/'heist/installer').mkdir(parents=True)
        (self.root/'setup/requirements.txt').rename(self.root/'heist/installer/requirements.txt')
        self.assertEqual(self.plan().version, '0.2.0')

    def browser_runtime_target(self):
        from tests import test_runtime_bundle as fixtures
        self.manifest.update(schema=3,frontend=True,web_runtime=True)
        for name,body in fixtures.SOURCES.items():
            self.write(name,body.decode())
        self.write('deploy/web/requirements.txt',fixtures.REQUIREMENTS.decode())
        self.git('rm','-qr','webserver')
        self.write('releases/release.json',json.dumps(self.manifest))
        self.commit()
        target=self.git('rev-parse','HEAD').strip()
        self.git('checkout','-q','--detach',self.source)
        return target

    def runtime_artifacts(self,target,change=None):
        from unittest.mock import patch
        from tests import test_runtime_bundle as fixtures
        from tests.test_ui_assets import bundle
        ui,runtime=self.root/'ui.tar.gz',self.root/'runtime.tar.gz'
        ui.write_bytes(bundle(target,standalone=True))
        with patch.object(fixtures,'COMMIT',target):
            runtime.write_bytes(fixtures.bundle(change))
        return ui,runtime

    def test_runtime_plan_binds_both_artifacts_and_all_code_to_immutable_git(self):
        from heist.runtime_bundle import digest
        from heist.rollout.manifest import Plan
        target=self.browser_runtime_target()
        ui,runtime=self.runtime_artifacts(target)
        plan=build_plan(self.root,target,'releases/release.json','config',ui,runtime)
        self.assertEqual(plan.schema,3)
        self.assertEqual(plan.runtime_bundle,{'path':str(runtime),'sha256':digest(runtime.read_bytes())})
        self.assertEqual(plan.web_after,())
        self.assertEqual(Plan.from_dict(plan.to_dict()),plan)
        self.runtime_artifacts(target,lambda files:files.update({'source/heist/api/serve.py':b'print("altered")\n'}))
        with self.assertRaisesRegex(ValueError,'trusted Git'):
            build_plan(self.root,target,'releases/release.json','config',ui,runtime)

    def test_runtime_plan_refuses_missing_runtime_legacy_ui_and_changed_dependency_pins(self):
        from tests.test_ui_assets import bundle
        target=self.browser_runtime_target()
        ui,runtime=self.runtime_artifacts(target)
        with self.assertRaisesRegex(ValueError,'--runtime-bundle'):
            build_plan(self.root,target,'releases/release.json','config',ui)
        ui.write_bytes(bundle(target))
        with self.assertRaisesRegex(ValueError,'standalone frontend'):
            build_plan(self.root,target,'releases/release.json','config',ui,runtime)
        self.runtime_artifacts(target,lambda files:files.update({'requirements.txt':b'gunicorn==99\npip==24.0\n'}))
        with self.assertRaisesRegex(ValueError,'trusted source'):
            build_plan(self.root,target,'releases/release.json','config',ui,runtime)

    def test_legacy_release_cannot_accept_an_undeclared_runtime(self):
        target=self.frontend_target()
        ui,_=self.runtime_artifacts(target)
        from tests.test_ui_assets import bundle
        ui.write_bytes(bundle(target))
        with self.assertRaisesRegex(ValueError,'does not declare a browser runtime'):
            build_plan(self.root,target,'releases/release.json','config',ui,'undeclared.tar.gz')


class PublishedBrowserUpdateContractTests(unittest.TestCase):
    def test_rc2_retains_rc1_migration_identities_and_declares_the_installed_browser_baseline(self):
        root=Path(__file__).resolve().parents[1]
        previous=json.loads((root/'releases/0.4.0-rc.1.json').read_text())
        current=json.loads((root/'releases/0.4.0-rc.2.json').read_text())
        self.assertEqual(current['schema'],3)
        self.assertEqual(current['version'],'0.4.0-rc.2')
        self.assertIn('2dc7a767bb46db0432a918fb85ed8f9c5e1a722c',current['supported_from'])
        self.assertTrue(set(previous['supported_from'])<=set(current['supported_from']))
        self.assertEqual(current['migrations'],previous['migrations'])
        self.assertEqual(current['protected_tables'],previous['protected_tables'])
        self.assertTrue(current['frontend'] and current['web_runtime'])
        for migration in current['migrations']:
            self.assertEqual(hashlib.sha256((root/migration['path']).read_bytes()).hexdigest(),migration['sha256'])
