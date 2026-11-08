"""Administrator SQL, authority, journal and recovery contracts on a disposable DB."""
import os
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from heist.platform.administration import Administration, AdminError
from heist.platform.jobs.journal import Journal, RecoveryRequired
from heist.security.passwords import verify_password
from tests import test_web_database as database
from tests import test_teardown_database as teardown_fixture


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Disposable PostgreSQL administrator connection required')
class PlatformAdministrationTests(unittest.TestCase):
    setUpClass=classmethod(database.WebDatabaseTests.setUpClass.__func__)
    tearDownClass=classmethod(database.WebDatabaseTests.tearDownClass.__func__)
    remove_database=classmethod(database.WebDatabaseTests.remove_database.__func__)
    sql=teardown_fixture.TeardownDatabaseTests.sql

    def setUp(self):
        teardown_fixture.TeardownDatabaseTests.setUp(self)
        self.sql('UPDATE users SET running_challenge=%s WHERE id=%s',(self.instance,self.user_id))
        self.grade=self.sql('INSERT INTO completed_challenges(user_id,challenge_template_id,completed_at) VALUES (%s,%s,CURRENT_TIMESTAMP) RETURNING id',(self.user_id,self.template))[0][0]
        self.admin=self.sql("SELECT id FROM api.create_user(%s,%s,%s,%s,'127.0.0.1')",('adm_'+self.username,'adm_'+self.username+'@example.invalid',self.old_hash,self.legacy_salt))[0][0]
        self.sql('UPDATE users SET is_admin=TRUE WHERE id=%s',(self.admin,))
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.journal=Journal(self.temporary.name)
        self.stop=Mock(side_effect=self.release)
        self.teardown=Mock(side_effect=lambda identifier,**kwargs:self.sql('DELETE FROM challenges WHERE id=%s',(identifier,)))
        self.launch=Mock(return_value=[])
        self.service=Administration(lambda:self.psycopg2.connect(**self.settings),self.journal,stop=self.stop,teardown=self.teardown,launch=self.launch,status=Mock(return_value='running'))

    def release(self,user,*,expected_challenge_id):
        changed=self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s AND running_challenge=%s RETURNING id',(user,expected_challenge_id))
        if changed:self.sql("UPDATE challenges SET lifecycle_state='EXPIRED',pre_assigned_user_id=NULL WHERE id=%s",(expected_challenge_id,))
        return bool(changed)

    def test_users_are_admin_only_search_is_literal_and_secrets_are_excluded(self):
        with self.assertRaises(AdminError) as rejected:self.service.users(self.user_id)
        self.assertEqual(rejected.exception.status,403)
        items=self.service.users(self.admin,self.username)['users']
        self.assertTrue(any(user['id']==self.user_id for user in items))
        self.assertNotIn('password_hash',str(items));self.assertNotIn(self.old_hash,str(items))
        self.assertEqual(self.service.users(self.admin,'%')['users'],[])
        self.sql('UPDATE users SET is_admin=FALSE WHERE id=%s',(self.admin,))
        with self.assertRaises(AdminError):self.service.instances(self.admin)

    def test_role_changes_revoke_sessions_are_idempotent_and_cannot_change_self(self):
        result=self.service.change_user(self.admin,self.user_id,'role',self.username,administrator=True,request_id='a'*32)
        self.assertTrue(result['sessions_revoked'])
        self.assertEqual(self.sql('SELECT is_admin FROM users WHERE id=%s',(self.user_id,)),[(True,)])
        self.service.change_user(self.admin,self.user_id,'role',self.username,administrator=True,request_id='a'*32)
        self.assertEqual(self.sql('SELECT auth_version FROM web_auth_state WHERE user_id=%s',(self.user_id,)),[(1,)])
        name=self.sql('SELECT username FROM users WHERE id=%s',(self.admin,))[0][0]
        with self.assertRaises(AdminError):self.service.change_user(self.admin,self.admin,'role',name,administrator=False)
        self.assertEqual(self.sql('SELECT is_admin FROM users WHERE id=%s',(self.admin,)),[(True,)])

    def test_completed_operation_replay_still_requires_current_actor_authority(self):
        self.service.change_user(self.admin,self.user_id,'revoke_sessions',self.username,request_id='b'*32)
        self.sql('UPDATE users SET is_admin=FALSE WHERE id=%s',(self.admin,))
        with self.assertRaises(AdminError) as error:
            self.service.change_user(self.admin,self.user_id,'revoke_sessions',self.username,request_id='b'*32)
        self.assertEqual(error.exception.status,403)

    def test_password_reset_sets_required_change_and_never_journals_secrets(self):
        secret='temporary-password-for-fixture'
        self.service.change_user(self.admin,self.user_id,'password',self.username,password=secret)
        stored,salt,reset,valid=self.sql("SELECT password_hash,password_salt,password_reset,password_reset_timestamp>CURRENT_TIMESTAMP-INTERVAL '1 minute' FROM users WHERE id=%s",(self.user_id,))[0]
        self.assertTrue(verify_password(stored,secret,salt));self.assertTrue(reset);self.assertTrue(valid)
        for path in Path(self.temporary.name).rglob('*.json'):
            self.assertNotIn(secret,path.read_text());self.assertNotIn(stored,path.read_text())
        self.assertEqual(self.sql('SELECT count(*) FROM web_sessions WHERE user_id=%s',(self.user_id,)),[(0,)])

    def test_wrong_confirmation_and_invalid_action_have_no_account_effects(self):
        for args in [('role','wrong'),('shell',self.username)]:
            with self.assertRaises(AdminError):self.service.change_user(self.admin,self.user_id,*args,administrator=True)
        self.assertEqual(self.sql('SELECT is_admin,password_hash FROM users WHERE id=%s',(self.user_id,)),[(False,self.old_hash)])
        self.assertEqual(self.sql('SELECT count(*) FROM web_auth_state WHERE user_id=%s',(self.user_id,)),[(0,)])

    def test_inspection_and_release_use_exact_assignment_and_keep_grades(self):
        detail=self.service.instance(self.admin,self.instance)
        self.assertEqual(detail['user_id'],self.user_id)
        self.assertEqual(detail['state'],'ACTIVE')
        self.service.change_instance(self.admin,self.instance,'release')
        self.stop.assert_called_once_with(self.user_id,expected_challenge_id=self.instance)
        self.assertEqual(self.sql('SELECT running_challenge FROM users WHERE id=%s',(self.user_id,)),[(None,)])
        self.teardown.assert_not_called();self.launch.assert_not_called()

    def test_remove_refuses_assigned_reserved_and_provisioning_instances(self):
        with self.assertRaises(AdminError):self.service.change_instance(self.admin,self.instance,'remove')
        self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s',(self.user_id,))
        self.sql("UPDATE challenges SET lifecycle_state='READY' WHERE id=%s",(self.instance,))
        with self.assertRaises(AdminError):self.service.change_instance(self.admin,self.instance,'remove')
        self.sql("UPDATE challenges SET lifecycle_state='PROVISIONING',pre_assigned_user_id=NULL WHERE id=%s",(self.instance,))
        with self.assertRaises(AdminError):self.service.change_instance(self.admin,self.instance,'remove')
        self.teardown.assert_not_called()

    def test_remove_expired_instance_accepts_its_historical_student_reservation(self):
        # stop_challenge expires and unassigns, retaining the historical owner.
        self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s',(self.user_id,))
        self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s",(self.instance,))
        self.service.change_instance(self.admin,self.instance,'remove')
        self.teardown.assert_called_once_with(self.instance,expected_template_id=self.template)
        self.assertEqual(self.sql('SELECT count(*) FROM challenges WHERE id=%s',(self.instance,)),[(0,)])
        self.assertEqual(self.sql('SELECT count(*) FROM completed_challenges WHERE id=%s',(self.grade,)),[(1,)])
        self.launch.assert_not_called()

    def test_failed_remove_exposes_its_instance_journal_despite_historical_owner(self):
        self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s',(self.user_id,))
        self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s",(self.instance,))
        self.teardown.side_effect=RuntimeError('fixture host cleanup failure')
        with self.assertRaises(RuntimeError):self.service.change_instance(self.admin,self.instance,'remove')
        operation=self.service.instance(self.admin,self.instance)['operation']
        self.assertEqual(operation['scope'],'instance')
        self.assertEqual(operation['resource'],self.instance)
        self.assertEqual(operation['state'],'NEEDS_REVIEW')
        with self.assertRaises(RecoveryRequired):self.service.change_instance(self.admin,self.instance,'remove')
        self.assertEqual(self.teardown.call_count,1)

    def test_operation_registry_retains_orphans_without_exposing_receipt_results(self):
        import json
        self.service.change_user(self.admin,self.user_id,'revoke_sessions',self.username)
        current=Path(self.temporary.name)/('user-'+str(self.user_id))/'current.json'
        value=json.loads(current.read_text());value['result']={'password':'must-stay-private'}
        current.write_text(json.dumps(value))
        orphan=Path(self.temporary.name)/'instance-999'
        orphan.mkdir(mode=0o700)
        (orphan/'current.json').write_text(json.dumps({'scope':'instance','resource':999,'id':'c'*32,'action':'admin_remove','state':'NEEDS_REVIEW','started':'2026-11-08T12:00:00Z'}))
        result=self.service.jobs(self.admin)
        self.assertEqual(len(result['jobs']),2)
        self.assertNotIn('must-stay-private',str(result))
        self.assertEqual(self.service.jobs(self.admin,state='NEEDS_REVIEW')['jobs'][0]['resource'],999)
        with self.assertRaises(AdminError):self.service.jobs(self.user_id)
        current.write_text('{')
        unavailable=self.service.jobs(self.admin,state='UNAVAILABLE')['jobs']
        self.assertEqual(len(unavailable),1)
        self.assertEqual(unavailable[0]['resource'],self.user_id)

    def test_rebuild_stops_removes_then_launches_and_keeps_the_user(self):
        self.service.change_instance(self.admin,self.instance,'rebuild')
        self.teardown.assert_called_once_with(self.instance,expected_template_id=self.template)
        self.launch.assert_called_once_with(self.template,self.user_id)
        self.assertEqual(self.sql('SELECT user_id,challenge_template_id FROM completed_challenges WHERE id=%s',(self.grade,)),[(self.user_id,self.template)])
        self.assertEqual(self.sql('SELECT count(*) FROM users WHERE id=%s',(self.user_id,)),[(1,)])
        self.assertEqual(self.sql('SELECT count(*) FROM challenges WHERE id=%s',(self.instance,)),[(0,)])

    def test_failed_rebuild_blocks_replay_and_does_not_start_another_instance(self):
        self.teardown.side_effect=RuntimeError('fixture teardown interrupted')
        with self.assertRaises(RuntimeError):self.service.change_instance(self.admin,self.instance,'rebuild')
        self.launch.assert_not_called()
        self.assertEqual(self.journal.inspect('user',self.user_id)['state'],'NEEDS_REVIEW')
        with self.assertRaises(RecoveryRequired):self.service.change_user(self.admin,self.user_id,'revoke_sessions',self.username)

    def test_internal_api_rechecks_actor_and_validates_input_without_commands(self):
        from heist.api.internal import create_app
        app=create_app({'BACKEND_AUTHENTICATION_TOKEN':'fixture-token','OPERATION_DIRECTORY':self.temporary.name,'MAINTENANCE_FILE':self.temporary.name+'/absent','CLEANUP_FILE':self.temporary.name+'/not-ready'},services={'get_db_connection':lambda:self.psycopg2.connect(**self.settings),'stop_challenge':self.stop,'teardown_challenge':self.teardown,'launch_challenge':self.launch})
        client=app.test_client();headers={'Authentication-Token':'fixture-token'}
        self.assertEqual(client.get('/admin/users',base_url='https://localhost',json={'actor_id':self.admin}).status_code,401)
        self.assertEqual(client.get('/admin/users',base_url='https://localhost',headers=headers,json={'actor_id':self.user_id}).status_code,403)
        self.assertEqual(client.get('/admin/users',base_url='https://localhost',headers=headers,json={'actor_id':self.admin}).status_code,200)
        self.assertEqual(client.post('/admin/instances/manage',base_url='https://localhost',headers=headers,json={'actor_id':self.admin,'instance_id':self.instance,'action':'rebuild'}).status_code,503)
        self.stop.assert_not_called()
        self.assertEqual(client.post('/admin/users/manage',base_url='https://localhost',headers=headers,json={'actor_id':True,'user_id':self.user_id}).status_code,400)

    def test_concurrent_cross_demotion_cannot_use_revoked_administrator_authority(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self.sql('UPDATE users SET is_admin=TRUE WHERE id=%s',(self.user_id,))
        def initially_serializable():
            connection=self.psycopg2.connect(**self.settings)
            connection.set_session(isolation_level='SERIALIZABLE')
            return connection
        self.service.connect=initially_serializable
        barrier=threading.Barrier(2)
        def change(actor,target,name):
            barrier.wait(timeout=5)
            try:self.service.change_user(actor,target,'role',name,administrator=False);return 'changed'
            except AdminError as error:return error.status
        with ThreadPoolExecutor(max_workers=2) as workers:
            a=workers.submit(change,self.admin,self.user_id,self.username)
            b=workers.submit(change,self.user_id,self.admin,'adm_'+self.username)
            results=[a.result(timeout=10),b.result(timeout=10)]
        self.assertCountEqual(results,['changed',403])
        self.assertEqual(self.sql('SELECT count(*) FROM users WHERE id IN (%s,%s) AND is_admin',(self.admin,self.user_id)),[(1,)])

    def test_network_inspection_retains_prefixes_and_multihomed_connections(self):
        disk=self.sql("INSERT INTO disk_files(user_id,display_name,proxmox_filename) VALUES (%s,'fixture','fixture.ova') RETURNING id",(self.user_id,))[0][0]
        template=self.sql("INSERT INTO machine_templates(challenge_template_id,name,disk_file_id,cores,ram_gb) VALUES (%s,'gateway',%s,1,1) RETURNING id",(self.template,disk))[0][0]
        machine=self.sql('INSERT INTO machines(machine_template_id,challenge_id) VALUES (%s,%s) RETURNING id',(template,self.instance))[0][0]
        for name,accessible in [('entry',True),('internal',False)]:
            net_template=self.sql('INSERT INTO network_templates(challenge_template_id,name,accessible,is_dmz) VALUES (%s,%s,%s,%s) RETURNING id',(self.template,name,accessible,not accessible))[0][0]
            network=self.sql("INSERT INTO networks(network_template_id,challenge_id,subnet,host_device) VALUES (%s,%s,'10.128.1.0/28','ch-fixture') RETURNING id",(net_template,self.instance))[0][0]
            self.sql("INSERT INTO network_connections(machine_id,network_id,client_mac,client_ip) VALUES (%s,%s,'02:00:00:00:00:01','10.128.1.2')",(machine,network))
        detail=self.service.instance(self.admin,self.instance)
        self.assertEqual(len(detail['networks']),2)
        self.assertEqual({net['subnet'] for net in detail['networks']},{'10.128.1.0/28'})
        self.assertEqual(len(detail['connections']),2)
        self.assertEqual({link['machine_id'] for link in detail['connections']},{machine})
        self.assertEqual(detail['machines'][0]['status'],'running')


class VMStatusTests(unittest.TestCase):
    def test_vm_inspection_is_bounded_and_does_not_return_raw_host_output(self):
        from unittest.mock import patch
        with patch('heist.platform.administration.subprocess.run',return_value=Mock(returncode=0,stdout='status: running\n')) as run:
            self.assertEqual(Administration.vm_status(123),'running')
        self.assertEqual(run.call_args.args[0],['qm','status','123'])
        self.assertEqual(run.call_args.kwargs['timeout'],2)
        with patch('heist.platform.administration.subprocess.run',return_value=Mock(returncode=1,stdout='private diagnostic')):
            self.assertEqual(Administration.vm_status(123),'unavailable')

    def test_vm_status_timeout_is_visible_without_exposing_the_exception(self):
        import subprocess
        from unittest.mock import patch
        with patch('heist.platform.administration.subprocess.run',side_effect=subprocess.TimeoutExpired('qm',2)):
            self.assertEqual(Administration.vm_status(123),'unavailable')
