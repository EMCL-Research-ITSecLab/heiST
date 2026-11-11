"""Worker deployment must retain source identity, environment and rollback paths."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from heist.rollout import administrator_deployment as deployment
from heist.rollout.pve import PVE


class AdministratorDeploymentTests(unittest.TestCase):
    def test_rollout_admission_rejects_pending_or_uncertain_administrator_work(self):
        adapter=object.__new__(PVE)
        adapter.database=MagicMock()
        cursor=adapter.database.connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect=[(0,),(0,),(True,),(1,)]
        with self.assertRaisesRegex(RuntimeError,'reconcile administrator requests'):
            adapter.assert_idle(allow_ready=True)
        self.assertIn('NEEDS_REVIEW',cursor.execute.call_args.args[0])
        adapter.database.connect.return_value.close.assert_called_once()

    def test_worker_requires_schema_contract_and_keeps_environment_in_service_section(self):
        self.assertFalse(deployment.enabled(SimpleNamespace(migrations=())))
        self.assertTrue(deployment.enabled(SimpleNamespace(migrations=(SimpleNamespace(identifier='0013_administrator_requests'),))))
        root=Path(__file__).resolve().parents[1]
        adapter=SimpleNamespace(installation=Path('/srv/heist'),config=SimpleNamespace(backend_env='/srv/heist/config/backend.env'),state=Path('/srv/private-state'))
        with patch('heist.rollout.administrator_deployment.blob',side_effect=lambda repo,commit,path:(root/path).read_bytes()) as read:
            files=deployment.files(adapter,'a'*40)
        body,mode=files[deployment.PATH];value=body.decode();service=value.split('[Service]',1)[1].split('[Install]',1)[0]
        self.assertEqual(mode,0o644)
        self.assertIn('ExecStart=/srv/heist/.venv/bin/python -m heist.platform.jobs.administrator --verify-runtime',service)
        self.assertIn('HEIST_BACKEND_ENV=/srv/heist/config/backend.env',service)
        self.assertIn('HEIST_INTERNAL_RUNTIME=/srv/private-state/internal-runtime/current',service)
        self.assertNotIn('Environment=',value.split('[Install]',1)[1])
        self.assertEqual(read.call_args.args[1],'a'*40)
        self.assertIn(deployment.UNIT,PVE.units)

    def test_worker_configuration_is_preserved_before_host_changes(self):
        adapter=object.__new__(PVE)
        adapter.config=SimpleNamespace(backend_env='/srv/heist/config/backend.env',api_certificate='/etc/pve/root.pem')
        adapter.environment={};adapter.installation=Path('/srv/heist');adapter.state=Path('/srv/private-state')
        self.assertIn(deployment.PATH,adapter.host_configuration_paths())
