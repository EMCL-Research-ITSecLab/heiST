"""Exercise durable intent with real locks, real process loss and disk faults."""
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from heist.files import maintenance_lock
from heist.platform.jobs.journal import Journal, RecoveryRequired


def interrupted(directory, request_id):
    Journal(directory).execute('user', 1, 'launch', {'id': 2}, lambda: os._exit(23), request_id=request_id)


class OperationJournalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'operations'
        self.journal = Journal(self.root)
        self.identifier = 'a'*32

    def execute(self, function, **kwargs):
        return self.journal.execute('user', 1, 'launch', {'id': 2}, function, request_id=self.identifier, **kwargs)

    def test_successful_retry_returns_recorded_result_without_repeating_effects(self):
        effect = Mock(return_value=['entrypoint'])
        self.assertEqual(self.execute(effect), ['entrypoint'])
        restarted = Journal(self.root)
        self.assertEqual(restarted.execute('user', 1, 'launch', {'id': 2}, effect, request_id=self.identifier), ['entrypoint'])
        effect.assert_called_once()
        self.assertEqual(restarted.inspect('user', 1)['state'], 'SUCCEEDED')
        with self.assertRaises(RecoveryRequired):
            restarted.execute('user', 1, 'stop', {'id': 2}, effect, request_id=self.identifier)
        effect.assert_called_once()

    def test_actual_worker_exit_leaves_uncertain_intent_and_blocks_other_work(self):
        process = multiprocessing.get_context('fork').Process(target=interrupted, args=(self.root, self.identifier))
        process.start()
        process.join(10)
        self.assertEqual(process.exitcode, 23)
        self.assertEqual(self.journal.inspect('user', 1)['state'], 'NEEDS_REVIEW')
        effect = Mock()
        with self.assertRaises(RecoveryRequired):
            self.execute(effect)
        with self.assertRaises(RecoveryRequired):
            self.journal.execute('user', 1, 'stop', {}, effect)
        effect.assert_not_called()
        with self.assertRaises(RecoveryRequired):
            self.journal.resolve('user', 1, 'b'*32, 'Native resources independently reconciled')
        self.journal.resolve('user', 1, self.identifier, 'Native tasks finished and resources independently reconciled')
        self.assertEqual(self.journal.inspect('user', 1)['state'], 'RESOLVED')
        self.assertTrue(self.journal.execute('user', 1, 'stop', {}, lambda: True))
        with self.assertRaises(RecoveryRequired):
            self.execute(effect)

    def test_exceptions_record_review_and_intent_io_failure_prevents_effects(self):
        with patch('heist.platform.jobs.journal.write_json', side_effect=OSError('full')):
            effect = Mock()
            with self.assertRaises(OSError):
                self.execute(effect)
            effect.assert_not_called()
        with self.assertRaises(RuntimeError):
            self.execute(Mock(side_effect=RuntimeError('native outcome uncertain')))
        value = json.loads((self.root/'user-1'/(self.identifier+'.json')).read_text())
        self.assertEqual(value['state'], 'NEEDS_REVIEW')
        self.assertNotIn('native outcome', json.dumps(value))

    def test_live_operation_lease_blocks_second_writer_and_reports_running(self):
        directory = self.journal.resource('user', 1)
        with maintenance_lock(directory):
            with self.assertRaises(BlockingIOError):
                self.execute(Mock())
        def effect():
            self.assertEqual(self.journal.inspect('user', 1)['state'], 'RUNNING')
            return True
        self.assertTrue(self.execute(effect))

    def test_invalid_resource_key_and_idempotency_key_never_call_effect(self):
        effect = Mock()
        for scope, resource, identifier in (('user/..', 1, self.identifier), ('user', True, self.identifier),
                                             ('user', 1, '../../x'), ('user', 0, self.identifier)):
            with self.subTest(scope=scope, resource=resource), self.assertRaises(ValueError):
                self.journal.execute(scope, resource, 'launch', {}, effect, request_id=identifier)
        effect.assert_not_called()

    def test_checked_rejection_is_durable_but_allows_a_new_operation_identity(self):
        from heist.platform.jobs.journal import RejectedOperation
        effect=Mock(side_effect=RejectedOperation('Image is still required by an exercise'))
        with self.assertRaises(RejectedOperation):
            self.execute(effect)
        self.assertEqual(self.journal.inspect('user',1)['state'],'REJECTED')
        with self.assertRaises(RejectedOperation):
            self.execute(effect)
        effect.assert_called_once()
        self.assertTrue(self.journal.execute('user',1,'launch',{'id':2},lambda:True))

    def test_verified_review_retry_preserves_failure_and_never_replays_old_identity(self):
        with self.assertRaises(RuntimeError):
            self.execute(Mock(side_effect=RuntimeError('failed launch')))
        effect = Mock(return_value=True)
        new_id = 'b'*32
        checker = Mock(return_value=True)
        self.assertTrue(self.journal.execute('user',1,'launch',{'id':2},effect,
                                            request_id=new_id,retry_review=checker))
        old = json.loads((self.root/'user-1'/(self.identifier+'.json')).read_text())
        self.assertEqual(old['state'],'NEEDS_REVIEW')
        self.assertEqual(old['retry_unblocked_by'],new_id)
        checker.assert_called_once()
        with self.assertRaises(RecoveryRequired):
            self.execute(effect,retry_review=checker)
        effect.assert_called_once()

    def test_failed_cleanup_check_and_running_receipt_still_block_new_work(self):
        with self.assertRaises(RuntimeError):
            self.execute(Mock(side_effect=RuntimeError('failed launch')))
        effect = Mock()
        with self.assertRaises(RecoveryRequired):
            self.journal.execute('user',1,'launch',{},effect,retry_review=lambda previous:False)
        with self.assertRaises(OSError):
            self.journal.execute('user',1,'launch',{},effect,retry_review=Mock(side_effect=OSError('database unavailable')))
        current=self.root/'user-1/current.json'
        data=json.loads(current.read_text());data['state']='RUNNING';current.write_text(json.dumps(data))
        checker=Mock(return_value=True)
        with self.assertRaises(RecoveryRequired):
            self.journal.execute('user',1,'launch',{},effect,retry_review=checker)
        checker.assert_not_called()
        effect.assert_not_called()
