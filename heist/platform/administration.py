"""Bounded administrator inspection and journalled recovery operations.

Only the privileged API imports this service. Browser database privileges stay
unchanged; passwords and raw host commands never enter diagnostics or journals.
"""
from contextlib import contextmanager
import subprocess
import re
import os
import hashlib
import json
import time
from itertools import islice

from psycopg2.extras import RealDictCursor
from heist.platform.jobs.journal import RejectedOperation
from heist.security.passwords import hash_password


class AdminError(RejectedOperation):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Administration:
    def __init__(self, connect, journal, *, stop=None, launch=None, teardown=None, status=None, vm_control=None):
        self.connect, self.journal = connect, journal
        self.stop, self.launch, self.teardown = stop, launch, teardown
        self.status = status or self.vm_status
        self.vm_control=vm_control or self.control_vm

    def overview(self,actor):
        from .management import overview
        return overview(self,actor)

    def maintenance(self,actor):
        with self.database(actor) as db,db.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.administrator_requests WHERE state IN ('QUEUED','RUNNING','NEEDS_REVIEW')")
            pending=cursor.fetchone()[0]
        from .management import maintenance
        return {**maintenance(os.environ),'pending_requests':pending}

    def audit(self,actor,page=1):
        with self.database(actor) as db,db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''SELECT e.id,e.recorded_at,e.action,e.resource_kind,e.resource_id,e.revision_id,e.fingerprint,
                              u.username AS actor FROM public.administrator_events e LEFT JOIN public.users u ON u.id=e.actor_id
                              ORDER BY e.id DESC LIMIT 26 OFFSET %s''',((page-1)*25,))
            values=[dict(row) for row in cursor.fetchall()]
        return {'events':values[:25],'has_more':len(values)>25,'page':page}

    def set_pool(self,actor,template,size,enabled,expected_revision,*,request_id=None):
        if type(size) is not int or not 0<=size<=10 or type(enabled) is not bool or type(expected_revision) is not int or expected_revision<0:
            raise AdminError('Choose a pool target between 0 and 10',400)
        def change():
            with self.database(actor) as db,db.cursor() as cursor:
                cursor.execute('SELECT is_active,ready_to_launch,marked_for_deletion FROM public.challenge_templates WHERE id=%s FOR UPDATE',(template,))
                item=cursor.fetchone()
                if not item:raise AdminError('Exercise not found',404)
                if enabled and size>0 and (not item[0] or not item[1] or item[2]):raise AdminError('Publish an import-ready exercise before preparing a pool')
                cursor.execute('SELECT revision FROM public.pool_overrides WHERE challenge_template_id=%s FOR UPDATE',(template,))
                old=cursor.fetchone()
                if (old[0] if old else 0)!=expected_revision:raise AdminError('Pool policy changed; refresh before saving')
                cursor.execute('SELECT is_admin FROM public.users WHERE id=%s',(actor,))
                if cursor.fetchone()!=(True,):raise AdminError('Administrator access required',403)
                cursor.execute('''INSERT INTO public.pool_overrides(challenge_template_id,enabled,size,updated_by) VALUES(%s,%s,%s,%s)
                                  ON CONFLICT(challenge_template_id) DO UPDATE SET enabled=EXCLUDED.enabled,size=EXCLUDED.size,
                                  revision=pool_overrides.revision+1,updated_at=clock_timestamp(),updated_by=EXCLUDED.updated_by
                                  RETURNING revision''',(template,enabled,size,actor))
                revision=cursor.fetchone()[0]
            return {'template_id':template,'size':size,'enabled':enabled,'revision':revision,'application':'pending_pool_manager'}
        return self.journal.execute('pool',template,'admin_pool_override',{'actor':actor,'size':size,'enabled':enabled,'expected_revision':expected_revision},change,request_id=request_id)

    def job_history(self,actor,scope,identifier):
        with self.database(actor):pass
        from .jobs.administrator import AdministratorQueue
        history=self.journal.history(scope,identifier)
        queued=AdministratorQueue(self).records(actor,scope=scope,resource=identifier,limit=51)
        merged={item['id']:item for item in queued}
        for item in history['operations']:
            queued_item=merged.get(item['id'],{})
            merged[item['id']]={**queued_item,**item}
            if queued_item.get('state')=='NEEDS_REVIEW':merged[item['id']]['state']='NEEDS_REVIEW'
        records=sorted(merged.values(),key=lambda item:item.get('started',''),reverse=True)
        return {'operations':records[:50],'truncated':history['truncated'] or len(records)>50,'current':history.get('current')}

    @contextmanager
    def database(self, actor):
        db = self.connect()
        try:
            # Fresh statements after an authority lock must see role revocations.
            db.set_session(isolation_level='READ COMMITTED',autocommit=False)
            with db:
                with db.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout='5s'")
                    cursor.execute("SET LOCAL lock_timeout='3s'")
                    cursor.execute('SELECT is_admin FROM public.users WHERE id=%s', (actor,))
                    value = cursor.fetchone()
                    if not value or value[0] is not True:
                        raise AdminError('Administrator access required', 403)
                yield db
        finally:
            db.close()

    def users(self, actor, search='', page=1):
        with self.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            pattern = '%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            cursor.execute('''SELECT id,username,email,is_admin,password_reset,created_at,last_login,
                              running_challenge,host(vpn_static_ip) AS vpn_ip,
                              (SELECT count(*) FROM public.web_sessions s WHERE s.user_id=u.id AND s.expires_at>CURRENT_TIMESTAMP) AS sessions
                              FROM public.users u WHERE username ILIKE %s OR email ILIKE %s
                              ORDER BY id LIMIT 26 OFFSET %s''', (pattern, pattern, (page-1)*25))
            items = [dict(item) for item in cursor.fetchall()]
            for item in items[:25]:item['operation']=self.operation('user',item['id'])
            return {'users':items[:25], 'has_more':len(items)>25, 'page':page}

    def change_user(self, actor, identifier, action, confirmation, *, password=None, administrator=None, request_id=None):
        # Replays must not bypass a later revocation of the acting administrator.
        with self.database(actor):
            pass
        if action not in ('role','password','revoke_sessions'):
            raise AdminError('Unknown user action',400)
        if action=='role' and type(administrator) is not bool:
            raise AdminError('Choose an administrator role',400)
        if action=='password':
            try: encoded=hash_password(password)
            except ValueError as error: raise AdminError(str(error),400) from None
        # The journal stores a fingerprint and safe result, never the password,
        # its hash, or a digest permitting offline guesses of a temporary secret.
        payload={'actor':actor,'user':identifier,'action':action,'administrator':administrator}
        def change():
            with self.database(actor) as db, db.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('heist-web-admin-accounts',0))")
                cursor.execute('SELECT is_admin FROM public.users WHERE id=%s',(actor,))
                authority=cursor.fetchone()
                if not authority or authority[0] is not True:raise AdminError('Administrator access required',403)
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('heist-web-auth:'||%s::text,0))", (identifier,))
                cursor.execute('SELECT username,is_admin FROM public.users WHERE id=%s FOR UPDATE',(identifier,))
                user=cursor.fetchone()
                if not user:raise AdminError('User not found',404)
                if confirmation!=user[0]:raise AdminError('Type the username to confirm',400)
                if actor==identifier:raise AdminError('Use another administrator to change your own account')
                if action=='role':
                    if user[1] and not administrator:
                        cursor.execute('SELECT count(*) FROM public.users WHERE is_admin=TRUE')
                        if cursor.fetchone()[0]<=1:raise AdminError('The last administrator must remain')
                    cursor.execute('UPDATE public.users SET is_admin=%s WHERE id=%s',(administrator,identifier))
                elif action=='password':
                    cursor.execute('''UPDATE public.users SET password_hash=%s,password_salt='',
                                      password_reset=TRUE,password_reset_timestamp=CURRENT_TIMESTAMP WHERE id=%s''',(encoded,identifier))
                cursor.execute('''INSERT INTO public.web_auth_state(user_id,auth_version) VALUES (%s,1)
                                  ON CONFLICT(user_id) DO UPDATE SET auth_version=public.web_auth_state.auth_version+1''',(identifier,))
                cursor.execute('DELETE FROM public.web_sessions WHERE user_id=%s',(identifier,))
            return {'user_id':identifier,'action':action,'sessions_revoked':True}
        return self.journal.execute('user',identifier,'admin_'+action,payload,change,request_id=request_id)

    def jobs(self, actor, page=1, state='all'):
        with self.database(actor):
            pass
        records=[]
        entries=list(islice(self.journal.directory.iterdir(),5001))
        for path in entries[:5000]:
            match=re.fullmatch(r'(user|template|pool|artifact|instance)-([1-9][0-9]{0,18})',path.name)
            if not match or path.is_symlink() or not path.is_dir():continue
            current=path/'current.json'
            if not current.is_file() or current.is_symlink():continue
            scope,resource=match[1],int(match[2])
            item=self.operation(scope,resource)
            if item:
                records.append({**item,'scope':scope,'resource':resource})
        from .jobs.administrator import AdministratorQueue
        queued=AdministratorQueue(self).records(actor,state='all',limit=501)
        merged={item['id']:item for item in queued}
        for item in records:
            key=item.get('id') or 'unavailable:'+str(item['scope'])+':'+str(item['resource'])
            queued_item=merged.get(key,{})
            merged[key]={**queued_item,**item}
            if queued_item.get('state')=='NEEDS_REVIEW':merged[key]['state']='NEEDS_REVIEW'
        records=list(merged.values())
        if state!='all':records=[item for item in records if item.get('state')==state]
        records.sort(key=lambda item:item.get('started',''),reverse=True)
        offset=(page-1)*25
        return {'jobs':records[offset:offset+25],'page':page,'has_more':len(records)>offset+25,'truncated':len(entries)>5000 or len(queued)>500}

    def instances(self, actor, page=1, search='', state='all', template_id=None):
        if state not in ('all','PROVISIONING','READY','ASSIGNED','ACTIVE','EXPIRED','TERMINATING') or not isinstance(search,str) or len(search)>100:
            raise AdminError('Invalid instance filter',400)
        with self.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            pattern='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            cursor.execute('''SELECT c.id,c.challenge_template_id,t.name,c.lifecycle_state::text AS state,
                              c.expires_at,c.subnet::text AS subnet,c.pre_assigned_user_id,
                              u.id AS user_id,u.username,
                              (SELECT count(*) FROM public.machines m WHERE m.challenge_id=c.id) AS machines
                              FROM public.challenges c JOIN public.challenge_templates t ON t.id=c.challenge_template_id
                              LEFT JOIN public.users u ON u.running_challenge=c.id
                              WHERE (%s='all' OR c.lifecycle_state::text=%s)
                              AND (%s::bigint IS NULL OR c.challenge_template_id=%s)
                              AND (t.name ILIKE %s OR COALESCE(u.username,'') ILIKE %s OR c.id::text ILIKE %s)
                              ORDER BY c.id LIMIT 26 OFFSET %s''',(state,state,template_id,template_id,pattern,pattern,pattern,(page-1)*25))
            items=[dict(item) for item in cursor.fetchall()]
            return {'instances':items[:25],'has_more':len(items)>25,'page':page}

    def activity(self, actor, instance_id=None):
        # Recheck authority before reading private telemetry or credentials.
        machines = None
        with self.database(actor) as db, db.cursor() as cursor:
            if instance_id is not None:
                cursor.execute('SELECT id FROM public.challenges WHERE id=%s', (instance_id,))
                if not cursor.fetchone():raise AdminError('Instance not found', 404)
                cursor.execute('SELECT id FROM public.machines WHERE challenge_id=%s ORDER BY id LIMIT 21', (instance_id,))
                machines = [row[0] for row in cursor.fetchall()]
        settings = dict(os.environ)
        filename = settings.get('HEIST_MONITORING_ENVIRONMENT_FILE')
        if filename:
            from pathlib import Path
            from dotenv import dotenv_values
            path = Path(filename)
            if not path.is_absolute() or '..' in path.parts:raise ValueError('Invalid monitoring environment path')
            settings.update({k:v for k,v in dotenv_values(path).items() if v is not None})
        from heist.monitoring.activity import read
        return read(settings, machines)

    def instance(self, actor, identifier):
        with self.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''SELECT c.id,c.challenge_template_id,c.lifecycle_state::text AS state,c.expires_at,
                              (SELECT a.activated_at FROM public.instance_activations a WHERE a.challenge_id=c.id) AS activated_at,c.subnet::text AS subnet,
                              t.name,c.pre_assigned_user_id,u.id AS user_id,u.username FROM public.challenges c
                              JOIN public.challenge_templates t ON t.id=c.challenge_template_id
                              LEFT JOIN public.users u ON u.running_challenge=c.id WHERE c.id=%s''',(identifier,))
            item=cursor.fetchone()
            if not item:raise AdminError('Instance not found',404)
            result=dict(item)
            cursor.execute('''SELECT m.id,t.name,t.cores,t.ram_gb,t.ad_role::text AS ad_role,t.disk_file_id FROM public.machines m JOIN public.machine_templates t
                              ON t.id=m.machine_template_id WHERE m.challenge_id=%s ORDER BY m.id LIMIT 20''',(identifier,))
            result['machines']=[dict(row) for row in cursor.fetchall()]
            cursor.execute('''SELECT n.id,t.name,n.subnet::text AS subnet,t.accessible,t.is_dmz
                              FROM public.networks n JOIN public.network_templates t ON t.id=n.network_template_id
                              WHERE n.challenge_id=%s ORDER BY n.id LIMIT 20''',(identifier,))
            result['networks']=[dict(row) for row in cursor.fetchall()]
            cursor.execute('''SELECT nc.machine_id,nc.network_id,host(nc.client_ip) AS address,nc.client_mac::text AS mac
                              FROM public.network_connections nc JOIN public.networks n ON n.id=nc.network_id
                              WHERE n.challenge_id=%s ORDER BY nc.machine_id,nc.network_id LIMIT 400''',(identifier,))
            result['connections']=[dict(row) for row in cursor.fetchall()]
        for machine in result['machines']:machine['status']=self.status(machine['id'])
        from heist.monitoring.agents import instance as instance_monitoring
        result['monitoring'] = instance_monitoring(result['machines'], os.environ)
        owner=result['user_id'] or result.get('pre_assigned_user_id')
        result['operation']=self.operation('instance',identifier) or (self.operation('user',owner) if owner else None)
        result['fingerprint']=self.instance_fingerprint(result)
        return result

    @staticmethod
    def instance_fingerprint(item):
        value={key:item.get(key) for key in ('id','challenge_template_id','state','user_id','pre_assigned_user_id','activated_at','expires_at','subnet')}
        value['machines']=[{key:m.get(key) for key in ('id','disk_file_id','cores','ram_gb','ad_role')} for m in item['machines']]
        value['networks']=[n['id'] for n in item['networks']]
        value['connections']=item['connections']
        return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

    def preview(self,actor,identifier,action,machine_id=None):
        item=self.instance(actor,identifier)
        if action not in ('release','rebuild','remove','start','shutdown','reboot'):raise AdminError('Unknown action',400)
        if action in ('release','rebuild') and not item['user_id']:raise AdminError('Instance has no assigned student')
        if action=='remove' and (item['user_id'] or item['state'] not in ('READY','EXPIRED','TERMINATING') or (item['state']=='READY' and item['pre_assigned_user_id'])):
            raise AdminError('Release the assignment before removing this instance')
        if action in ('start','shutdown','reboot'):
            machine=next((m for m in item['machines'] if m['id']==machine_id),None)
            if not machine:raise AdminError('Machine not found in this instance',404)
            if item['state'] not in ('READY','ACTIVE','ASSIGNED'):raise AdminError('Instance lifecycle does not allow VM control')
            if machine['status'] not in ('running','stopped'):raise AdminError('VM state is unavailable')
            if (action=='start')!=(machine['status']=='stopped'):raise AdminError('VM state does not allow this action')
        return {'instance_id':identifier,'name':item['name'],'action':action,'machine_id':machine_id,
                'fingerprint':item['fingerprint'],'state':item['state'],'user_id':item['user_id'],
                'machines':[m['id'] for m in item['machines']] if machine_id is None else [machine_id],
                'networks':[n['id'] for n in item['networks']] if action in ('remove','rebuild') else [],
                'guest_changes_lost':action in ('remove','rebuild'),'grades_preserved':True}

    @staticmethod
    def control_vm(identifier,action):
        if type(identifier) is not int or identifier<=0 or action not in ('start','shutdown','reboot'):raise ValueError('Invalid VM command')
        args=['qm',action,str(identifier)]+(['--timeout','60'] if action in ('shutdown','reboot') else [])
        subprocess.run(args,check=True,capture_output=True,timeout=75)

    def change_vm(self,actor,identifier,machine_id,action,expected,*,request_id=None):
        if action not in ('start','shutdown','reboot'):raise AdminError('Unknown VM action',400)
        preview=self.preview(actor,identifier,action,machine_id)
        if preview['fingerprint']!=expected:raise AdminError('Instance changed; review the action again')
        def change(progress):
            progress('checking_assignment')
            current=self.preview(actor,identifier,action,machine_id)
            if current['fingerprint']!=expected:raise AdminError('Instance changed; review the action again')
            progress('requesting_'+action)
            self.vm_control(machine_id,action)
            progress('verifying_vm_state')
            target='stopped' if action=='shutdown' else 'running'
            self.wait_for_vm_state(machine_id,target)
            return {'machine_id':machine_id,'action':action,'status':target,'guest_readiness':'unverified'}
        scope,key=('user',preview['user_id']) if preview['user_id'] else ('instance',identifier)
        return self.journal.execute(scope,key,'admin_vm_'+action,{'actor':actor,'instance':identifier,'machine':machine_id,'expected':expected},change,
                                    request_id=request_id,with_progress=True)

    def operation(self,scope,identifier):
        try:return self.journal.inspect(scope,identifier)
        except (OSError,ValueError,KeyError,TypeError):return {'state':'UNAVAILABLE','scope':scope,'resource':identifier}

    @staticmethod
    def vm_status(identifier):
        try:
            value=subprocess.run(['qm','status',str(identifier)],capture_output=True,text=True,timeout=2)
            if value.returncode==0 and value.stdout.strip() in ('status: running','status: stopped'):
                return value.stdout.strip().removeprefix('status: ')
        except (OSError,subprocess.TimeoutExpired):pass
        return 'unavailable'

    def wait_for_vm_state(self, identifier, target, *, timeout=60, clock=None, pause=None):
        """Observe an already submitted task; never repeat its power command.

        A successful Proxmox reboot can briefly report stopped while QEMU comes
        back. Unavailable status is also possible during that transition. Only
        the requested final power state confirms completion; a bounded timeout
        leaves the existing operation held for reconciliation.
        """
        clock = clock or time.monotonic
        pause = pause or time.sleep
        deadline = clock()+timeout
        while True:
            if self.status(identifier) == target:
                return
            remaining = deadline-clock()
            if remaining <= 0:
                raise RuntimeError('VM state was not confirmed')
            pause(min(1,remaining))

    def change_instance(self, actor, identifier, action, *, request_id=None, expected=None):
        if action not in ('release','rebuild','remove'):raise AdminError('Unknown instance action',400)
        item=self.instance(actor,identifier)
        if expected is not None and item['fingerprint']!=expected:raise AdminError('Instance changed; review the action again')
        if action in ('release','rebuild') and not item['user_id']:raise AdminError('Instance has no assigned student')
        if action=='remove' and (item['user_id'] or item['state'] not in ('READY','EXPIRED','TERMINATING') or (item['state']=='READY' and item['pre_assigned_user_id'])):
            raise AdminError('Release the student assignment before removing this instance')
        def change(progress):
            progress('checking_assignment')
            # Revalidate authority and assignment after obtaining the operation lease.
            current=self.instance(actor,identifier)
            if expected is not None and current['fingerprint']!=expected:raise AdminError('Instance changed; review the action again')
            if current['user_id']!=item['user_id'] or current['challenge_template_id']!=item['challenge_template_id']:
                raise AdminError('Instance assignment changed; refresh before retrying')
            if action in ('release','rebuild'):
                progress('releasing_assignment')
                if self.stop(item['user_id'],expected_challenge_id=identifier) is not True:
                    raise AdminError('Instance assignment changed; refresh before retrying')
            if action in ('remove','rebuild'):
                progress('removing_instance')
                self.teardown(identifier,expected_template_id=item['challenge_template_id'])
                with self.database(actor) as db, db.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM public.challenges WHERE id=%s',(identifier,))
                    if cursor.fetchone():raise RuntimeError('Instance removal was not confirmed')
            if action=='rebuild':
                progress('launching_replacement')
                self.launch(item['challenge_template_id'],item['user_id'])
            progress('completed')
            return {'instance_id':identifier,'action':action}
        scope,key=('user',item['user_id']) if item['user_id'] else ('instance',identifier)
        return self.journal.execute(scope,key,'admin_'+action,{'actor':actor,'instance':identifier,'expected':expected},change,request_id=request_id,with_progress=True)
