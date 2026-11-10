"""Monitoring deletion must prove absence/completion and authenticate its peer."""
import json
import unittest
from unittest.mock import Mock
import requests

from heist.infrastructure.monitoring.wazuh import Wazuh


def response(data, *, raw=False, status=200):
    value = Mock(status_code=status)
    payload = data.encode() if raw else json.dumps(data).encode()
    value.iter_content.return_value = [payload]
    return value


def result(items, **extra):
    return {'error': 0, 'data': {'affected_items': items, 'total_failed_items': 0, **extra}}


class WazuhTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = Wazuh('fd12:3456::103', 55000, 'test-user', 'private-test-password', session=self.session)

    def test_absent_agent_is_success_only_after_authenticated_valid_inventory(self):
        replies = [response('a.b.c', raw=True), response(result([]))]
        self.session.request.side_effect = replies
        self.assertTrue(self.client.remove_agent(123))
        self.assertEqual(self.session.request.call_count, 2)
        self.assertEqual(self.session.request.call_args.args, ('GET', 'https://[fd12:3456::103]:55000/agents'))
        for call in self.session.request.call_args_list:
            self.assertIs(call.kwargs['verify'], True)
            self.assertFalse(call.kwargs['allow_redirects'])
            self.assertEqual(call.kwargs['timeout'], (3, 10))
        self.assertTrue(all(reply.close.call_count == 1 for reply in replies))
        self.client.close()
        self.session.close.assert_called_once()

    def test_exact_agent_is_removed_and_partial_failure_cannot_free_its_identity(self):
        inventory = [{'id': '042', 'name': 'Agent_123'}]
        self.session.request.side_effect = [response('a.b.c', raw=True), response(result(inventory)), response(result(['042']))]
        self.assertTrue(self.client.remove_agent(123))
        self.assertEqual(self.session.request.call_args.kwargs['params']['agents_list'], '042')
        self.session.request.side_effect = [response('a.b.c', raw=True), response(result(inventory)), response(result([], total_failed_items=1))]
        with self.assertRaises(RuntimeError):
            self.client.remove_agent(123)

    def test_wrong_identity_manager_id_invalid_inventory_and_authentication_are_rejected(self):
        for inventory in (None, [{'id': '000', 'name': 'Agent_123'}], [{'id': '042', 'name': 'another-agent'}], [{'id': '042', 'name': 'agent_123'}], [{'id': '042', 'name': 'Agent_123'}, {'id': '043', 'name': 'Agent_123'}]):
            self.session.reset_mock()
            self.session.request.side_effect = [response('a.b.c', raw=True), response(result(inventory))]
            with self.subTest(inventory=inventory), self.assertRaises(RuntimeError):
                self.client.remove_agent(123)
            self.assertEqual(self.session.request.call_count, 2)
        self.session.request.side_effect = [response('invalid token\nheader', raw=True)]
        with self.assertRaises(RuntimeError):
            self.client.remove_agent(123)

    def test_cleanup_uses_the_name_registered_by_provisioning(self):
        from pathlib import Path
        import ast
        source = Path(__file__).resolve().parents[1]/'heist/platform/challenges/warmup.py'
        assignments = [node.value for node in ast.walk(ast.parse(source.read_text()))
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'agent_name'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 2)
        for value in assignments:
            self.assertIsInstance(value, ast.JoinedStr)
            self.assertEqual(value.values[0].value, 'Agent_')
        self.session.request.side_effect = [response('a.b.c', raw=True), response(result([]))]
        self.assertTrue(self.client.remove_agent(123))
        self.assertEqual(self.session.request.call_args.kwargs['params'], {'name': 'Agent_123'})

    def test_transport_error_redirect_and_malformed_json_are_closed_without_private_error(self):
        for reply in (response('ignored', raw=True, status=307), response('not-json', raw=True)):
            self.session.request.side_effect = None
            self.session.request.return_value = reply
            with self.assertRaises(RuntimeError):
                self.client.call('GET', '/agents')
            reply.close.assert_called_once()
        self.session.request.side_effect = requests.Timeout('private-test-password')
        with self.assertRaises(RuntimeError) as error:
            self.client.remove_agent(123)
        self.assertNotIn('private-test-password', str(error.exception))

    def test_disabled_tls_missing_credentials_and_invalid_hosts_never_create_a_session(self):
        for host in ('https://evil.invalid/path', 'host\nheader', ''):
            with self.assertRaises(ValueError):
                Wazuh(host, 55000, 'user', 'password')
        for certificate in (False, 0, '', 'relative.pem'):
            with self.assertRaises(ValueError):
                Wazuh('monitor.invalid', 55000, 'user', 'password', certificate=certificate)
        with self.assertRaises(ValueError):
            Wazuh('monitor.invalid', 55000, 'user', None)

    def test_trusted_legacy_leaf_is_pinned_without_disabling_ca_verification(self):
        import hashlib,ssl,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'leaf.pem'
            path.write_text('-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n')
            session=Mock()
            client=Wazuh('monitoring.invalid',55000,'test-user','private-test-password',pinned_certificate=str(path),session=session)
            self.assertEqual(client.certificate,str(path))
            adapter=session.mount.call_args.args[1]
            self.assertEqual(adapter.fingerprint,hashlib.sha256(b'abc').hexdigest())
            self.assertIs(adapter.poolmanager.connection_pool_kw['assert_hostname'],False)
            self.assertEqual(adapter.poolmanager.connection_pool_kw['assert_fingerprint'],adapter.fingerprint)
