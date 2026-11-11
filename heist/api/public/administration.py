"""Administrator operations with explicit methods and server-refreshed roles."""
from flask import Blueprint, request

from .context import body, internal, rate_limit, repository, require_admin
from .errors import ApiError
from .learning import pagination
from .validation import choice, positive_id, text

blueprint = Blueprint('administration', __name__)
DIAGNOSTIC_FIELDS = ('checked_at', 'database', 'maintenance', 'lifecycle', 'services', 'archive', 'monitoring', 'release', 'source_version', 'storage')


@blueprint.get('/admin/overview')
def overview():
    actor=require_admin()
    rate_limit('admin-overview',str(actor['id']),30)
    return internal().request('admin_overview',{'actor_id':actor['id']})


@blueprint.get('/admin/audit')
def audit():
    actor=require_admin();page,_,_=pagination(25)
    return internal().request('admin_audit',{'actor_id':actor['id'],'page':page})


@blueprint.get('/admin/maintenance')
def maintenance():
    actor=require_admin()
    return internal().request('admin_maintenance',{'actor_id':actor['id']})


@blueprint.post('/admin/pools/<identifier>')
def pool(identifier):
    actor=require_admin();rate_limit('admin-pools',str(actor['id']),20)
    data=body();size=data.get('size');revision=data.get('expected_revision');enabled=data.get('enabled')
    if type(size) is not int or not 0<=size<=10 or type(revision) is not int or revision<0 or type(enabled) is not bool:
        raise ApiError('Choose a pool target between 0 and 10')
    return internal().request('admin_pool_change',{'actor_id':actor['id'],'template_id':positive_id(identifier,'exercise identifier'),
        'size':size,'enabled':enabled,'expected_revision':revision})


@blueprint.get('/admin/operations')
def operations():
    user = require_admin()
    rate_limit('admin-diagnostics', str(user['id']), 60)
    value = internal().request('operations').get('data')
    if not isinstance(value, dict):
        raise ApiError('Platform diagnostics are temporarily unavailable', 503)
    return {'success': True, 'data': {key: value[key] for key in DIAGNOSTIC_FIELDS if key in value}}


@blueprint.get('/admin/announcements')
def announcements():
    require_admin()
    page, size, offset = pagination(10)
    return {'success': True, 'data': {'announcements': repository().call('get_announcements', size, offset),
            'total': repository().scalar('get_total_announcement_count'), 'page': page}}


def announcement_fields(value):
    return (text(value.get('title'), name='Title', minimum=1, maximum=100).strip(),
            text(value.get('content'), name='Announcement', minimum=1, maximum=5000).strip(),
            text(value.get('short_description', ''), name='Short description', maximum=255).strip(),
            choice(value.get('importance'), ('normal', 'important', 'critical'), 'importance'),
            choice(value.get('category'), ('general', 'updates', 'maintenance', 'events', 'security'), 'category'))


@blueprint.post('/admin/announcements')
def create_announcement():
    user = require_admin()
    rate_limit('admin-announcement', str(user['id']), 30)
    arguments = announcement_fields(body())
    if not arguments[0] or not arguments[1]:
        raise ApiError('Title and announcement are required')
    identifier = repository().scalar('create_announcement', *arguments, user['username'])
    return {'success': True, 'message': 'Announcement published', 'id': identifier}


@blueprint.route('/admin/announcements/<identifier>', methods=['PUT', 'DELETE'])
def change_announcement(identifier):
    user = require_admin()
    rate_limit('admin-announcement', str(user['id']), 30)
    identifier = positive_id(identifier, 'announcement identifier')
    repo = repository()
    with repo.transaction():
        if not repo.scalar('announcement_exists', identifier):
            raise ApiError('Announcement not found', 404)
        if request.method == 'DELETE':
            repo.call('delete_announcement', identifier)
        else:
            arguments = announcement_fields(body())
            if not arguments[0] or not arguments[1]:
                raise ApiError('Title and announcement are required')
            repo.call('update_announcement', identifier, *arguments)
    return {'success': True, 'message': 'Announcement deleted' if request.method == 'DELETE' else 'Announcement updated'}


@blueprint.get('/admin/users')
def users():
    actor=require_admin()
    page,_,_=pagination(25)
    search=text(request.args.get('search',''),name='Search',maximum=100)
    return internal().request('admin_users',{'actor_id':actor['id'],'page':page,'search':search})


