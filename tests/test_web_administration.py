"""Administrator routes tested with actual role changes and persistent writes."""
import os
import unittest
from unittest.mock import Mock
from tests import test_web_auth as authentication


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class AdministrationTests(unittest.TestCase):
    def test_management_reads_and_actions_validate_scope_preview_and_current_role(self):
        paths=('admin/overview','admin/audit','admin/jobs/user/123','admin/instances/3/preview?action=reboot&machine_id=4')
        for path in paths:self.assertEqual(self.request(path).status_code,401)
        self.login()
        for path in paths:self.assertEqual(self.request(path).status_code,403)
        self.platform.request.assert_not_called();self.update_user('is_admin=TRUE')
        self.platform.request.return_value={'success':True,'data':{}}
        self.assertEqual(self.request(paths[-1]).status_code,200)
        self.assertEqual(self.platform.request.call_args.args,('admin_preview',{'actor_id':self.user_id,'instance_id':3,'machine_id':4,'action':'reboot'}))
        self.assertEqual(self.request('admin/instances/3/machines/4','POST',json={'action':'shutdown','expected':'a'*64,'actor_id':999}).status_code,200)
        self.assertEqual(self.platform.request.call_args.args,('admin_vm_change',{'actor_id':self.user_id,'instance_id':3,'machine_id':4,'action':'shutdown','expected':'a'*64}))
        self.platform.reset_mock()
        self.assertEqual(self.request('admin/instances/3','POST',json={'action':'rebuild'}).status_code,400)
        self.assertEqual(self.request('admin/instances/3/machines/4','POST',json={'action':'shell','expected':'a'*64}).status_code,400)
        self.assertEqual(self.request('admin/jobs/host/123').status_code,400)
        self.assertEqual(self.request('admin/pools/1','POST',json={'enabled':True,'size':11,'expected_revision':0}).status_code,400)
        self.platform.request.assert_not_called()
    setUpClass = classmethod(authentication.PublicAuthenticationTests.setUpClass.__func__)
    tearDownClass = classmethod(authentication.PublicAuthenticationTests.tearDownClass.__func__)
    remove_database = classmethod(authentication.PublicAuthenticationTests.remove_database.__func__)
    request = authentication.PublicAuthenticationTests.request
    bootstrap = authentication.PublicAuthenticationTests.bootstrap
    login = authentication.PublicAuthenticationTests.login
    update_user = authentication.PublicAuthenticationTests.update_user

    def setUp(self):
        authentication.PublicAuthenticationTests.setUp(self)
        self.platform = Mock()
        self.app.extensions['internal_client_factory'] = lambda: self.platform

    def test_private_activity_requires_current_admin_and_ignores_forged_actor(self):
        path='admin/monitoring/activity'
        self.assertEqual(self.request(path).status_code,401)
        self.login()
        self.assertEqual(self.request(path).status_code,403)
        self.platform.request.assert_not_called()
        self.update_user('is_admin=TRUE')
        self.platform.request.return_value={'success':True,'data':{'status':'ready','events':[]}}
        response=self.request(path+'?instance_id=123&actor_id=999')
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.platform.request.call_args.args,('admin_activity',{'actor_id':self.user_id,'instance_id':123}))
        self.assertEqual(self.request(path+'?instance_id=0').status_code,400)
        self.update_user('is_admin=FALSE');self.platform.reset_mock()
        self.assertEqual(self.request(path).status_code,403)
        self.platform.request.assert_not_called()

    def test_administration_reloads_role_before_platform_access(self):
        self.assertEqual(self.request('admin/operations').status_code, 401)
        self.login()
        self.assertEqual(self.request('admin/operations').status_code, 403)
        self.platform.request.assert_not_called()
        self.update_user('is_admin=TRUE')
        monitoring = {'status': 'failed', 'checks': []}
        self.platform.request.return_value = {'success': True, 'data': {'database': 'ready', 'services': {}, 'monitoring': monitoring, 'raw_configuration': 'private-token'}}
        result = self.request('admin/operations')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['data'], {'database': 'ready', 'services': {}, 'monitoring': monitoring})
        self.assertNotIn('private-token', str(result.json))
        self.update_user('is_admin=FALSE')
        self.platform.reset_mock()
        self.assertEqual(self.request('admin/operations').status_code, 403)
        self.platform.request.assert_not_called()

    def test_announcement_crud_is_admin_only_and_preserves_author(self):
        self.login()
        value = {'title': 'Maintenance', 'content': 'Scheduled upgrade', 'short_description': 'Tomorrow', 'category': 'maintenance', 'importance': 'important', 'author': 'forged'}
        self.assertEqual(self.request('admin/announcements', 'POST', json=value).status_code, 403)
        self.update_user('is_admin=TRUE')
        result = self.request('admin/announcements', 'POST', json=value)
        self.assertEqual(result.status_code, 200, result.json)
        identifier = result.json['id']
        result = self.request('admin/announcements').json['data']
        saved = next(item for item in result['announcements'] if item['id'] == identifier)
        self.assertEqual(saved['author'], self.username)
        result = self.request('admin/announcements/'+str(identifier), 'PUT', json={**value, 'content': 'Updated schedule'})
        self.assertEqual(result.status_code, 200, result.json)
        result = self.request('announcements').json['data']['announcements']
        self.assertEqual(next(item for item in result if item['id'] == identifier)['content'], 'Updated schedule')
        self.assertEqual(self.request('admin/announcements/'+str(identifier), 'DELETE', json={}).status_code, 200)
        self.assertFalse(self.repo.scalar('announcement_exists', identifier))
        self.assertEqual(self.request('admin/announcements/'+str(identifier), 'DELETE', json={}).status_code, 404)
        self.assertEqual(self.request('admin/announcements/'+str(identifier), 'GET').status_code, 405)

    def test_announcement_validation_rejects_oversize_empty_unknown_enums_and_invalid_ids(self):
        self.login()
        self.update_user('is_admin=TRUE')
        valid = {'title': 'Hello', 'content': 'World', 'importance': 'normal', 'category': 'general'}
        for invalid in ({'title': ' '}, {'content': 'x'*5001}, {'importance': 'unexpected'}, {'category': 'unknown'}):
            self.assertEqual(self.request('admin/announcements', 'POST', json={**valid, **invalid}).status_code, 400)
        self.assertEqual(self.request('admin/announcements/0', 'DELETE', json={}).status_code, 400)
        self.assertEqual(self.request('admin/announcements?page=0').status_code, 400)
        self.platform.request.assert_not_called()

    def test_author_username_change_preserves_announcements(self):
        self.login()
        self.update_user('is_admin=TRUE')
        result = self.request('admin/announcements', 'POST', json={'title': 'Notice', 'content': 'Hello', 'importance': 'normal', 'category': 'general'})
        self.assertEqual(result.status_code, 200)
        identifier = result.json['id']
        updated = 'edit_'+self.username[4:]
        result = self.request('profile', 'POST', json={'action': 'update_username', 'username': updated})
        self.assertEqual(result.status_code, 200, result.json)
        rows = self.request('admin/announcements').json['data']['announcements']
        self.assertEqual(next(item for item in rows if item['id'] == identifier)['author'], updated)

    def test_user_and_instance_management_require_admin_and_ignore_forged_actor(self):
        self.assertEqual(self.request('admin/users').status_code,401)
        self.login()
        for path in ('admin/users','admin/jobs','admin/instances','admin/instances/1'):
            self.assertEqual(self.request(path).status_code,403)
        self.platform.request.assert_not_called()
        self.update_user('is_admin=TRUE')
        self.platform.request.return_value={'success':True,'data':{'users':[]}}
        self.assertEqual(self.request('admin/users?search=student').status_code,200)
        self.assertEqual(self.platform.request.call_args.args[1],{'actor_id':self.user_id,'page':1,'search':'student'})
        response=self.request('admin/users/2','POST',json={'actor_id':999,'action':'role','administrator':True,'confirmation':'student'})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.platform.request.call_args.args,('admin_user_change',{'actor_id':self.user_id,'user_id':2,'action':'role','confirmation':'student','administrator':True}))
        self.assertEqual(self.request('admin/instances/3','POST',json={'action':'rebuild','actor_id':999,'expected':'a'*64}).status_code,200)
        self.assertEqual(self.platform.request.call_args.args,('admin_instance_change',{'actor_id':self.user_id,'instance_id':3,'action':'rebuild','expected':'a'*64}))
        self.assertEqual(self.request('admin/jobs?state=NEEDS_REVIEW').status_code,200)
        self.assertEqual(self.platform.request.call_args.args,('admin_jobs',{'actor_id':self.user_id,'page':1,'state':'NEEDS_REVIEW'}))
        self.platform.reset_mock()
        self.assertEqual(self.request('admin/users/2','POST',json={'action':'role','administrator':'true','confirmation':'student'}).status_code,400)
        self.assertEqual(self.request('admin/instances/3','POST',json={'action':'shell'}).status_code,400)
        self.platform.request.assert_not_called()
