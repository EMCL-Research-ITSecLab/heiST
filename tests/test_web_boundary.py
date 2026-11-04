import unittest
from unittest.mock import Mock
from heist.api.public import create_app


class PublicBoundaryTests(unittest.TestCase):
    def test_deeply_nested_json_is_a_bad_request_without_touching_storage(self):
        from heist.api.public.context import body
        from heist.api.public.errors import ApiError
        factory = Mock()
        app = create_app({'WEB_SESSION_SECRET': 'a'*64}, repository_factory=factory)
        with app.test_request_context('/api/login', method='POST', data='['*1100+'0'+']'*1100, content_type='application/json'):
            with self.assertRaises(ApiError) as caught:
                body()
            self.assertEqual(caught.exception.status, 400)
        factory.assert_not_called()

    def test_invalid_secret_configuration_is_rejected_before_resources_are_created(self):
        factory = Mock()
        for secret in (None, 'short', 'z'*64):
            with self.assertRaises(ValueError):
                create_app({'WEB_SESSION_SECRET': secret}, repository_factory=factory)
        factory.assert_not_called()

    def test_http_unknown_routes_and_anonymous_protected_reads_do_not_access_database(self):
        factory = Mock()
        app = create_app({'WEB_SESSION_SECRET': 'a'*64, 'TESTING': True}, repository_factory=factory)
        client = app.test_client()
        self.assertEqual(client.get('/api/session', base_url='http://localhost').status_code, 400)
        self.assertEqual(client.get('/api/does-not-exist', base_url='https://localhost').status_code, 404)
        self.assertEqual(client.get('/api/dashboard', base_url='https://localhost').status_code, 401)
        factory.assert_not_called()

    def test_unavailable_dependency_has_generic_json_and_security_headers(self):
        app = create_app({'WEB_SESSION_SECRET': 'a'*64, 'TESTING': True}, repository_factory=Mock(side_effect=RuntimeError('private DB credentials')))
        with self.assertLogs(app.logger, level='ERROR'):
            response = app.test_client().get('/api/session', base_url='https://localhost')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.get_data(as_text=True))
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_maintenance_closes_browser_routes_but_liveness_stays_available(self):
        from pathlib import Path
        import tempfile
        factory=Mock()
        with tempfile.TemporaryDirectory() as temporary:
            marker=Path(temporary)/'maintenance';marker.touch()
            app=create_app({'WEB_SESSION_SECRET':'a'*64,'MAINTENANCE_FILE':str(marker)},repository_factory=factory)
            client=app.test_client()
            self.assertEqual(client.get('/api/session',base_url='https://localhost').status_code,503)
            self.assertEqual(client.post('/api/login',base_url='https://localhost',json={}).status_code,503)
            self.assertEqual(client.get('/api/health/ready',base_url='https://localhost',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,503)
            self.assertEqual(client.get('/api/health/live',base_url='https://localhost').status_code,200)
            factory.assert_not_called()
