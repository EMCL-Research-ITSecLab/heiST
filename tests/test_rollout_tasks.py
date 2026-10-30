"""Real journals exercise uncertain submissions and explicitly retried restores."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

from heist.rollout.controller import Transaction
from heist.rollout.tasks import Tasks


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transaction = Transaction(Path(self.temp.name), {})
        self.request = Mock()
        self.tasks = Tasks('pve', self.request)
        self.upid = 'UPID:pve:0001:0002:0003:qmrestore:1000:root@pam:'

    def uncertain(self):
        self.request.side_effect = TimeoutError('uncertain response')
        with self.assertRaises(TimeoutError):
            self.tasks.run(self.transaction, 'restore-web', '/nodes/pve/qemu', {'vmid': 1000})
        self.request.reset_mock(side_effect=True)
        return self.transaction.data['tasks']['restore-web']

    def test_uncertain_submission_never_blindly_reposts(self):
        self.uncertain()
        with self.assertRaisesRegex(RuntimeError, 'unknown'):
            self.tasks.run(self.transaction, 'restore-web', '/nodes/pve/qemu', {'vmid': 1000})
        self.request.assert_not_called()

    def test_adoption_checks_identity_and_exact_request(self):
        job = self.uncertain()
        self.request.return_value = {'type': 'qmrestore', 'id': '1000', 'starttime': job['submitted_at']}
        with self.assertRaises(ValueError):
            self.tasks.reconcile(self.transaction, 'restore-web', 'wrong', upid=self.upid)
        self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], upid=self.upid)
        self.assertEqual(job['upid'], self.upid)
        self.assertEqual(Transaction.load(self.transaction.path).data['tasks']['restore-web']['upid'], self.upid)

    def test_wrong_vm_or_older_task_cannot_be_adopted(self):
        job = self.uncertain()
        for status in ({'type': 'qmrestore', 'id': '2000', 'starttime': job['submitted_at']},
                       {'type': 'qmrestore', 'id': '1000', 'starttime': job['submitted_at'] - 30},
                       {'type': 'qmrestore', 'id': '1000', 'starttime': job['submitted_at'] + 30}):
            self.request.return_value = status
            with self.assertRaises(ValueError):
                self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], upid=self.upid)
        self.assertIsNone(job['upid'])

    def test_only_failed_stopped_restore_can_be_retried(self):
        job = self.uncertain()
        job['upid'] = self.upid
        for status in ({'status': 'running'}, {'status': 'stopped', 'exitstatus': 'OK'}):
            self.request.return_value = status
            with self.assertRaises(RuntimeError):
                self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], retry=True)
        self.request.return_value = {'status': 'stopped', 'exitstatus': 'disk error'}
        self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], retry=True)
        self.assertTrue(job['retry_authorized'])
        self.assertEqual(job['attempts'][0]['upid'], self.upid)
        self.request.reset_mock()
        self.tasks.settle(self.transaction)
        self.request.assert_not_called()

    def test_reconciliation_is_forbidden_after_write_boundary(self):
        job = self.uncertain()
        for boundary in ('committed', 'recovery_committed'):
            self.transaction.data[boundary] = True
            with self.assertRaises(RuntimeError):
                self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], upid=self.upid)

    def test_retry_authorization_is_consumed_before_uncertain_resubmission(self):
        job = self.uncertain()
        job.update(upid=self.upid)
        self.request.return_value = {'status': 'stopped', 'exitstatus': 'error'}
        self.tasks.reconcile(self.transaction, 'restore-web', job['request_sha256'], retry=True)
        self.request.side_effect = TimeoutError('response lost')
        with self.assertRaises(TimeoutError):
            self.tasks.run(self.transaction, 'restore-web', '/nodes/pve/qemu', {'vmid': 1000})
        self.assertFalse(job['retry_authorized'])
        self.request.reset_mock(side_effect=True)
        with self.assertRaisesRegex(RuntimeError, 'unknown'):
            self.tasks.run(self.transaction, 'restore-web', '/nodes/pve/qemu', {'vmid': 1000})
        self.request.assert_not_called()
