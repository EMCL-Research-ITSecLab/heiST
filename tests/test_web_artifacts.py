"""Upload intake permissions use real sessions and the restricted PostgreSQL role."""
import os
from pathlib import Path
import tempfile
import unittest

from tests import test_web_auth as authentication


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class ArtifactUploadTests(unittest.TestCase):
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
        self.root = Path(temporary.name)
        self.app.config['DATA_ROOT'] = temporary.name
        self.update_user('is_admin=TRUE')

    def create(self):
        self.login()
        value = self.request('admin/artifact-uploads', 'POST', json={'name': 'test.ova', 'size': 4, 'guest_os': 'linux'})
        self.assertEqual(value.status_code, 201, value.json)
        return 'admin/artifact-uploads/'+value.json['data']['id']

    def test_transfer_and_seal_do_not_publish_unvalidated_disk(self):
        path = self.create()
        self.assertEqual(self.request(path+'/seal', 'POST').status_code, 400)
        result = self.request(path+'/chunks/0', 'PUT', data=b'disk', content_type='application/octet-stream')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.request(path+'/chunks/0', 'PUT', data=b'disk', content_type='application/octet-stream').status_code, 200)
        result = self.request(path+'/seal', 'POST')
        self.assertEqual(result.status_code, 202, result.json)
        self.assertEqual(result.json['data']['state'], 'SEALED')
        self.assertIn('not complete', result.json['message'])
        self.assertEqual(self.repo.call('get_user_available_disk_files', self.user_id), [])
        self.assertEqual(self.request(path+'/seal', 'POST').status_code, 202)
        self.assertEqual(self.request(path, 'DELETE').status_code, 400)

    def test_role_revocation_and_cross_account_ownership_block_all_staging_operations(self):
        path = self.create()
        self.update_user('is_admin=FALSE')
        self.assertEqual(self.request(path).status_code, 403)
        self.assertEqual(self.request(path, 'DELETE').status_code, 403)
        self.assertEqual(self.request(path+'/chunks/0', 'PUT', data=b'disk', content_type='application/octet-stream').status_code, 403)
        self.assertEqual(self.request(path+'/seal', 'POST').status_code, 403)
        self.update_user('is_admin=TRUE')
        # Move the private directory to a distinct owner namespace. Knowing an
        # upload identifier must not reveal or mutate another user's upload.
        directory = self.root/'artifact-uploads'/str(self.user_id)
        directory.rename(directory.with_name(str(self.user_id+1)))
        self.assertEqual(self.request(path).status_code, 400)
        self.assertEqual(self.request(path+'/seal', 'POST').status_code, 400)

    def test_invalid_chunk_content_and_size_cancel_and_unauthenticated_access(self):
        self.assertEqual(self.request('admin/artifact-uploads/abcd').status_code, 401)
        path = self.create()
        self.assertEqual(self.request(path+'/chunks/0', 'PUT', data='disk', content_type='text/plain').status_code, 415)
        self.assertEqual(self.request(path+'/chunks/0', 'PUT', data=b'bad', content_type='application/octet-stream').status_code, 400)
        self.assertEqual(self.request(path+'/chunks/1', 'PUT', data=b'disk', content_type='application/octet-stream').status_code, 400)
        self.assertEqual(self.request(path, 'DELETE').json['data']['state'], 'CANCELLED')
        self.assertEqual(self.request(path+'/chunks/0', 'PUT', data=b'disk', content_type='application/octet-stream').status_code, 400)
