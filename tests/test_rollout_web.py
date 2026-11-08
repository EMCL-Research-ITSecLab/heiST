"""Maintenance rules preserve other chains; guard failures block Apache at boot."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from heist.rollout import guest_agent, guest_firewall


class WebMaintenanceTests(unittest.TestCase):
    def test_legacy_role_inspection_returns_only_one_deployed_role(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);environment=root/'.env';config={'root':str(root/'html')}
            environment.write_text('DB_PASSWORD=never-return-this\nDB_USER="api_user" # deployed\n')
            self.assertEqual(guest_agent.legacy_database_user(config),'api_user')
            environment.write_text('DB_USER=api_user\nDB_USER=another\n')
            with self.assertRaisesRegex(RuntimeError,'exactly one'):guest_agent.legacy_database_user(config)
            environment.unlink();environment.symlink_to(root/'missing')
            with self.assertRaisesRegex(RuntimeError,'regular'):guest_agent.legacy_database_user(config)

    def test_runtime_marker_is_visible_without_access_to_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'public-marker'
            guest_firewall.sync_public_marker(True, marker)
            self.assertEqual(marker.read_text(), 'maintenance\n')
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            guest_firewall.sync_public_marker(False, marker)
            self.assertFalse(marker.exists())
            target = Path(directory)/'private';target.write_text('untouched')
            marker.symlink_to(target)
            with self.assertRaises(ValueError):
                guest_firewall.sync_public_marker(True, marker)
            self.assertEqual(target.read_text(), 'untouched')

    def test_only_the_known_previous_guard_can_be_upgraded(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = '# previous trusted guard'
            program = root/'program.py';program.write_text(previous)
            with patch.multiple(guest_agent, STATE=root/'state', PROGRAM=program,
                                UNIT=root/'guard.service', CRON_GUARD=root/'cron.d/guard.conf',
                                APACHE_GUARD=root/'apache.d/guard.conf',
                                PREVIOUS_FIREWALL_SHA256=hashlib.sha256(previous.encode()).hexdigest()), patch.object(guest_agent.subprocess, 'run'):
                guest_agent.install_guard({'program': '# current trusted guard'})
                self.assertEqual(program.read_text(), '# current trusted guard')
                program.write_text('# unexpected local modification')
                with self.assertRaisesRegex(RuntimeError, 'unknown maintenance guard'):
                    guest_agent.install_guard({'program': '# current trusted guard'})
                self.assertEqual(program.read_text(), '# unexpected local modification')

    def test_rules_cover_both_families_and_leave_loopback_and_other_ports(self):
        run = Mock(return_value=Mock(returncode=1))
        guest_firewall.configure(True, run)
        restores = [call for call in run.call_args_list if call.kwargs.get('check')]
        self.assertEqual(len(restores), 2)
        self.assertEqual({call.args[0][0] for call in restores}, {'iptables-restore', 'ip6tables-restore'})
        for call in restores:
            rules = call.kwargs['input']
            self.assertIn('! -i lo -p tcp -m multiport --dports 80,443', rules)
            self.assertIn('--noflush', call.args[0])
            self.assertNotIn('-F INPUT', rules)
            self.assertNotIn('22', rules)

    def test_removal_changes_only_owned_chain(self):
        run = Mock(return_value=Mock(returncode=0))
        guest_firewall.configure(False, run)
        for call in run.call_args_list:
            if call.kwargs.get('check'):
                self.assertEqual(call.kwargs['input'], '*filter\n-D INPUT -j HEIST_WEB_MAINT\n-F HEIST_WEB_MAINT\n-X HEIST_WEB_MAINT\nCOMMIT\n')

    def test_persistent_guard_is_executable_through_python_and_required_by_apache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(guest_agent, STATE=root/'state', PROGRAM=root/'program.py',
                                UNIT=root/'guard.service', CRON_GUARD=root/'cron.d/guard.conf',
                                APACHE_GUARD=root/'apache.d/guard.conf'), patch.object(guest_agent.subprocess, 'run'):
                guest_agent.install_guard({'program': '# trusted guard'})
                self.assertIn('ExecStart=/usr/bin/python3 ', (root/'guard.service').read_text())
                self.assertIn('Requires=heist-web-maintenance.service', (root/'apache.d/guard.conf').read_text())
                self.assertIn('ConditionPathExists=!/var/lib/heist/maintenance', (root/'cron.d/guard.conf').read_text())
                self.assertTrue((root/'state/maintenance').exists())

    def test_web_drift_collision_and_escape_are_rejected_before_deployment(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'index.php').write_bytes(b'original')
            metadata = {'root': str(root), 'before': {'index.php': hashlib.sha256(b'original').hexdigest()}, 'after': {'index.php': None}}
            guest_agent.validate_sources(metadata)
            (root/'index.php').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'source changed'):
                guest_agent.validate_sources(metadata)
            for path in ('../outside', '/absolute', './index.php'):
                with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                    guest_agent.validate_sources({'root': str(root), 'before': {}, 'after': {path: None}})
            with self.assertRaisesRegex(RuntimeError, 'collides'):
                guest_agent.validate_sources({'root': str(root), 'before': {}, 'after': {'index.php': None}})

    def test_runtime_dependency_and_environment_fingerprints_detect_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'html';root.mkdir()
            (root/'composer.lock').write_text('installed lock fixture')
            hashes = guest_agent.runtime_hashes({'root':str(root)})
            guest_agent.verify_runtime({'hashes':hashes})
            (root/'composer.lock').write_text('changed lock fixture')
            with self.assertRaisesRegex(RuntimeError,'Preserved web'):
                guest_agent.verify_runtime({'hashes':hashes})
