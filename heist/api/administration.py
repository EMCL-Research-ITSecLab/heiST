"""Fixed internal administrator routes; no arbitrary commands or SQL are exposed."""
from flask import Blueprint, current_app, request
from heist.platform.administration import AdminError
from heist.platform.jobs.journal import Journal, RecoveryRequired, RejectedOperation


def blueprint(factory):
    routes=Blueprint('platform_administration',__name__)

    def value():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise AdminError('JSON object required',400)
        return data

    def identifier(item):
        if type(item) is not int or not 0<item<2**63:raise AdminError('Positive integer required',400)
        return item

    def run(function):
        try:return {'success':True,'data':function(factory(),value())}
        except ValueError:return {'success':False,'message':'Invalid administrator request'},400
        except AdminError as error:return {'success':False,'message':str(error)},error.status
        except (RecoveryRequired,RejectedOperation,BlockingIOError):
            return {'success':False,'message':'An operation requires reconciliation; inspect before retrying'},409
        except Exception as error:
            current_app.logger.error('Administrator operation failed: %s',type(error).__name__)
            return {'success':False,'message':'Administrator operation unavailable; inspect its journal before retrying'},503

    def page(data):
        p=identifier(data.get('page',1))
        if p>10000:raise AdminError('Page is out of range',400)
        return p

    @routes.get('/admin/users')
    def users():
        def load(service,data):
            search=data.get('search','')
            if not isinstance(search,str) or len(search)>100:raise AdminError('Search is too long',400)
            return service.users(identifier(data.get('actor_id')),search,page(data))
        return run(load)

    @routes.post('/admin/users/manage')
    def manage_user():
        def change(service,data):
            confirmation=data.get('confirmation')
            if not isinstance(confirmation,str) or len(confirmation)>20:raise AdminError('Type the username to confirm',400)
            return service.change_user(identifier(data.get('actor_id')),identifier(data.get('user_id')),
                data.get('action'),confirmation,password=data.get('password'),administrator=data.get('administrator'),
                request_id=Journal.request_id(request.headers.get('Idempotency-Key')))
        return run(change)

    @routes.get('/admin/jobs')
    def jobs():
        def load(service,data):
            state=data.get('state','all')
            if state not in ('all','RUNNING','NEEDS_REVIEW','SUCCEEDED','REJECTED','RESOLVED','UNAVAILABLE'):
                raise AdminError('Unknown operation state',400)
            return service.jobs(identifier(data.get('actor_id')),page(data),state)
        return run(load)

    @routes.get('/admin/instances')
    def instances():return run(lambda service,data:service.instances(identifier(data.get('actor_id')),page(data)))

    @routes.get('/admin/instances/details')
    def instance():return run(lambda service,data:service.instance(identifier(data.get('actor_id')),identifier(data.get('instance_id'))))

    @routes.post('/admin/instances/manage')
    def manage_instance():
        from heist.runtime import cleanup_is_complete
        data=request.get_json(silent=True)
        if isinstance(data,dict) and data.get('action')=='rebuild' and not cleanup_is_complete(current_app.config['CLEANUP_FILE']):
            return {'success':False,'message':'Startup cleanup requires reconciliation before rebuilding'},503
        return run(lambda service,data:service.change_instance(identifier(data.get('actor_id')),identifier(data.get('instance_id')),
            data.get('action'),request_id=Journal.request_id(request.headers.get('Idempotency-Key'))))
    return routes
