"""Owner-scoped authoring contracts against real stored functions and role grants."""
from contextlib import closing
import os
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

from tests import test_web_auth as authentication
from tests.test_challenge_definition import exercise
from tests.test_web_media import png
from heist.api.public.errors import ApiError


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class AuthoringTests(unittest.TestCase):
    setUpClass = classmethod(authentication.PublicAuthenticationTests.setUpClass.__func__)
    tearDownClass = classmethod(authentication.PublicAuthenticationTests.tearDownClass.__func__)
    remove_database = classmethod(authentication.PublicAuthenticationTests.remove_database.__func__)
    request = authentication.PublicAuthenticationTests.request
    bootstrap = authentication.PublicAuthenticationTests.bootstrap
    login = authentication.PublicAuthenticationTests.login
    update_user = authentication.PublicAuthenticationTests.update_user

    def setUp(self):
        authentication.PublicAuthenticationTests.setUp(self)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app.config['DATA_ROOT'] = temporary.name
        self.update_user('is_admin=TRUE')
        self.platform = Mock()
        self.platform.request.side_effect = self.operation
        self.app.extensions['internal_client_factory'] = lambda: self.platform
        self.sql("INSERT INTO disk_files(user_id,display_name,proxmox_filename) VALUES (%s,'Debian','owned.ova')", (self.user_id,))
        self.value = exercise()
        self.value['name'] = self.username+' exercise'

    def sql(self, statement, arguments=()):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(statement, arguments)
                return cursor.fetchall() if cursor.description else None

    def operation(self, name, payload):
        if name == 'import_templates':
            self.sql('UPDATE challenge_templates SET ready_to_launch=TRUE WHERE id=%s', (payload['challenge_template_id'],))
        return {'success': True}

    def create(self):
        self.login()
        result = self.request('admin/challenges', 'POST', json=self.value)
        self.assertEqual(result.status_code, 201, result.json)
        return result.json['id']

    def test_options_create_and_management_roundtrip_with_real_topology(self):
        self.assertEqual(self.request('admin/challenges/options').status_code, 401)
        identifier = self.create()
        self.assertEqual(self.request('admin/challenges/options').json['ovas'][0]['filename'], 'Debian')
        self.platform.request.assert_called_once_with('import_templates', {'challenge_template_id': identifier})
        result = self.request('admin/challenges')
        self.assertEqual(result.status_code, 200, result.json)
        saved = next(item for item in result.json['data']['challenges'] if item['id'] == identifier)
        self.assertEqual(saved['description'], self.value['description'])
        self.assertTrue(saved['is_active'])
        self.assertEqual(self.repo.call('web_template_state', identifier, one=True), {'ready': True, 'instances': 0})
        machine = self.sql('SELECT name,cores,ram_gb FROM machine_templates WHERE challenge_template_id=%s', (identifier,))[0]
        self.assertEqual(machine, ('target', 1, 1))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM network_connection_templates c JOIN machine_templates m ON m.id=c.machine_template_id WHERE m.challenge_template_id=%s', (identifier,))[0][0], 1)
        self.assertEqual(self.request('admin/challenges', 'POST', json=self.value).status_code, 409)

    def test_invalid_or_foreign_image_definition_creates_no_rows_or_platform_operations(self):
        self.login()
        self.value['vms'][0]['ova_name'] = 'Foreign image'
        result = self.request('admin/challenges', 'POST', json=self.value)
        self.assertEqual(result.status_code, 400)
        self.platform.request.assert_not_called()
        self.assertEqual(self.repo.scalar('count_user_challenges_with_same_name', self.value['name'], self.user_id), 0)
        self.update_user('is_admin=FALSE')
        self.assertEqual(self.request('admin/challenges', 'POST', json=self.value).status_code, 403)
        self.assertEqual(self.request('admin/challenges/options').status_code, 403)

    def test_ambiguous_import_keeps_inactive_definition_and_prevents_blind_duplicate_retry(self):
        self.login()
        self.platform.request.side_effect = ApiError('Transport outcome unknown', 503)
        result = self.request('admin/challenges', 'POST', json=self.value)
        self.assertEqual(result.status_code, 503, result.json)
        self.assertIn('saved inactive', result.json['message'])
        saved = self.sql('SELECT id,is_active,ready_to_launch FROM challenge_templates WHERE creator_id=%s AND name=%s', (self.user_id, self.value['name']))[0]
        self.assertEqual(saved[1:], (False, False))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM machine_templates WHERE challenge_template_id=%s', (saved[0],))[0][0], 1)
        self.assertEqual(self.request('admin/challenges', 'POST', json=self.value).status_code, 409)
        self.assertEqual(self.platform.request.call_count, 1)
        self.assertEqual(self.request('admin/challenges/'+str(saved[0]), 'PUT', json=self.value).status_code, 409)

    def test_edit_retire_restore_and_delete_are_owner_scoped_and_methods_are_explicit(self):
        identifier = self.create()
        path = 'admin/challenges/'+str(identifier)
        result = self.request(path, 'PUT', json={**self.value, 'description': 'Updated content'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.repo.call('get_challenge_template_details', identifier, one=True)['description'], 'Updated content')
        self.assertEqual(self.request(path+'/leaderboard').status_code, 200)
        self.assertEqual(self.request(path, 'DELETE', json={'force': False}).status_code, 200)
        self.assertTrue(self.repo.scalar('challenge_template_is_marked_for_deletion', identifier))
        self.assertEqual(self.request(path, 'PUT', json=self.value).status_code, 409)
        self.assertEqual(self.request(path+'/restore', 'POST', json={}).status_code, 200)
        self.assertFalse(self.repo.scalar('challenge_template_is_marked_for_deletion', identifier))
        self.sql('UPDATE challenge_templates SET creator_id=NULL WHERE id=%s', (identifier,))
        self.platform.reset_mock()
        for method in ('PUT', 'DELETE'):
            self.assertEqual(self.request(path, method, json=self.value).status_code, 404)
        self.assertEqual(self.request(path+'/restore', 'POST', json={}).status_code, 404)
        self.assertEqual(self.request(path+'/leaderboard').status_code, 404)
        self.platform.request.assert_not_called()
        self.sql('UPDATE challenge_templates SET creator_id=%s WHERE id=%s', (self.user_id, identifier))
        result = self.request(path, 'DELETE', json={'force': True})
        self.assertEqual(result.status_code, 200, result.json)
        self.platform.request.assert_called_once_with('delete_templates', {'challenge_id': identifier})
        self.assertIsNone(self.repo.call('get_challenge_template_details', identifier, one=True))

    def test_failed_permanent_delete_keeps_definition_retired_and_grades_available(self):
        identifier = self.create()
        self.platform.request.side_effect = ApiError('Platform operation failed', 503)
        result = self.request('admin/challenges/'+str(identifier), 'DELETE', json={'force': True})
        self.assertEqual(result.status_code, 503)
        saved = self.repo.call('get_challenge_template_details', identifier, one=True)
        self.assertTrue(saved['marked_for_deletion'])
        self.assertFalse(saved['is_active'])
        self.assertTrue(self.repo.call('get_challenge_flags', identifier))

    def test_pool_selection_excludes_inactive_retired_and_unready_exercises(self):
        from heist.platform.pools.manager import pool_template_ids
        from heist.platform.challenges.availability import require_available_template
        identifier = self.create()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            self.assertIn(identifier, pool_template_ids(connection))
            require_available_template(connection, identifier)
        for assignments in ('is_active=FALSE', 'is_active=TRUE,marked_for_deletion=TRUE', 'marked_for_deletion=FALSE,ready_to_launch=FALSE'):
            self.sql('UPDATE challenge_templates SET '+assignments+' WHERE id=%s', (identifier,))
            with closing(self.psycopg2.connect(**self.settings)) as connection:
                self.assertNotIn(identifier, pool_template_ids(connection))
                with self.assertRaises(ValueError):
                    require_available_template(connection, identifier)

    def test_multipart_cover_upload_uses_private_generated_image_and_rejects_invalid_images(self):
        self.login()
        value = dict(self.value)
        for key in ('vms', 'subnets', 'flags', 'hints'):
            value[key] = json.dumps(value[key])
        response = self.request('admin/challenges', 'POST', data={**value, 'image': (io.BytesIO(b'<svg/>'), 'cover.png')})
        self.assertEqual(response.status_code, 400)
        self.platform.request.assert_not_called()
        response = self.request('admin/challenges', 'POST', data={**value, 'image': (io.BytesIO(png()), '../../cover.php')})
        self.assertEqual(response.status_code, 201, response.json)
        saved = self.repo.call('get_challenge_template_details', response.json['id'], one=True)
        self.assertTrue(saved['image_path'].startswith('/api/media/challenge_images/'))
        path = Path(self.app.config['DATA_ROOT'])/'media/challenge_images'/saved['image_path'].rsplit('/', 1)[-1]
        self.assertEqual(path.read_bytes(), png())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
