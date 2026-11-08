"""QGA writes cannot silently truncate data or replay ambiguous commands."""
import base64
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from heist.infrastructure.proxmox.guest_agent import GuestAgent, GuestAgentError, GATimeoutError, ExecResult


def agent():
    with patch('heist.infrastructure.proxmox.guest_agent._resolve_socket_path', return_value=Path('/unused/test.qga')):
        value = GuestAgent(123)
    value._transport = Mock(connected=True)
    return value


class GuestFileTests(unittest.TestCase):
    def test_complete_utf8_write_requires_byte_count_flush_close_and_permissions(self):
        value = agent(); events = []
        def call(command, arguments, **kwargs):
            events.append(command)
            if command == 'guest-file-open': return 7
            if command == 'guest-file-write':
                self.assertEqual(base64.b64decode(arguments['buf-b64']), 'ä'.encode())
                return {'count': 2}
        value._transport.call.side_effect = call
        value.exec = Mock(return_value=ExecResult(pid=1, exit_code=0))
        value.write_file('/staged/config', 'ä', unix_mode=0o600)
        self.assertEqual(events, ['guest-file-open','guest-file-write','guest-file-flush','guest-file-close'])
        value.exec.assert_called_once_with(['chmod','600','/staged/config'],capture_output=False,timeout=10)

    def test_short_or_unconfirmed_writes_never_flush_or_report_success(self):
        for result in ({'count': 1}, {'count': True}, {'count': 3}, {}, None):
            with self.subTest(result=result):
                value = agent(); value._transport.call.side_effect = [7, result, None]
                with self.assertRaisesRegex(GuestAgentError, 'incomplete or unconfirmed'):
                    value.write_file('/staged/config', b'xx')
                self.assertEqual([call.args[0] for call in value._transport.call.call_args_list],
                                 ['guest-file-open','guest-file-write','guest-file-close'])

    def test_flush_close_and_permission_failures_cannot_report_success(self):
        for stage in ('guest-file-flush','guest-file-close'):
            value = agent()
            def call(command, arguments, **kwargs):
                if command == stage: raise GuestAgentError(stage)
                return 7 if command == 'guest-file-open' else {'count': 2}
            value._transport.call.side_effect = call
            with self.subTest(stage=stage), self.assertRaisesRegex(GuestAgentError, stage):
                value.write_file('/staged/config', b'xx')
        value = agent();value._transport.call.side_effect = [7, {'count': 2}, None, None]
        value.exec = Mock(return_value=ExecResult(pid=1, exit_code=1))
        with self.assertRaisesRegex(GuestAgentError, 'permission'):
            value.write_file('/staged/config', b'xx', unix_mode=0o600)

    def test_original_write_failure_survives_a_cleanup_failure(self):
        value = agent(); original = GuestAgentError('original write failure')
        value._transport.call.side_effect = [7, original, GuestAgentError('close failure')]
        with self.assertRaises(GuestAgentError) as caught:value.write_file('/staged/config', b'xx')
        self.assertIs(caught.exception, original)

    def test_ambiguous_commands_and_file_offsets_are_not_replayed(self):
        for command in ('guest-exec','guest-file-open','guest-file-write','guest-file-read','guest-file-flush','guest-file-close'):
            value = agent(); original = GATimeoutError('response lost')
            value._transport.call.side_effect = [original, {'count': 2}]
            with self.subTest(command=command), self.assertRaises(GATimeoutError):value._call(command, {'handle': 7})
            value._transport.call.assert_called_once_with(command, {'handle': 7}, timeout=None)
            value._transport.close.assert_called_once_with(); value._transport.connect.assert_not_called()

    def test_status_poll_reconnects_without_starting_another_process(self):
        value = agent(); value._transport.call.side_effect = [GATimeoutError('response lost'), {'exited': True}]
        self.assertEqual(value._call('guest-exec-status', {'pid': 321}), {'exited': True})
        self.assertEqual([call.args[:2] for call in value._transport.call.call_args_list],
                         [('guest-exec-status', {'pid':321}), ('guest-exec-status', {'pid':321})])
        value._transport.connect.assert_called_once_with()
