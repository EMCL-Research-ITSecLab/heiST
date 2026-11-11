"""Real PostgreSQL queue ownership, stale previews and uncertain execution."""
import os
import unittest
from unittest.mock import Mock,patch

from tests import test_platform_administration as fixture
from heist.platform.administration import AdminError
from heist.platform.jobs.administrator import AdministratorQueue


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Disposable PostgreSQL required')
class AdministratorQueueTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PlatformAdministrationTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.PlatformAdministrationTests.tearDownClass.__func__)
    remove_database=classmethod(fixture.PlatformAdministrationTests.remove_database.__func__)
    sql=fixture.PlatformAdministrationTests.sql
    release=fixture.PlatformAdministrationTests.release

    def setUp(self):
        fixture.PlatformAdministrationTests.setUp(self)
        self.sql('DELETE FROM public.administrator_requests')
        self.queue=AdministratorQueue(self.service)
        disk=self.sql("INSERT INTO disk_files(user_id,display_name,proxmox_filename) VALUES(%s,'fixture',%s) RETURNING id",(self.user_id,self.username+'.ova'))[0][0]
        template=self.sql("INSERT INTO machine_templates(challenge_template_id,name,disk_file_id,cores,ram_gb) VALUES(%s,'target',%s,1,1) RETURNING id",(self.template,disk))[0][0]
        self.machine=self.sql('INSERT INTO machines(machine_template_id,challenge_id) VALUES(%s,%s) RETURNING id',(template,self.instance))[0][0]
        self.service.vm_control=Mock(side_effect=lambda vm,action:setattr(self.service.status,'return_value','stopped' if action=='shutdown' else 'running'))

    def enqueue(self,action='shutdown',identifier='a'*32):
        preview=self.service.preview(self.admin,self.instance,action,self.machine if action in ('start','shutdown','reboot') else None)
        return self.queue.enqueue(self.admin,self.instance,action,preview['fingerprint'],self.machine if action in ('start','shutdown','reboot') else None,request_id=identifier)

    def test_enqueue_does_not_execute_and_worker_runs_once_with_progress(self):
        job=self.enqueue();self.service.vm_control.assert_not_called()
        self.assertEqual(job['state'],'QUEUED')
        self.assertTrue(self.queue.run_one())
        self.service.vm_control.assert_called_once_with(self.machine,'shutdown')
        self.assertFalse(self.queue.run_one())
        history=self.service.job_history(self.admin,'user',self.user_id)
        operation=next(row for row in history['operations'] if row['id']==job['job_id'])
        self.assertEqual(operation['state'],'SUCCEEDED')
        self.assertEqual(operation['actor'],self.admin)
        self.assertEqual([event['stage'] for event in operation['events']],['checking_assignment','requesting_shutdown','verifying_vm_state'])
        self.assertNotIn('expected',str(history))

    def test_pending_duplicate_cancel_and_role_revocation_are_checked(self):
        job=self.enqueue()
        self.assertEqual(self.enqueue()['job_id'],job['job_id'])
        with self.assertRaises(AdminError):self.enqueue(identifier='b'*32)
        with self.assertRaises(AdminError):self.queue.cancel(self.user_id,job['job_id'])
        self.queue.cancel(self.admin,job['job_id'])
        self.assertFalse(self.queue.run_one());self.service.vm_control.assert_not_called()
        self.enqueue(identifier='c'*32)
        self.sql('UPDATE users SET is_admin=FALSE WHERE id=%s',(self.admin,))
        self.queue.run_one()
        self.assertEqual(self.sql("SELECT state FROM administrator_requests WHERE id=%s",('c'*32,)),[('REJECTED',)])
        self.service.vm_control.assert_not_called()

    def test_assignment_change_and_unowned_vm_never_reach_hypervisor(self):
        with self.assertRaises(AdminError):self.service.preview(self.admin,self.instance,'reboot',9000)
        self.enqueue()
        self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s",(self.instance,))
        self.queue.run_one()
        self.assertEqual(self.sql('SELECT state FROM administrator_requests WHERE id=%s',('a'*32,)),[('REJECTED',)])
        self.service.vm_control.assert_not_called()

    def test_uncertain_execution_blocks_replay_until_recorded_reconciliation(self):
        job=self.enqueue();self.service.vm_control.side_effect=RuntimeError('fixture-private-error')
        self.queue.run_one()
        self.assertEqual(self.sql('SELECT state FROM administrator_requests WHERE id=%s',(job['job_id'],)),[('NEEDS_REVIEW',)])
        with self.assertRaises(AdminError):self.queue.cancel(self.admin,job['job_id'])
        with self.assertRaises(AdminError):self.queue.resolve(self.admin,job['job_id'],'checked','wrong')
        self.queue.resolve(self.admin,job['job_id'],'Independently checked VM and assignment state',job['job_id'])
        self.assertEqual(self.sql('SELECT state,resolved_by FROM administrator_requests WHERE id=%s',(job['job_id'],)),[('RESOLVED',self.admin)])
        self.assertEqual(self.service.operation('user',self.user_id)['state'],'RESOLVED')
        self.assertNotIn('fixture-private-error',str(self.service.jobs(self.admin)))
        self.assertEqual(self.service.vm_control.call_count,1)

    def test_restart_and_readiness_guards_do_not_replay_work(self):
        job=self.enqueue()
        self.assertFalse(self.queue.run_one(ready=lambda:False));self.service.vm_control.assert_not_called()
        self.sql("UPDATE administrator_requests SET state='RUNNING' WHERE id=%s",(job['job_id'],))
        self.queue.recover_interrupted()
        self.assertFalse(self.queue.run_one());self.service.vm_control.assert_not_called()
        self.assertEqual(self.sql('SELECT state FROM administrator_requests WHERE id=%s',(job['job_id'],)),[('NEEDS_REVIEW',)])

    def test_server_filters_and_overview_are_admin_only(self):
        with self.assertRaises(AdminError):self.service.overview(self.user_id)
        with patch('heist.platform.management.host_capacity',return_value={'status':'unavailable'}):
            result=self.service.overview(self.admin)
        self.assertGreaterEqual(result['counts']['machines'],1)
        self.assertEqual(result['host']['status'],'unavailable')
        self.assertEqual(result['training']['capture_status'],'disabled')
        self.assertEqual(self.service.instances(self.admin,search=self.username)['instances'][0]['id'],self.instance)
        self.assertEqual(self.service.instances(self.admin,state='READY',template_id=self.template)['instances'],[])
        self.assertEqual(self.service.instances(self.admin,search='%')['instances'],[])

    def test_pool_policy_uses_revision_and_requires_publish_readiness(self):
        with self.assertRaises(AdminError):self.service.set_pool(self.admin,self.template,2,True,0)
        self.sql('UPDATE challenge_templates SET is_active=TRUE,ready_to_launch=TRUE WHERE id=%s',(self.template,))
        result=self.service.set_pool(self.admin,self.template,2,True,0)
        self.assertEqual(result['application'],'pending_pool_manager')
        with self.assertRaises(AdminError):self.service.set_pool(self.admin,self.template,3,True,0)
        from heist.platform.pools.manager import PoolManager
        with self.psycopg2.connect(**self.settings) as db:
            self.assertEqual(PoolManager.__new__(PoolManager).get_target_pool_size(db,self.template),2)
        self.service.set_pool(self.admin,self.template,2,False,result['revision'])
        self.service.vm_control.assert_not_called()

    def test_zero_manual_pool_target_does_not_schedule_a_minimum_copy(self):
        from heist.platform.pools.manager import PoolManager
        self.sql('UPDATE challenge_templates SET is_active=TRUE,ready_to_launch=TRUE WHERE id=%s',(self.template,))
        self.service.set_pool(self.admin,self.template,0,True,0)
        manager=PoolManager.__new__(PoolManager)
        manager.minimal_pool_size=1;manager.maximal_pool_size=10
        with self.psycopg2.connect(**self.settings) as db, \
             patch('heist.platform.pools.manager.pool_template_ids',return_value=[self.template]), \
             patch('heist.platform.pools.manager.threading.Thread') as thread:
            manager._check_and_maintain_pool(db)
            thread.assert_not_called()
            self.assertEqual(manager.get_target_pool_size(db,self.template),0)
            self.sql('UPDATE pool_overrides SET enabled=FALSE WHERE challenge_template_id=%s',(self.template,))
            with patch.object(manager,'forecast_pool_size',return_value=0):
                self.assertEqual(manager.get_target_pool_size(db,self.template),1)
            with patch.object(manager,'forecast_pool_size',return_value=100):
                self.assertEqual(manager.get_target_pool_size(db,self.template),10)

    def test_internal_http_acknowledges_queue_without_executing_vm_command(self):
        from pathlib import Path
        from heist.api.internal import create_app
        cleanup=Path(self.temporary.name)/'cleanup';cleanup.write_text('complete\n')
        app=create_app({'TESTING':True,'BACKEND_AUTHENTICATION_TOKEN':'fixture-token','OPERATION_DIRECTORY':str(self.journal.directory),
            'CLEANUP_FILE':str(cleanup),'MAINTENANCE_FILE':str(Path(self.temporary.name)/'maintenance')},
            services={'get_db_connection':self.service.connect,'vm_status':self.service.status,'vm_control':self.service.vm_control})
        preview=self.service.preview(self.admin,self.instance,'shutdown',self.machine)
        client=app.test_client()
        data={'actor_id':self.admin,'instance_id':self.instance,'machine_id':self.machine,'action':'shutdown','expected':preview['fingerprint']}
        response=client.post('/admin/instances/machines/manage',base_url='https://localhost',json=data,headers={'Authentication-Token':'fixture-token'})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['data']['state'],'QUEUED')
        self.service.vm_control.assert_not_called()

    def test_queue_needs_review_is_not_hidden_by_a_terminal_journal(self):
        job=self.enqueue();self.queue.run_one()
        self.sql("UPDATE administrator_requests SET state='RUNNING' WHERE id=%s",(job['job_id'],))
        self.queue.recover_interrupted()
        result=self.service.job_history(self.admin,'user',self.user_id)
        self.assertEqual(next(v for v in result['operations'] if v['id']==job['job_id'])['state'],'NEEDS_REVIEW')
        self.assertEqual(self.service.jobs(self.admin,state='NEEDS_REVIEW')['jobs'][0]['state'],'NEEDS_REVIEW')
