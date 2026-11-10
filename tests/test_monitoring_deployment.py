"""Monitoring installation files participate in host checkpoint/recovery."""
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from heist.rollout import monitoring_deployment as deployment
from heist.rollout.pve import PVE


class MonitoringDeploymentTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(vms=tuple(SimpleNamespace(role=role,host=role+'.example.invalid',user='root' if role!='monitoring' else 'ubuntu')
                               for role in ('web','database','monitoring')),backend_env='/srv/heist/config/backend.env',api_certificate='/etc/pve/root.pem')

    def test_configuration_uses_infrastructure_identities_and_separate_archive_admin_account(self):
        config=deployment.configuration(self.config(),{'HEIST_ARCHIVE_STATUS_HOST':'archive.example.invalid','HEIST_ARCHIVE_STATUS_USER':'heist-archive'})
        self.assertEqual(len(config['remotes']),4)
        self.assertEqual(config['remotes'][-1]['user'],'ubuntu')
        self.assertEqual(config['remotes'][0]['user'],'root')
        with self.assertRaises(ValueError):deployment.configuration(self.config(),{'HEIST_ARCHIVE_STATUS_HOST':'host; command'})

    def test_source_bound_units_adapt_installation_and_private_environment_paths(self):
        root=Path(__file__).resolve().parents[1]
        adapter=SimpleNamespace(config=self.config(),installation=Path('/srv/heist'),environment={})
        with patch('heist.rollout.monitoring_deployment.blob',side_effect=lambda repo,commit,name:(root/name).read_bytes()) as read:
            files=deployment.files(adapter,'a'*40)
        self.assertEqual(set(files),set(deployment.paths()))
        body,mode=files[Path('/etc/systemd/system/heist-monitoring.service')]
        self.assertIn(b'/srv/heist/.venv/bin/python',body)
        self.assertIn(b'--environment /srv/heist/config/backend.env',body)
        self.assertEqual(mode,0o644)
        config,mode=files[deployment.CONFIGURATION]
        self.assertEqual(mode,0o600)
        self.assertEqual(len(json.loads(config)['remotes']),3)
        self.assertTrue(all(call.args[1]=='a'*40 for call in read.call_args_list))

    def test_monitoring_files_and_service_states_are_included_in_recovery_inventory(self):
        adapter=object.__new__(PVE);adapter.config=self.config();adapter.installation=Path('/srv/heist');adapter.environment={};adapter.state=Path('/var/lib/heist')
        self.assertTrue(set(deployment.paths()).issubset(adapter.host_configuration_paths()))
        self.assertTrue(set(deployment.UNITS).issubset(PVE.units))
        states=deployment.target_services()
        self.assertTrue(states['heist-monitoring.timer']['active'])
        self.assertFalse(states['heist-monitoring.service']['active'])
