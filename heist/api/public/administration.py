"""Administrator operations with explicit methods and server-refreshed roles."""
from flask import Blueprint, request

from .context import body, internal, rate_limit, repository, require_admin
from .errors import ApiError
from .learning import pagination
from .validation import choice, positive_id, text

blueprint = Blueprint('administration', __name__)
DIAGNOSTIC_FIELDS = ('checked_at', 'database', 'maintenance', 'lifecycle', 'services', 'archive', 'monitoring', 'release', 'source_version', 'storage')


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
    return internal().request('admin_instances',{'actor_id':actor['id'],'page':page})


@blueprint.route('/admin/instances/<identifier>',methods=['GET','POST'])
def manage_instance(identifier):
    actor=require_admin()
    payload={'actor_id':actor['id'],'instance_id':positive_id(identifier,'instance identifier')}
    if request.method=='POST':
        rate_limit('admin-instances',str(actor['id']),20)
        payload['action']=choice(body().get('action'),('release','rebuild','remove'),'instance action')
    return internal().request('admin_instance_change' if request.method=='POST' else 'admin_instance',payload)


@blueprint.get('/admin/jobs')
def jobs():
    actor=require_admin()
    page,_,_=pagination(25)
    state=choice(request.args.get('state','all'),('all','RUNNING','NEEDS_REVIEW','SUCCEEDED','REJECTED','RESOLVED','UNAVAILABLE'),'operation state')
    return internal().request('admin_jobs',{'actor_id':actor['id'],'page':page,'state':state})