@blueprint.post('/admin/users/<identifier>')
def manage_user(identifier):
    actor=require_admin()
    rate_limit('admin-users',str(actor['id']),20)
    data=body()
    action=choice(data.get('action'),('role','password','revoke_sessions'),'user action')
    confirmation=text(data.get('confirmation'),name='Confirmation',minimum=3,maximum=20)
    payload={'actor_id':actor['id'],'user_id':positive_id(identifier,'user identifier'),'action':action,'confirmation':confirmation}
    if action=='role':
        if type(data.get('administrator')) is not bool:raise ApiError('Choose an administrator role')
        payload['administrator']=data['administrator']
    if action=='password':payload['password']=text(data.get('password'),name='Password',minimum=8,maximum=72)
    return internal().request('admin_user_change',payload)


@blueprint.get('/admin/instances')
def instances():
    actor=require_admin()
    page,_,_=pagination(25)
    data={'actor_id':actor['id'],'page':page,
          'search':text(request.args.get('search',''),name='Search',maximum=100),
          'state':choice(request.args.get('state','all'),('all','PROVISIONING','READY','ASSIGNED','ACTIVE','EXPIRED','TERMINATING'),'instance state')}
    if 'template_id' in request.args:data['template_id']=positive_id(request.args['template_id'],'exercise identifier')
    return internal().request('admin_instances',data)


def expected(data):
    import re
    value=data.get('expected')
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise ApiError('Review the action before confirming')
    return value


@blueprint.get('/admin/instances/<identifier>/preview')
def preview(identifier):
    actor=require_admin()
    action=choice(request.args.get('action'),('release','rebuild','remove','start','shutdown','reboot'),'instance action')
    data={'actor_id':actor['id'],'instance_id':positive_id(identifier,'instance identifier'),'action':action}
    if 'machine_id' in request.args:data['machine_id']=positive_id(request.args['machine_id'],'machine identifier')
    return internal().request('admin_preview',data)


@blueprint.post('/admin/instances/<identifier>/machines/<machine_id>')
def manage_machine(identifier,machine_id):
    actor=require_admin();rate_limit('admin-vms',str(actor['id']),20)
    data=body()
    return internal().request('admin_vm_change',{'actor_id':actor['id'],'instance_id':positive_id(identifier,'instance identifier'),
        'machine_id':positive_id(machine_id,'machine identifier'),'action':choice(data.get('action'),('start','shutdown','reboot'),'VM action'),'expected':expected(data)})


@blueprint.get('/admin/monitoring/activity')
def activity():
    actor=require_admin()
    rate_limit('admin-activity',str(actor['id']),30)
    data={'actor_id':actor['id']}
    if 'instance_id' in request.args:data['instance_id']=positive_id(request.args['instance_id'],'instance identifier')
    return internal().request('admin_activity',data)


@blueprint.route('/admin/instances/<identifier>',methods=['GET','POST'])
def manage_instance(identifier):
    actor=require_admin()
    payload={'actor_id':actor['id'],'instance_id':positive_id(identifier,'instance identifier')}
    if request.method=='POST':
        rate_limit('admin-instances',str(actor['id']),20)
        data=body()
        payload['action']=choice(data.get('action'),('release','rebuild','remove'),'instance action')
        payload['expected']=expected(data)
    return internal().request('admin_instance_change' if request.method=='POST' else 'admin_instance',payload)


@blueprint.get('/admin/jobs')
def jobs():
    actor=require_admin()
    page,_,_=pagination(25)
    state=choice(request.args.get('state','all'),('all','QUEUED','RUNNING','NEEDS_REVIEW','SUCCEEDED','REJECTED','RESOLVED','UNAVAILABLE','CANCELLED'),'operation state')
    return internal().request('admin_jobs',{'actor_id':actor['id'],'page':page,'state':state})


@blueprint.get('/admin/jobs/<scope>/<resource>')
def history(scope,resource):
    actor=require_admin()
    return internal().request('admin_job_history',{'actor_id':actor['id'],'scope':choice(scope,('user','template','pool','artifact','instance'),'operation scope'),
                                                'resource':positive_id(resource,'resource identifier')})


@blueprint.post('/admin/jobs/<identifier>/cancel')
def cancel_job(identifier):
    import re
    actor=require_admin();rate_limit('admin-job-cancel',str(actor['id']),20)
    if not re.fullmatch('[a-f0-9]{32}',identifier):raise ApiError('Invalid operation identifier')
    return internal().request('admin_job_cancel',{'actor_id':actor['id'],'job_id':identifier})


@blueprint.post('/admin/jobs/<identifier>/resolve')
def resolve_job(identifier):
    import re
    actor=require_admin();rate_limit('admin-job-resolve',str(actor['id']),10)
    if not re.fullmatch('[a-f0-9]{32}',identifier):raise ApiError('Invalid operation identifier')
    data=body()
    return internal().request('admin_job_resolve',{'actor_id':actor['id'],'job_id':identifier,
        'reason':text(data.get('reason'),name='Recovery checks',minimum=10,maximum=500),
        'confirmation':text(data.get('confirmation'),name='Operation ID',minimum=32,maximum=32)})
