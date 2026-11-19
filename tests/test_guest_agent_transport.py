"""Guest-agent replies must belong to this connection and this command."""
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

from heist.infrastructure.proxmox.guest_agent import (
    GuestAgent, GuestAgentError, GATimeoutError, _QEMUGATransport,
)


class GuestTransportTests(unittest.TestCase):
    def transport(self, chunks):
        transport = _QEMUGATransport(Path('/unused/test.qga'))
        transport._sock = Mock()
        transport._sock.recv.side_effect = chunks + [b'']
        self.addCleanup(transport.close)
        return transport

    def test_sync_discards_old_complete_and_partial_replies_and_retains_next_frame(self):
        transport = self.transport([
            b'{"return":{}}\n{"return":',
            b'\xff{"return":41}\n\xff{"ret',
            b'urn":42}\n{"return":{"pid":9},"id":"ours"}\n',
        ])
        with patch('heist.infrastructure.proxmox.guest_agent.secrets.randbits', return_value=42):
            transport._synchronize()
        payload = transport._sock.sendall.call_args.args[0]
        self.assertEqual(payload[:1], b'\xff')
        self.assertEqual(json.loads(payload[1:])['arguments'], {'id':42})
        with patch('heist.infrastructure.proxmox.guest_agent.secrets.token_hex', return_value='ours'):
            self.assertEqual(transport.call('guest-exec', {'path':'/bin/true'}), {'pid':9})

    def test_call_skips_stale_reply_and_matches_request_id(self):
        transport = self.transport([b'{"return":{}}\n{"id":"other","return":{}}\n'
                                    b'{"id":"ours","return":{"pid":123}}\n'])
        with patch('heist.infrastructure.proxmox.guest_agent.secrets.token_hex', return_value='ours'):
            self.assertEqual(transport.call('guest-exec', {'path':'/bin/true'}), {'pid':123})
        self.assertEqual(transport._sock.sendall.call_count, 1)

    def test_unmatched_reply_times_out_instead_of_replaying_execution(self):
        transport = self.transport([b'{"return":{}}\n', socket.timeout()])
        sock = transport._sock
        with self.assertRaises(GATimeoutError):
            transport.call('guest-exec', {'path':'/bin/true'})
        self.assertEqual(sock.sendall.call_count, 1)
        self.assertFalse(transport.connected)

    def test_invalid_execution_pid_is_clear_and_never_replayed(self):
        for result in ({}, None, {'pid':True}, {'pid':0}, {'pid':'123'}):
            with self.subTest(result=result), patch(
                'heist.infrastructure.proxmox.guest_agent._resolve_socket_path',
                return_value=Path('/unused/test.qga'),
            ):
                agent = GuestAgent(123)
                agent._call = Mock(return_value=result)
                with self.assertRaisesRegex(GuestAgentError, 'not replayed'):
                    agent._exec_socket(['/bin/true'], True, None, 1, .01, None)
                agent._call.assert_called_once()

    def test_cold_guest_retries_only_sync_within_socket_wait_budget(self):
        transport = _QEMUGATransport(Path('/unused/test.qga'))
        first, second = Mock(), Mock()
        with patch.object(Path, 'exists', return_value=True), patch(
            'heist.infrastructure.proxmox.guest_agent.os.access', return_value=True,
        ), patch('heist.infrastructure.proxmox.guest_agent.socket.socket', side_effect=[first, second]), patch.object(
            transport, '_synchronize', side_effect=[GATimeoutError('guest still booting'), None],
        ) as sync, patch.object(transport, '_drain'), patch(
            'heist.infrastructure.proxmox.guest_agent.time.sleep',
        ):
            transport.connect(wait_timeout=120)
            self.assertEqual(sync.call_count, 2)
            first.close.assert_called_once()
            first.sendall.assert_not_called()
            second.sendall.assert_not_called()
            self.assertTrue(transport.connected)
            transport.close()

    def test_cold_guest_does_not_retry_without_boot_wait_opt_in(self):
        transport = _QEMUGATransport(Path('/unused/test.qga'))
        with patch.object(Path, 'exists', return_value=True), patch(
            'heist.infrastructure.proxmox.guest_agent.os.access', return_value=True,
        ), patch('heist.infrastructure.proxmox.guest_agent.socket.socket'), patch.object(
            transport, '_synchronize', side_effect=GATimeoutError('not ready'),
        ) as sync, patch.object(transport, '_drain'):
            with self.assertRaises(GATimeoutError):
                transport.connect()
            sync.assert_called_once()
            self.assertFalse(transport.connected)
