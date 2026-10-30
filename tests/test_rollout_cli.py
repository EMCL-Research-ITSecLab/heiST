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
