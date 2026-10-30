import ast
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class AgentLoggingTests(unittest.TestCase):
    def test_label_restore_failure_prevents_reporting_success(self):
        for code in (0, 1):
            with self.subTest(restorecon_exit=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for command, status in (('install', 0), ('restorecon', code)):
                    helper = root / command
                    helper.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$TRACE"\nexit ' + str(status) + '\n')
                    helper.chmod(0o755)
                script = Path(__file__).resolve().parents[1] / 'heist/monitoring/wazuh/agent/linux/config/install_logging_files.sh'
                result = subprocess.run(['bash', str(script), '/staged-config'], capture_output=True,
                                        env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'], 'TRACE': str(root / 'trace')})
                self.assertEqual(result.returncode, code)
                trace = (root / 'trace').read_text().splitlines()
                self.assertEqual(len(trace), 4)
                self.assertIn('/usr/local/sbin/heist-bash-logging', trace[-1])
                self.assertIn('/etc/systemd/system/bash_loggin_systemd.service', trace[-1])
                self.assertIn('/etc/systemd/system/bash_loggin_timer.timer', trace[-1])

    def test_template_freeze_never_falls_back_to_forced_stop(self):
        source = Path(__file__).resolve().parents[1] / 'heist/backend/proxmox_api_calls.py'
        tree = ast.parse(source.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'shutdown_vm_api_call')
        namespace = {'subprocess': Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        namespace['shutdown_vm_api_call'](SimpleNamespace(id=123))
        args, kwargs = namespace['subprocess'].run.call_args
        self.assertEqual(args[0][:2], ['qm', 'shutdown'])
        self.assertNotIn('--skiplock', args[0])
        self.assertEqual(args[0][args[0].index('--forceStop') + 1], '0')
        self.assertTrue(kwargs['check'])
        self.assertGreater(kwargs['timeout'], 0)
        namespace['subprocess'].run.side_effect = TimeoutError('guest refused shutdown')
        with self.assertRaises(TimeoutError):
            namespace['shutdown_vm_api_call'](SimpleNamespace(id=123))
