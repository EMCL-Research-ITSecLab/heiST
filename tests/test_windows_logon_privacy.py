import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class WindowsLogonPrivacyTests(unittest.TestCase):
    def test_warmup_hides_base_image_identity_without_embedding_a_student_name(self):
        source = Path(__file__).resolve().parents[1] / 'heist/platform/challenges/warmup.py'
        tree = ast.parse(source.read_text())
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'WINDOWS_LOGON_PRIVACY_COMMAND'
                    for target in node.targets)
        )
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == 'hide_windows_last_logged_on_user')
        command = ast.literal_eval(assignment.value)
        self.assertIn('DontDisplayLastUserName', command)
        self.assertIn('LastLoggedOnUser', command)
        self.assertIn('LastLoggedOnSAMUser', command)
        self.assertIn('DefaultUserName', command)
        self.assertNotIn('ctf_admin', command.lower())
        self.assertNotIn('student', command.lower())

        scope = {'WINDOWS_LOGON_PRIVACY_COMMAND': command, 'RuntimeError': RuntimeError}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), 'exec'), scope)
        ga = Mock()
        ga.exec.return_value = SimpleNamespace(exit_code=0, stderr='')
        scope['hide_windows_last_logged_on_user'](ga, 123)
        argv = ga.exec.call_args.args[0]
        self.assertEqual(argv[-1], command)
        self.assertEqual(ga.exec.call_args.kwargs['timeout'], 30)

    def test_warmup_calls_privacy_guard_before_windows_network_configuration(self):
        source = Path(__file__).resolve().parents[1] / 'heist/platform/challenges/warmup.py'
        function = next(
            node for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.FunctionDef)
            and node.name == 'configure_ipv6_and_wazuh_windows'
        )
        calls = [node.func.id for node in ast.walk(function)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn('hide_windows_last_logged_on_user', calls)


if __name__ == '__main__':
    unittest.main()
