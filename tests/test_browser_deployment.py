"""Execute the bounded SSH bootstrap and verify checkpointed template adoption."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from heist.rollout.browser_deployment import BOOTSTRAP, adopt_templates, credentials, deploy_guest, package
from heist.rollout.template_checkpoint import identity
from heist.runtime_bundle import digest
from tests.test_runtime_bundle import COMMIT, bundle as runtime_bundle
from tests.test_ui_assets import bundle as ui_bundle


class BrowserDeploymentTests(unittest.TestCase):
    def test_bootstrap_delivers_private_configuration_and_verified_artifacts_without_shell_evaluation(self):
        # Harmless source fixture executes in the real isolated bootstrap process.
        def source(files):
            files['source/heist/rollout/browser_guest.py'] = b'import json,sys; value=json.load(sys.stdin); print(json.dumps({"commit":value["commit"],"runtime_exists":__import__("pathlib").Path(value["runtime_bundle"]).is_file()}))\n'
        config = {'commit': COMMIT, 'password': 'test-only-private-value'}
        payload = package(runtime_bundle(source), ui_bundle(standalone=True), config, COMMIT)
        result = subprocess.run([sys.executable,'-c',BOOTSTRAP,digest(payload)],input=payload,capture_output=True,check=True,timeout=30)
        self.assertEqual(json.loads(result.stdout), {'commit': COMMIT, 'runtime_exists': True})
        self.assertNotIn(config['password'].encode(),result.stdout)
        altered = subprocess.run([sys.executable,'-c',BOOTSTRAP,'0'*64],input=payload,capture_output=True,timeout=30)
        self.assertNotEqual(altered.returncode,0)
        self.assertIn(b'checksum differs',altered.stderr)

    def test_bootstrap_retains_native_agent_failure_diagnostics_without_configuration(self):
        def source(files):
            files['source/heist/rollout/browser_guest.py'] = b'import sys; sys.stderr.write("native agent diagnostic\\n"); raise SystemExit(19)\n'
        config = {'commit': COMMIT, 'password': 'private-value-must-stay-on-stdin'}
        payload = package(runtime_bundle(source), ui_bundle(standalone=True), config, COMMIT)
        result = subprocess.run([sys.executable,'-c',BOOTSTRAP,digest(payload)],input=payload,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,19)
        self.assertEqual(result.stderr,b'native agent diagnostic\n')
        self.assertEqual(result.stdout,b'')
        self.assertNotIn(config['password'].encode(),result.stderr)

    def test_bootstrap_refuses_traversal_even_with_a_matching_transport_digest(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            member=tarfile.TarInfo('../outside');member.size=4
            archive.addfile(member,io.BytesIO(b'nope'))
        payload=stream.getvalue()
        result=subprocess.run([sys.executable,'-c',BOOTSTRAP,digest(payload)],input=payload,capture_output=True,timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Unsafe browser deployment package',result.stderr)

    def test_guest_deployment_refuses_before_transport_without_a_complete_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter=SimpleNamespace(marker=Path(temporary)/'maintenance',config=Mock())
            transaction=SimpleNamespace(data={'checkpoint_ready':False})
            with self.assertRaisesRegex(RuntimeError,'complete checkpoint'):deploy_guest(adapter,transaction)
            adapter.config.assert_not_called()

    def test_private_browser_credentials_survive_retry_without_rotating_or_exposing_the_password(self):
        with tempfile.TemporaryDirectory() as temporary:
            transaction=SimpleNamespace(data={'backup_directory':temporary})
            first=credentials(transaction)
            self.assertEqual(first,credentials(transaction))
            path=Path(temporary)/'browser-credentials.json'
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError,'private'):credentials(transaction)

    def test_all_template_identities_are_checked_before_any_ownership_label_is_written(self):
        saved={'template':'1','name':'owned','smbios1':'uuid=5898f7b2-d8bd-42e0-a43e-d90f0f7d19b6'}
        checkpoint=identity(saved)
        adapter=SimpleNamespace(configuration=Mock(side_effect=[saved,{**saved,'name':'foreign'}]),is_running=Mock(return_value=False),command=Mock())
        transaction=SimpleNamespace(data={'template_catalogue':{'123':checkpoint,'124':checkpoint}})
        with self.assertRaisesRegex(RuntimeError,'foreign template'):adopt_templates(adapter,transaction)
        adapter.command.assert_not_called()
        adapter.configuration=Mock(return_value={**saved,'tags':'teaching'})
        transaction.data['template_catalogue']={'123':checkpoint}
        adopt_templates(adapter,transaction)
        args=adapter.command.call_args.args[0]
        self.assertIn('heist-managed;heist-vm-123;teaching',args)
        self.assertIn('Managed by heiST; machine-template=123',args)
