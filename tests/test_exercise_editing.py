"""Real browser/internal API and SQL checks for configuration editing."""
from copy import deepcopy
import os
import tempfile
import unittest
from unittest.mock import patch

from heist.api.internal import create_app
from heist.api.public.errors import ApiError
from tests.test_web_authoring import AuthoringTests


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL required')
class ExerciseEditingTests(unittest.TestCase):
    setUpClass = classmethod(AuthoringTests.setUpClass.__func__)
    tearDownClass = classmethod(AuthoringTests.tearDownClass.__func__)
    remove_database = classmethod(AuthoringTests.remove_database.__func__)
    request, bootstrap, login, update_user = AuthoringTests.request, AuthoringTests.bootstrap, AuthoringTests.login, AuthoringTests.update_user
    sql, create = AuthoringTests.sql, AuthoringTests.create

    def operation(self,name,payload):
        if name == 'import_templates':
            self.sql('UPDATE challenge_templates SET ready_to_launch=TRUE WHERE id=%s',(payload['challenge_template_id'],))
            return {'success':True}
        endpoints={'admin_configuration':('GET','/admin/challenges/configuration'),
                   'admin_configuration_change':('POST','/admin/challenges/configuration'),
                   'admin_pool_details':('GET','/admin/pools/details'), 'admin_pool_change':('POST','/admin/pools/manage')}
        method,path=endpoints[name]
        response=self.internal.open(path,method=method,json=payload,base_url='https://backend.test',headers={'Authentication-Token':'test-token'})
        if response.status_code>=400:raise ApiError(response.json.get('message','Invalid request'),response.status_code)
        return response.json

    def setUp(self):
        AuthoringTests.setUp(self)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,{'HEIST_TEMPLATE_LOCK_DIRECTORY':temporary.name+'/locks'}).start()
        self.internal=create_app({'BACKEND_AUTHENTICATION_TOKEN':'test-token','OPERATION_DIRECTORY':temporary.name+'/jobs',
            'MAINTENANCE_FILE':temporary.name+'/maintenance'},services={'get_db_connection':lambda:self.psycopg2.connect(**self.settings)}).test_client()
        self.identifier=self.create()
        self.sql('UPDATE challenge_templates SET is_active=FALSE WHERE id=%s',(self.identifier,))

    def loaded(self):
        response=self.request(f'admin/challenges/{self.identifier}/configuration')
        self.assertEqual(response.status_code,200,response.json)
        return response.json['data']

    def save(self,value):
        return self.request(f'admin/challenges/{self.identifier}/configuration','PUT',json={'definition':value['definition'],'expected':value['fingerprint']})

    def test_networks_resources_and_domains_change_without_changing_machine_or_flag_identity(self):
        before=self.loaded();changed=deepcopy(before)
        changed['definition']['vms'][0].update(cores=3,ram_gb=4,domain_name='edited.lab.test')
        changed['definition']['subnets'].append({'name':'second','accessible':False,'dmz':False,'attached_vms':['target']})
        response=self.save(changed);self.assertEqual(response.status_code,200,response.json)
        after=self.loaded()
        self.assertNotEqual(after['fingerprint'],before['fingerprint'])
        self.assertEqual(after['definition']['vms'][0]['id'],before['definition']['vms'][0]['id'])
        self.assertEqual(after['definition']['flags'][0]['id'],before['definition']['flags'][0]['id'])
        self.assertEqual(after['definition']['vms'][0]['cores'],3)
        self.assertEqual(after['definition']['vms'][0]['ram_gb'],4)
        self.assertEqual(len(after['definition']['subnets']),2)
        self.assertGreaterEqual(self.sql('SELECT count(*) FROM exercise_revisions WHERE challenge_template_id=%s',(self.identifier,))[0][0],3)
        self.assertEqual(self.save(changed).status_code,409)

    def test_active_or_instantiated_configuration_is_never_changed(self):
        for active,instance in ((True,False),(False,True)):
            with self.subTest(active=active,instance=instance):
                self.sql('UPDATE challenge_templates SET is_active=%s WHERE id=%s',(active,self.identifier))
                if instance:self.sql("INSERT INTO challenges(challenge_template_id,lifecycle_state) VALUES(%s,'READY')",(self.identifier,))
                value=self.loaded();before=deepcopy(value);value['definition']['description']='Must not save'
                self.assertEqual(self.save(value).status_code,409)
                self.assertEqual(self.loaded()['fingerprint'],before['fingerprint'])
                self.sql('DELETE FROM challenges WHERE challenge_template_id=%s',(self.identifier,))

    def test_earned_flags_keep_verifier_points_identity_and_completion(self):
        before=self.loaded();flag=before['definition']['flags'][0]
        self.sql('INSERT INTO completed_challenges(user_id,challenge_template_id,flag_id,completed_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP)',(self.user_id,self.identifier,flag['id']))
        completion=self.sql('SELECT id,flag_id,completed_at FROM completed_challenges WHERE challenge_template_id=%s',(self.identifier,))
        for field,value in (('flag','replacement'),('points',3),('id',2**62)):
            candidate=deepcopy(before);candidate['definition']['flags'][0][field]=value
            self.assertIn(self.save(candidate).status_code,(400,409))
        valid=deepcopy(before);valid['definition']['subnets'][0]['dmz']=True
        self.assertEqual(self.save(valid).status_code,200)
        self.assertEqual(self.sql('SELECT id,flag_id,completed_at FROM completed_challenges WHERE challenge_template_id=%s',(self.identifier,)),completion)

    def test_foreign_machine_invalid_topology_and_unauthorized_actor_are_rejected(self):
        before=self.loaded()
        for change in ('foreign-machine','disconnected','image-replacement'):
            candidate=deepcopy(before)
            if change=='foreign-machine':candidate['definition']['vms'][0]['id']=2**62
            elif change=='disconnected':candidate['definition']['subnets'][0]['attached_vms']=[]
            else:candidate['definition']['vms'][0]['ova_name']='Foreign image'
            self.assertEqual(self.save(candidate).status_code,400)
            self.assertEqual(self.loaded()['fingerprint'],before['fingerprint'])
        self.sql('UPDATE challenge_templates SET creator_id=NULL WHERE id=%s',(self.identifier,))
        self.assertEqual(self.request(f'admin/challenges/{self.identifier}/configuration').status_code,404)

    def test_manual_pool_policy_can_be_staged_before_publication(self):
        response=self.request(f'admin/pools/{self.identifier}')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['data']['pool_size'],6)
        response=self.request(f'admin/pools/{self.identifier}','POST',json={'size':6,'enabled':True,'expected_revision':0})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['data']['application'],'waiting_for_publication')
        self.assertEqual(self.sql('SELECT count(*) FROM challenges WHERE challenge_template_id=%s',(self.identifier,)),[(0,)])
