"""Durable administrator queue; uncertain work is never automatically replayed."""
from pathlib import Path

from psycopg2.extras import RealDictCursor

from .journal import Journal, RejectedOperation


class AdministratorQueue:
    def __init__(self,service):
        self.service=service

    def enqueue(self,actor,instance,action,expected,machine=None,*,request_id=None):
        from heist.platform.administration import AdminError
        if (machine is None and action not in ('release','rebuild','remove')) or (machine is not None and action not in ('start','shutdown','reboot')):
            raise AdminError('Invalid operation target',400)
        identifier=Journal.request_id(request_id)
        preview=self.service.preview(actor,instance,action,machine)
        if preview['fingerprint']!=expected:raise AdminError('Instance changed; review the action again')
        scope,resource=('user',preview['user_id']) if preview['user_id'] else ('instance',instance)
        with self.service.database(actor) as db,db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('SELECT * FROM public.administrator_requests WHERE id=%s',(identifier,))
            previous=cursor.fetchone()
            if previous:
                if any(previous[key]!=value for key,value in {'actor_id':actor,'instance_id':instance,'action':action,'machine_id':machine,'expected':expected}.items()):
                    raise AdminError('Request identifier was reused for different input')
                return {'job_id':identifier,'state':previous['state'],'scope':previous['scope'],'resource':previous['resource']}
            cursor.execute('''SELECT id FROM public.administrator_requests WHERE scope=%s AND resource=%s
                              AND state IN ('QUEUED','RUNNING','NEEDS_REVIEW')''',(scope,resource))
            if cursor.fetchone():raise AdminError('An operation is pending or requires reconciliation')
            # Serialize independent enqueue transactions, then recheck the actor.
            cursor.execute('SELECT pg_advisory_xact_lock(2147483000,%s)',(resource % 2147483647,))
            cursor.execute('SELECT is_admin FROM public.users WHERE id=%s',(actor,))
            row=cursor.fetchone()
            if not row or row['is_admin'] is not True:raise AdminError('Administrator access required',403)
            cursor.execute('''SELECT id FROM public.administrator_requests WHERE scope=%s AND resource=%s
                              AND state IN ('QUEUED','RUNNING','NEEDS_REVIEW')''',(scope,resource))
            if cursor.fetchone():raise AdminError('An operation is pending or requires reconciliation')
            cursor.execute('''INSERT INTO public.administrator_requests(id,actor_id,instance_id,scope,resource,action,machine_id,expected)
                              VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',(identifier,actor,instance,scope,resource,action,machine,expected))
        return {'job_id':identifier,'state':'QUEUED','scope':scope,'resource':resource}

    def cancel(self,actor,identifier):
        from heist.platform.administration import AdminError
        identifier=Journal.request_id(identifier)
        with self.service.database(actor) as db,db.cursor() as cursor:
            cursor.execute('''UPDATE public.administrator_requests SET state='CANCELLED',cancelled_by=%s,finished_at=clock_timestamp()
                              WHERE id=%s AND state='QUEUED' RETURNING id''',(actor,identifier))
            if not cursor.fetchone():raise AdminError('Only a queued operation can be cancelled')
        return {'job_id':identifier,'state':'CANCELLED'}

    def resolve(self,actor,identifier,reason,confirmation):
        from heist.platform.administration import AdminError
        identifier=Journal.request_id(identifier)
        if confirmation!=identifier or not isinstance(reason,str) or not 10<=len(reason.strip())<=500:
            raise AdminError('Record recovery checks and type the operation ID',400)
        with self.service.database(actor) as db,db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM public.administrator_requests WHERE id=%s AND state='NEEDS_REVIEW' FOR UPDATE",(identifier,))
            job=cursor.fetchone()
            if not job:raise AdminError('Only an uncertain queued operation can be reconciled')
            cursor.execute('SELECT is_admin FROM public.users WHERE id=%s',(actor,))
            row=cursor.fetchone()
            if not row or row['is_admin'] is not True:raise AdminError('Administrator access required',403)
            current=self.service.operation(job['scope'],job['resource'])
            if current and current.get('state')=='RUNNING':raise AdminError('A resource operation is still running')
            if current and current.get('state')=='NEEDS_REVIEW':
                if current['id']!=identifier:raise AdminError('Another resource operation needs reconciliation first')
                self.service.journal.resolve(job['scope'],job['resource'],identifier,reason.strip())
            cursor.execute("UPDATE public.administrator_requests SET state='RESOLVED',resolved_by=%s,resolution_reason=%s,finished_at=clock_timestamp() WHERE id=%s",(actor,reason.strip(),identifier))
        return {'job_id':identifier,'state':'RESOLVED'}

    def records(self,actor,*,scope=None,resource=None,state='all',limit=500):
        with self.service.database(actor) as db,db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''SELECT id,scope,resource,action,state,actor_id AS actor,created_at AS started,
                              finished_at AS finished,cancelled_by,resolved_by,instance_id,machine_id FROM public.administrator_requests
                              WHERE (%s::text IS NULL OR scope=%s) AND (%s::bigint IS NULL OR resource=%s)
                              AND (%s='all' OR state=%s) ORDER BY created_at DESC LIMIT %s''',(scope,scope,resource,resource,state,state,limit))
            records=[dict(row) for row in cursor.fetchall()]
        for row in records:
            row['managed_queue']=True
            row['action']='admin_'+('vm_' if row['action'] in ('start','shutdown','reboot') else '')+row['action']
            for key in ('started','finished'):
                if row[key] is not None:row[key]=row[key].isoformat()
        return records

    def recover_interrupted(self):
        """Call only while owning the deployment's singleton worker lease."""
        db=self.service.connect()
        try:
            with db,db.cursor() as cursor:
                cursor.execute("UPDATE public.administrator_requests SET state='NEEDS_REVIEW',finished_at=clock_timestamp(),message='Worker stopped before completion was confirmed' WHERE state='RUNNING'")
                return cursor.rowcount
        finally:db.close()

    def run_one(self,*,maintenance=None,ready=lambda:True):
        if not ready() or (maintenance is not None and Path(maintenance).exists()):return False
        db=self.service.connect()
        try:
            with db,db.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM public.administrator_requests WHERE state='QUEUED' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1")
                job=cursor.fetchone()
                if not job:return False
                cursor.execute("UPDATE public.administrator_requests SET state='RUNNING',started_at=clock_timestamp() WHERE id=%s",(job['id'],))
            try:
                if not ready() or (maintenance is not None and Path(maintenance).exists()):raise RejectedOperation('Platform stopped accepting operations before execution')
                if job['machine_id'] is not None:
                    self.service.change_vm(job['actor_id'],job['instance_id'],job['machine_id'],job['action'],job['expected'],request_id=job['id'])
                else:
                    self.service.change_instance(job['actor_id'],job['instance_id'],job['action'],expected=job['expected'],request_id=job['id'])
                state,message='SUCCEEDED',None
            except RejectedOperation as error:
                state,message='REJECTED',str(error)[:300]
            except Exception:
                state,message='NEEDS_REVIEW','Execution was not confirmed; reconcile actual resources before retrying'
            with db,db.cursor() as cursor:
                cursor.execute('UPDATE public.administrator_requests SET state=%s,message=%s,finished_at=clock_timestamp() WHERE id=%s',(state,message,job['id']))
            self.last_state=state
            self.last_identifier=job['id']
            return True
        finally:db.close()


def main():
    import argparse
    import json
    import time
    from heist.environment import load_backend_env
    from heist.api.internal import create_app
    from heist.files import maintenance_lock,private_directory
    from heist.runtime import cleanup_is_complete
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    parser.add_argument('--verify-runtime',action='store_true');args=parser.parse_args()
    load_backend_env()
    if args.verify_runtime:
        from heist.api.internal_serve import load_runtime
        load_runtime()
    app=create_app();service=app.extensions['administrator_service']()
    directory=private_directory(service.journal.directory/'administrator-worker')
    with maintenance_lock(directory):
        queue=AdministratorQueue(service)
        recovered=queue.recover_interrupted()
        print(json.dumps({'schema':1,'service':'administrator-worker','event':'worker_started','recovered_requests':recovered}),flush=True)
        while True:
            work=queue.run_one(maintenance=app.config['MAINTENANCE_FILE'],ready=lambda:cleanup_is_complete(app.config['CLEANUP_FILE']))
            if work:print(json.dumps({'schema':1,'service':'administrator-worker','event':'request_processed','job_id':queue.last_identifier,'state':queue.last_state}),flush=True)
            if args.once:return 0
            if not work:time.sleep(3)


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        import json
        print(json.dumps({'service':'administrator-worker','status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)
