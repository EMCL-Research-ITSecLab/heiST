"""Bounded administrator inspection and journalled recovery operations.

Only the privileged API imports this service. Browser database privileges stay
unchanged; passwords and raw host commands never enter diagnostics or journals.
"""
from contextlib import contextmanager
import subprocess
import re
from itertools import islice

from psycopg2.extras import RealDictCursor
from heist.platform.jobs.journal import RejectedOperation
from heist.security.passwords import hash_password


class AdminError(RejectedOperation):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Administration:
    def __init__(self, connect, journal, *, stop=None, launch=None, teardown=None, status=None):
        self.connect, self.journal = connect, journal
        self.stop, self.launch, self.teardown = stop, launch, teardown
        self.status = status or self.vm_status

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
            if item and (state=='all' or item.get('state')==state):
                records.append({**item,'scope':scope,'resource':resource})
        records.sort(key=lambda item:item.get('started',''),reverse=True)
        offset=(page-1)*25
        return {'jobs':records[offset:offset+25],'page':page,'has_more':len(records)>offset+25,'truncated':len(entries)>5000}

    def instances(self, actor, page=1):
        with self.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''SELECT c.id,c.challenge_template_id,t.name,c.lifecycle_state::text AS state,
                              c.expires_at,c.subnet::text AS subnet,c.pre_assigned_user_id,
                              u.id AS user_id,u.username,
                              (SELECT count(*) FROM public.machines m WHERE m.challenge_id=c.id) AS machines
                              FROM public.challenges c JOIN public.challenge_templates t ON t.id=c.challenge_template_id
                              LEFT JOIN public.users u ON u.running_challenge=c.id
                              ORDER BY c.id LIMIT 26 OFFSET %s''',((page-1)*25,))
            items=[dict(item) for item in cursor.fetchall()]
            return {'instances':items[:25],'has_more':len(items)>25,'page':page}

    def instance(self, actor, identifier):
        with self.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''SELECT c.id,c.challenge_template_id,c.lifecycle_state::text AS state,
                              t.name,c.pre_assigned_user_id,u.id AS user_id,u.username FROM public.challenges c
                              JOIN public.challenge_templates t ON t.id=c.challenge_template_id
                              LEFT JOIN public.users u ON u.running_challenge=c.id WHERE c.id=%s''',(identifier,))
            item=cursor.fetchone()
            if not item:raise AdminError('Instance not found',404)
            result=dict(item)
            cursor.execute('''SELECT m.id,t.name FROM public.machines m JOIN public.machine_templates t
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
        owner=result['user_id'] or result.get('pre_assigned_user_id')
        result['operation']=self.operation('instance',identifier) or (self.operation('user',owner) if owner else None)
        return result

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

    def change_instance(self, actor, identifier, action, *, request_id=None):
        if action not in ('release','rebuild','remove'):raise AdminError('Unknown instance action',400)
        item=self.instance(actor,identifier)
        if action in ('release','rebuild') and not item['user_id']:raise AdminError('Instance has no assigned student')
        if action=='remove' and (item['user_id'] or item['state'] not in ('READY','EXPIRED','TERMINATING') or (item['state']=='READY' and item['pre_assigned_user_id'])):
            raise AdminError('Release the student assignment before removing this instance')
        def change():
            # Revalidate authority and assignment after obtaining the operation lease.
            current=self.instance(actor,identifier)
            if current['user_id']!=item['user_id'] or current['challenge_template_id']!=item['challenge_template_id']:
                raise AdminError('Instance assignment changed; refresh before retrying')
            if action in ('release','rebuild'):
                if self.stop(item['user_id'],expected_challenge_id=identifier) is not True:
                    raise AdminError('Instance assignment changed; refresh before retrying')
            if action in ('remove','rebuild'):
                self.teardown(identifier,expected_template_id=item['challenge_template_id'])
                with self.database(actor) as db, db.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM public.challenges WHERE id=%s',(identifier,))
                    if cursor.fetchone():raise RuntimeError('Instance removal was not confirmed')
            if action=='rebuild':self.launch(item['challenge_template_id'],item['user_id'])
            return {'instance_id':identifier,'action':action}
        scope,key=('user',item['user_id']) if item['user_id'] else ('instance',identifier)
        return self.journal.execute(scope,key,'admin_'+action,{'actor':actor,'instance':identifier},change,request_id=request_id)
