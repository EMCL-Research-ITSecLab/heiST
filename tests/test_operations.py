"""Administrator diagnostics use read-only, bounded, sanitized infrastructure data."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, Mock

from heist.platform.operations import archive_status, collect, release_status, service_states


class OperationsTests(unittest.TestCase):
    def receipt(self, **changes):
        value = {'schema': 1, 'source': 'web', 'status': 'success', 'started_at': '2026-10-30T10:00:00+00:00',
                 'completed_at': '2026-10-30T10:01:00+00:00', 'last_success_at': '2026-10-30T10:01:00+00:00',
                 'counters': {'verified': 3, 'copied': 1, 'private': 'do-not-return'}}
        value.update(changes)
        return json.dumps(value).encode()

    def test_archive_receipt_is_sanitized_and_staleness_is_detected(self):
        settings = {'HEIST_ARCHIVE_STATUS_HOST': 'archive', 'HEIST_ARCHIVE_STATUS_FILE': '/archive/status.json'}
        now = datetime(2026, 10, 30, 10, 5, tzinfo=timezone.utc)
        result = archive_status(settings, now=now, read_remote=lambda: self.receipt(password='do-not-return'))
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['counters'], {'verified': 3, 'copied': 1})
        self.assertNotIn('do-not-return', json.dumps(result))
        self.assertEqual(archive_status(settings, now=now+timedelta(hours=1), read_remote=lambda: self.receipt())['status'], 'stale')

    def test_archive_configuration_absence_or_invalid_remote_data_is_explicit(self):
        self.assertEqual(archive_status({})['status'], 'not configured')
        settings = {'HEIST_ARCHIVE_STATUS_HOST': 'archive', 'HEIST_ARCHIVE_STATUS_FILE': '/archive/status.json'}
        for body in (b'x'*65537, b'invalid json', self.receipt(started_at='invalid', completed_at=None), self.receipt(source='../private')):
            self.assertEqual(archive_status(settings, read_remote=lambda: body)['status'], 'unavailable')
        self.assertEqual(archive_status(settings, read_remote=Mock(side_effect=subprocess.TimeoutExpired('ssh', 5)))['status'], 'unavailable')

    def test_database_failure_closes_connection_and_is_visible(self):
        db = MagicMock()
        db.cursor.side_effect = RuntimeError('secret database error')
        with tempfile.TemporaryDirectory() as directory:
            report = collect(lambda: db, {'HEIST_STATE_DIRECTORY': directory}, Path(directory)/'maintenance', services=lambda: [], archive=lambda: {})
        db.set_session.assert_called_once_with(readonly=True)
        db.close.assert_called_once()
        self.assertEqual(report['database'], 'unavailable')
        self.assertNotIn('secret', json.dumps(report))

    def test_counts_use_read_only_transactions_and_expose_no_user_records(self):
        db = MagicMock()
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [('READY', 4), ('ACTIVE', 2)]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'maintenance'
            marker.touch()
            result = collect(lambda: db, {'HEIST_STATE_DIRECTORY': directory}, marker, services=lambda: [], archive=lambda: {})
        self.assertEqual(result['lifecycle'], {'READY': 4, 'ACTIVE': 2})
        self.assertTrue(result['maintenance'])
        self.assertEqual(result['database'], 'ready')
        self.assertTrue(all(not call.args[0].startswith(('INSERT', 'DELETE', 'UPDATE')) for call in cursor.execute.call_args_list))

    def test_release_receipt_does_not_expose_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'installed.json').write_text(json.dumps({'commit': 'a'*40, 'version': '0.3.0', 'backup_directory': '/private'}))
            (root/'active.json').write_text('{"transaction":"../escape"}')
            result = release_status(root)
            self.assertEqual(result['commit'], 'a'*40)
            self.assertIsNone(result['active_transaction'])
            self.assertNotIn('/private', json.dumps(result))

    def test_systemd_probe_has_fixed_units_no_shell_and_bounded_timeout(self):
        run = Mock(return_value=type('Result', (), {'stdout': 'Id=backend.service\nActiveState=active\nSubState=running\n'})())
        result = service_states(run)
        self.assertEqual(result[0]['state'], 'active')
        self.assertEqual(result[1]['state'], 'unknown')
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
