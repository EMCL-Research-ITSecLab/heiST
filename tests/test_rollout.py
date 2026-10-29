"""Recovery policy tests with deterministic host failures and real durable journals."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from heist.rollout.controller import Controller, Transaction
from heist.rollout.manifest import Plan


class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)/'state'
        self.operations=Mock()
        self.controller=Controller(self.state,self.operations)
        self.plan=Plan(1,'/root/heiST','old','new','0.2.0','releases/0.2.0.json','manifest','config',(),(),(),source_version='0.1.0')
        def checkpoint(transaction):transaction.save(snapshots={'verified':'fixture'})
        self.operations.checkpoint.side_effect=checkpoint

    def transaction(self):
        return Transaction.load(next((self.state/'transactions').iterdir()))

    def test_success_commits_before_resuming_writers(self):
        def finish(transaction):self.assertTrue(transaction.data['committed'])
        self.operations.finish.side_effect=finish
        result=self.controller.apply(self.plan)
        self.assertEqual(result.data['phase'],'COMPLETE')
        self.assertFalse((self.state/'active.json').exists())
        self.operations.restore.assert_not_called()
        self.assertEqual(json.loads((self.state/'installed.json').read_text())['commit'],'new')

    def test_preflight_failure_has_no_maintenance_or_checkpoint_effects(self):
        self.operations.preflight.side_effect=RuntimeError('not drained')
        with self.assertRaisesRegex(RuntimeError,'not drained'):self.controller.apply(self.plan)
        self.operations.quiesce.assert_not_called();self.operations.checkpoint.assert_not_called()

    def test_every_precommit_failure_recovers_without_resuming_unverified_new_code(self):
        for stage in ('quiesce','checkpoint','deploy','migrate','verify'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                operations=Mock()
                getattr(operations,stage).side_effect=[RuntimeError('failure'),None] if stage=='verify' else RuntimeError('failure')
                controller=Controller(Path(directory)/'state',operations)
                with self.assertRaisesRegex(RuntimeError,'failure'):controller.apply(self.plan)
                transaction=Transaction.load(next((Path(directory)/'state/transactions').iterdir()))
                self.assertEqual(transaction.data['phase'],'ROLLED_BACK')
                self.assertFalse(transaction.data['committed'])
                if stage in ('deploy','migrate','verify'):operations.restore.assert_called_once()
                else:operations.restore.assert_not_called()

    def test_failed_restore_leaves_active_recovery_journal_and_does_not_open_writes(self):
        self.operations.migrate.side_effect=RuntimeError('migration failed')
        self.operations.restore.side_effect=RuntimeError('disk restore failed')
        with self.assertRaisesRegex(RuntimeError,'disk restore failed'):self.controller.apply(self.plan)
        self.assertEqual(self.transaction().data['phase'],'RECOVERY_REQUIRED')
        self.assertTrue((self.state/'active.json').exists())
        self.operations.finish.assert_not_called()

    def test_restart_before_commit_recovers_checkpoint_instead_of_replaying_migrations(self):
        self.operations.migrate.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.controller.apply(self.plan)
        self.assertEqual(self.transaction().data['phase'],'MIGRATING')
        self.operations.reset_mock();self.operations.migrate.side_effect=None
        result=self.controller.resume()
        self.assertEqual(result.data['phase'],'ROLLED_BACK')
        self.operations.restore.assert_called_once();self.operations.migrate.assert_not_called()

    def test_postcommit_failure_never_automatically_restores_student_data(self):
        self.operations.finish.side_effect=RuntimeError('worker startup failed')
        with self.assertRaisesRegex(RuntimeError,'worker startup failed'):self.controller.apply(self.plan)
        self.assertEqual(self.transaction().data['phase'],'COMMIT_NEEDS_ATTENTION')
        self.assertTrue(self.transaction().data['committed'])
        self.operations.restore.assert_not_called()
        self.operations.finish.side_effect=None
        result=self.controller.resume()
        self.assertEqual(result.data['phase'],'COMPLETE')
        self.operations.restore.assert_not_called()

    def test_new_upgrade_is_refused_while_recovery_is_pending(self):
        self.operations.finish.side_effect=RuntimeError('blocked')
        with self.assertRaises(RuntimeError):self.controller.apply(self.plan)
        with self.assertRaisesRegex(RuntimeError,'unfinished'):self.controller.apply(self.plan)

    def test_manual_rollback_requires_release_confirmation_and_new_safety_checkpoint(self):
        original=self.controller.apply(self.plan)
        with self.assertRaises(ValueError):self.controller.rollback(original.path.name,confirm_version='wrong')
        self.operations.reset_mock()
        result=self.controller.rollback(original.path.name,confirm_version='0.2.0')
        self.assertEqual(result.plan.target,'old')
        self.assertEqual(result.plan.version,'0.1.0')
        self.operations.checkpoint.assert_called_once()
        self.operations.restore.assert_called_once()
        self.assertIs(self.operations.restore.call_args.args[0],result)
        self.assertEqual(self.operations.restore.call_args.kwargs['checkpoint'].path,original.path)
        self.assertTrue(result.data['checkpoint_ready'])

    def test_failed_manual_rollback_recovers_its_newer_safety_checkpoint(self):
        original=self.controller.apply(self.plan)
        self.operations.restore.side_effect=[RuntimeError('old snapshot read failed'),None]
        with self.assertRaisesRegex(RuntimeError,'old snapshot read failed'):
            self.controller.rollback(original.path.name,confirm_version='0.2.0')
        self.assertEqual(self.operations.restore.call_count,2)
        self.assertIsNone(self.operations.restore.call_args.kwargs.get('checkpoint'))

    def test_recovery_finish_failure_never_restores_again_after_writers_resume(self):
        self.operations.migrate.side_effect = RuntimeError('bad migration')
        self.operations.finish.side_effect = RuntimeError('startup failed')
        with self.assertRaisesRegex(RuntimeError, 'startup failed'):
            self.controller.apply(self.plan)
        self.assertTrue(self.transaction().data['recovery_committed'])
        self.operations.restore.assert_called_once()
        self.operations.reset_mock()
        self.operations.finish.side_effect = None
        result = self.controller.resume()
        self.assertEqual(result.data['phase'], 'ROLLED_BACK')
        self.operations.restore.assert_not_called()
        self.operations.verify.assert_not_called()
