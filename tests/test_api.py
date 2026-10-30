"""Real Flask requests; infrastructure boundaries are injected."""
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, Mock
from heist.backend.api import create_app


class APITests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.marker = Path(self.temp.name) / 'maintenance'
        self.launch, self.delete = Mock(return_value=['10.128.0.1']), Mock()
        self.db = MagicMock()
        self.db.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        self.connect = Mock(return_value=self.db)
        self.app = create_app({'TESTING': True, 'BACKEND_AUTHENTICATION_TOKEN': 'test-only', 'MAINTENANCE_FILE': str(self.marker)}, {
            'launch_challenge': self.launch, 'delete_user_config': self.delete,
            'delete_machine_templates': Mock(side_effect=RuntimeError('private failure')), 'get_db_connection': self.connect})
        self.client = self.app.test_client()

    def request(self, route='/launch-challenge', method='POST', **kwargs):
        return self.client.open(route, method=method, base_url='https://localhost',
            headers={'Authentication-Token': 'test-only'}, **kwargs)

    def test_all_routes_require_auth_before_side_effects(self):
        for route in self.app.url_map.iter_rules():
            if route.endpoint != 'static':
                result = self.client.open(str(route), method='POST' if 'POST' in route.methods else 'GET', base_url='https://localhost')
                self.assertEqual(result.status_code, 401)
        self.connect.assert_not_called()
        self.launch.assert_not_called()

    def test_unconfigured_token_fails_closed(self):
        self.app.config['BACKEND_AUTHENTICATION_TOKEN'] = None
        self.assertEqual(self.request(json={'user_id': 1, 'challenge_template_id': 2}).status_code, 401)

    def test_redirect_preserves_post_and_query(self):
        result = self.client.post('/launch-challenge?check=1', base_url='http://localhost')
        self.assertEqual(result.status_code, 307)
        self.assertEqual(result.headers['Location'], 'https://localhost/launch-challenge?check=1')

    def test_invalid_ids_never_reach_backend(self):
        for value in (True, False, 0, -1, 1.2, [], {}, '1;shutdown', '1.0', '١', 2**63, None):
            with self.subTest(value=value):
                self.assertEqual(self.request(json={'user_id': value, 'challenge_template_id': 2}).status_code, 400)
        self.launch.assert_not_called()

    def test_non_objects_and_missing_fields_are_bad_requests(self):
        for value in ([], 'hello', {}, None):
            self.assertEqual(self.request(json=value).status_code, 400)

    def test_normalises_string_ids_and_preserves_response(self):
        result = self.request(json={'user_id': '7', 'challenge_template_id': '2'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['entrypoints'], ['10.128.0.1'])
        self.assertEqual(self.launch.call_args.args[:2], (2, 7))

    def test_validation_precedes_database_connection(self):
        self.assertEqual(self.request('/delete-machine-templates', json={}).status_code, 400)
        self.connect.assert_not_called()

    def test_operation_failure_closes_connection_and_hides_internal_errors(self):
        with self.assertLogs(self.app.logger, level='ERROR'):
            result = self.request('/delete-machine-templates', json={'challenge_id': 2})
        self.assertEqual(result.status_code, 500)
        self.assertNotIn(b'private', result.data)
        self.db.close.assert_called_once()

    def test_health_distinguishes_liveness_and_readiness(self):
        self.assertEqual(self.request('/health/live', method='GET').status_code, 200)
        self.connect.assert_not_called()
        self.assertEqual(self.request('/health/ready', method='GET').status_code, 200)
        self.db.close.assert_called_once()
        self.connect.side_effect = RuntimeError('unavailable')
        with self.assertLogs(self.app.logger, level='ERROR'):
            self.assertEqual(self.request('/health/ready', method='GET').status_code, 503)

    def test_body_limit_and_delete_validation(self):
        self.assertEqual(self.request(data='x' * 65537, content_type='application/json').status_code, 413)
        self.assertEqual(self.request('/delete-user-config', json={'user_id': -1}).status_code, 400)
        self.delete.assert_not_called()
        self.assertEqual(self.request('/delete-user-config', json={'user_id': '3'}).status_code, 200)
        self.delete.assert_called_once_with(3)

    def test_maintenance_blocks_mutations_but_allows_authenticated_health(self):
        self.marker.touch()
        self.assertEqual(self.request(json={'user_id': 1, 'challenge_template_id': 2}).status_code, 503)
        self.launch.assert_not_called()
        self.assertEqual(self.request('/health/live', method='GET').status_code, 200)
