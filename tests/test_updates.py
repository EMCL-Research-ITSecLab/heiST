"""Real temporary Git repositories; failures injected at host service boundaries."""
from pathlib import Path
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import Mock
from setup.update import apply, plan


class UpdateTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'backend').mkdir()
        self.source = self.repo / 'backend/example.py'
        self.source.write_text('value = 1\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'before')
        self.old = self.git('rev-parse', 'HEAD').strip()
        self.source.write_text('value = 2\n')
        self.git('commit', '-qam', 'after')
        self.new = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', '-q', self.old)
        self.host = Mock()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True)

    def test_success_preserves_configuration_and_retains_recovery_bundle(self):
        config = self.repo / 'backend/.env'
        config.write_text('private unchanged configuration\n')
        state = self.root / 'state'
        apply(self.repo, state, plan(self.repo, self.new), self.host)
        self.assertEqual(self.source.read_text(), 'value = 2\n')
        self.assertEqual(config.read_text(), 'private unchanged configuration\n')
        self.assertTrue((state / 'source.bundle').is_file())
        self.assertIn('APPLIED', (state / 'transaction.json').read_text())
        self.host.finish.assert_called_once()

    def test_failed_new_health_restores_old_source_before_resuming_workers(self):
        self.host.healthy.side_effect = [None, RuntimeError('not ready'), None]
        state = self.root / 'state'
        with self.assertRaisesRegex(RuntimeError, 'not ready'):
            apply(self.repo, state, plan(self.repo, self.new), self.host)
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.assertIn('ROLLED_BACK', (state / 'transaction.json').read_text())
        self.host.finish.assert_called_once()

    def test_failed_rollback_health_does_not_resume_workers(self):
        self.host.healthy.side_effect = [None, RuntimeError('new'), RuntimeError('old')]
        state = self.root / 'state'
        with self.assertRaisesRegex(RuntimeError, 'old'):
            apply(self.repo, state, plan(self.repo, self.new), self.host)
        self.assertIn('ROLLBACK_NEEDS_OPERATOR', (state / 'transaction.json').read_text())
        self.host.finish.assert_not_called()

    def test_schema_or_dependency_change_is_refused_before_host_operations(self):
        self.git('checkout', '-q', self.new)
        (self.repo / 'requirements.txt').write_text('flask\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'dependency change')
        target = self.git('rev-parse', 'HEAD').strip()
        self.git('checkout', '-q', self.old)
        proposal = plan(self.repo, target)
        self.assertEqual(proposal['requires_separate_migration'], ['requirements.txt'])
        with self.assertRaisesRegex(RuntimeError, 'separate migration'):
            apply(self.repo, self.root / 'state', proposal, self.host)
        self.assertEqual(self.host.mock_calls, [])

    def test_busy_host_prevents_changes_and_service_stops(self):
        self.host.idle.side_effect = RuntimeError('busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            apply(self.repo, self.root / 'state', plan(self.repo, self.new), self.host)
        self.host.stop.assert_not_called()
        self.assertEqual(self.source.read_text(), 'value = 1\n')

    def test_second_idle_check_closes_launch_race_and_restores_services(self):
        self.host.idle.side_effect = [None, RuntimeError('launch raced')]
        with self.assertRaisesRegex(RuntimeError, 'launch raced'):
            apply(self.repo, self.root / 'state', plan(self.repo, self.new), self.host)
        self.assertEqual(self.source.read_text(), 'value = 1\n')
        self.host.finish.assert_called_once()

    def test_dirty_tracked_files_are_refused(self):
        self.source.write_text('local changes\n')
        with self.assertRaisesRegex(RuntimeError, 'local changes'):
            plan(self.repo, self.new)
