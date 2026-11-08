"""The interactive wizard never enters maintenance without exact commit approval."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from heist.files import sha256
from heist.rollout.cli import main
from heist.rollout.controller import Transaction
from heist.rollout.manifest import Plan


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'deployment.json'
        example = Path(__file__).resolve().parents[1]/'config/deployment.example.json'
        self.config.write_bytes(example.read_bytes())
        self.plan = Plan(1, '/fixture', 'old', 'a'*40, '0.2.0', 'manifest', 'sha', sha256(self.config), (), (), ())
        self.arguments = ['wizard', '--config', str(self.config), '--target', 'reviewed']

    def test_noninteractive_wizard_cannot_apply(self):
        with patch('heist.rollout.cli.build_plan', return_value=self.plan), \
             patch('heist.rollout.cli.sys.stdin.isatty', return_value=False), \
             patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO), \
             patch('heist.rollout.pve.PVE') as operations:
            with self.assertRaises(SystemExit) as error:
                main(self.arguments)
            self.assertEqual(error.exception.code, 2)
            operations.assert_not_called()

    def test_incorrect_approval_cancels_before_constructing_host_operations(self):
        with patch('heist.rollout.cli.build_plan', return_value=self.plan), \
             patch('heist.rollout.cli.sys.stdin.isatty', return_value=True), \
             patch('builtins.input', return_value='wrong'), patch('sys.stdout', new_callable=io.StringIO), \
             patch('heist.rollout.pve.PVE') as operations:
            self.assertEqual(main(self.arguments), 2)
            operations.assert_not_called()

    def test_exact_commit_approval_applies_the_displayed_plan(self):
        transaction = Transaction(self.root/'transaction', {'plan': self.plan.to_dict(), 'phase': 'COMPLETE'})
        controller = Mock();controller.apply.return_value = transaction
        with patch('heist.rollout.cli.build_plan', return_value=self.plan), \
             patch('heist.rollout.cli.sys.stdin.isatty', return_value=True), \
             patch('builtins.input', return_value=self.plan.target), patch('sys.stdout', new_callable=io.StringIO), \
             patch('heist.rollout.pve.PVE'), patch('heist.rollout.cli.Controller', return_value=controller):
            self.assertEqual(main(self.arguments), 0)
        controller.apply.assert_called_once_with(self.plan)

    def test_recovery_rehearsal_refuses_before_loading_config_without_explicit_fixture_optin(self):
        from tools.local.rehearse_recovery import main as rehearse
        with patch.dict('os.environ', {'HEIST_PRIVILEGED_TESTS': '0'}), \
             patch('tools.local.rehearse_recovery.Deployment.load') as load:
            with self.assertRaisesRegex(RuntimeError, 'disposable heist-pilot'):
                rehearse(['--config', '/nonexistent/config', '--transaction', 'fixture', '--confirm-version', '0.2.0'])
            load.assert_not_called()


class NativePlatformAdmissionTests(unittest.TestCase):
    def test_platform_rehearsal_requires_isolation_optin_before_loading_deployment(self):
        from tools.local.rehearse_platform import main as rehearse
        with patch.dict('os.environ',{'HEIST_PRIVILEGED_TESTS':'0'}),patch('tools.local.rehearse_platform.Deployment.load') as load:
            with self.assertRaisesRegex(RuntimeError,'disposable heist-pilot'):
                rehearse(['--config','/missing/config','--checkpoint','/missing/checkpoint','--target','candidate',
                          '--ui-bundle','/missing/ui','--runtime-bundle','/missing/runtime','--output','/missing/receipt'])
            load.assert_not_called()


class ExternalBaselineAuditTests(unittest.TestCase):
    def test_external_dump_and_unsupported_source_flag_never_bypass_isolation(self):
        from tools.local.rehearse_migrations import main as rehearse
        with patch.dict('os.environ',{'HEIST_PRIVILEGED_TESTS':'0'}),patch('tools.local.rehearse_migrations.Deployment.load') as load:
            with self.assertRaisesRegex(RuntimeError,'disposable heist-pilot'):
                rehearse(['--config','/missing','--output','/missing','--baseline-dump','/private/database.backup',
                    '--baseline-source','e'*40,'--baseline-sha256','a'*64,'--audit-unsupported-source'])
            load.assert_not_called()

    def test_external_dump_requires_private_ownership_exact_digest_and_archive_header(self):
        from tools.local.rehearse_migrations import external_baseline_source
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'database.backup';path.write_bytes(b'PGDMP-reviewed-fixture');path.chmod(0o600)
            digest=sha256(path)
            with patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=0,st_mode=0o100600)):
                self.assertEqual(external_baseline_source(path,digest,'e'*40),'e'*40)
                with self.assertRaisesRegex(RuntimeError,'reviewed checksum'):
                    external_baseline_source(path,'b'*64,'e'*40)
            for owner,mode in ((1000,0o100600),(0,0o100644)):
                with patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=owner,st_mode=mode)):
                    with self.assertRaisesRegex(RuntimeError,'private root-owned'):
                        external_baseline_source(path,digest,'e'*40)
            path.write_bytes(b'invalid dump')
            with patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=0,st_mode=0o100600)):
                with self.assertRaisesRegex(RuntimeError,'custom archive'):
                    external_baseline_source(path,sha256(path),'e'*40)
