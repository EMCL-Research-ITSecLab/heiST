"""Exercise definition authoring and owner-scoped administrator management."""
import math

from flask import Blueprint, current_app, request

from heist.platform.challenges.definition import DefinitionError, definition, metadata
from .context import body, internal, rate_limit, repository, require_admin
from .errors import ApiError
from .learning import pagination
from .media import MAX_BYTES, remove_owned_image, save_image
from .validation import positive_id

blueprint = Blueprint('authoring', __name__)


def owned_template(user, identifier):
    identifier = positive_id(identifier, 'exercise identifier')
    value = repository().call('get_challenge_template_details', identifier, one=True)
    if value is None or value['creator_id'] != user['id']:
        raise ApiError('Exercise not found', 404)
    return value


@blueprint.post('/admin/challenges/import-yaml')
def import_yaml():
    user = require_admin()
    rate_limit('yaml-preview',user['id'],20,300)
    source = body().get('yaml')
    if not isinstance(source,str) or len(source.encode('utf-8',errors='replace')) > 256*1024:
        raise ApiError('YAML file must be at most 256 KiB')
    result = internal().request('parse_challenge_yaml',{'yaml':source})
    value = result.get('data')
    artifacts = repository().call('get_user_available_disk_files',user['id'])
    if not isinstance(value,dict):
        raise ApiError('Invalid YAML preview response',503)
    # Legacy YAML may omit the suffix used by the current upload library.
    names = {item['display_name'] for item in artifacts}
    for vm in value.get('vms',[]):
        name = vm.get('ova_name')
        if isinstance(name,str) and name not in names and name+'.ova' in names:
            vm['ova_name'] = name+'.ova'
    try:
        definition(value,artifacts)
    except DefinitionError as error:
        raise ApiError(str(error)) from None
    return {'success':True,'data':value}


@blueprint.get('/admin/challenges/options')
def options():
    user = require_admin()
    return {'success': True, 'ovas': [{**value, 'filename': value['display_name']} for value in repository().call('get_user_available_disk_files', user['id'])]}


@blueprint.get('/admin/challenges')
def challenges():
    user = require_admin()
    repo = repository()
    values = repo.call('get_challenge_templates_for_management', user['id'])
    return {'success': True, 'data': {'challenges': values, 'stats': {
        'total_challenges': len(values), 'active_challenges': sum(item['is_active'] and not item['marked_for_deletion'] for item in values),
        'active_deployments': repo.scalar('get_active_deployments_of_challenge_templates_by_user', user['id']),
        'total_deployments': repo.scalar('get_total_deployments_of_challenge_templates_by_user', user['id']),
        'avg_completion_minutes': repo.scalar('get_average_completion_time_of_challenge_templates_by_user', user['id'])}}}


def create_definition(user, value, cover):
    repo = repository()
    artifacts = repo.call('get_user_available_disk_files', user['id'])
    try:
        parsed = definition(value, artifacts)
    except DefinitionError as error:
        raise ApiError(str(error)) from None
    if repo.scalar('count_user_challenges_with_same_name', parsed['name'], user['id']):
        raise ApiError('You already have an exercise with this name', 409)
    image = save_image(cover, 'challenge_images', user['id']) if cover is not None and cover.filename else None
    try:
        with repo.transaction():
            identifier = repo.scalar('create_challenge_template', parsed['name'], parsed['description'], parsed['category'], parsed['difficulty'],
                                      image, False, user['id'], parsed['hint'], parsed['solution'])
            machines = {}
            for machine in parsed['machines']:
                machine_id = repo.scalar('create_machine_template', identifier, machine['name'], machine['disk_file_id'], machine['cores'], machine['ram_gb'], machine['ad_role'])
                machines[machine['name']] = machine_id
                repo.call('create_domain_template', machine_id, machine['domain_name'])
            for network in parsed['networks']:
                network_id = repo.scalar('create_network_template', network['name'], network['accessible'], network['dmz'], identifier)
                for name in network['attached_vms']:
                    repo.call('create_network_connection_template', machines[name], network_id)
            for flag in parsed['flags']:
                repo.call('create_challenge_flag', identifier, flag['flag'], flag['description'], flag['points'], flag['order_index'],
                          flag['user_specific'], machines.get(flag['vm_name']))
            for hint in parsed['hints']:
                repo.call('create_challenge_hint', identifier, hint['hint_text'], hint['unlock_points'], hint['order_index'])
    except BaseException:
        if image:
            remove_owned_image(image, 'challenge_images', user['id'])
        raise
    # After commit, infrastructure may already have changed even if HTTPS times
    # out. Preserve the inactive definition for reconciliation; never roll back
    # its IDs or delete partially imported machines on an ambiguous response.
    try:
        internal().request('import_templates', {'challenge_template_id': identifier})
        state = repo.call('web_template_state', identifier, one=True)
        if not state or not state['ready']:
            raise ApiError('Machine import readiness is not confirmed', 503)
    except ApiError:
        raise ApiError('Exercise '+str(identifier)+' was saved inactive. Check its machine import before retrying.', 503) from None
    repo.call('update_challenge_template', identifier, parsed['name'], parsed['description'], parsed['category'], parsed['difficulty'],
              parsed['hint'], parsed['solution'], parsed['is_active'])
    return {'success': True, 'message': 'Exercise created', 'id': identifier}, 201


@blueprint.post('/admin/challenges')
def create_challenge():
    user = require_admin()
    rate_limit('create-exercise', str(user['id']), 10, 3600)
    cover = None
    if request.mimetype == 'multipart/form-data':
        request.max_content_length = MAX_BYTES+65536
        if any(len(values) != 1 for _, values in request.form.lists()) or any(len(values) != 1 for _, values in request.files.lists()):
            raise ApiError('Duplicate exercise field')
        if set(request.files)-{'image'}:
            raise ApiError('Only an exercise cover image may be uploaded here')
        value, cover = request.form.to_dict(), request.files.get('image')
    else:
        value = body()
    return create_definition(user, value, cover)


@blueprint.put('/admin/challenges/<identifier>')
def update_challenge(identifier):
    user = require_admin()
    value = owned_template(user, identifier)
    if value['marked_for_deletion']:
        raise ApiError('Restore this exercise before editing it', 409)
    try:
        parsed = metadata(body())
    except DefinitionError as error:
        raise ApiError(str(error)) from None
    repo = repository()
    if parsed['name'].casefold() != value['name'].casefold() and repo.scalar('count_user_challenges_with_same_name', parsed['name'], user['id']):
        raise ApiError('You already have an exercise with this name', 409)
    state = repo.call('web_template_state', value['id'], one=True)
    if parsed['is_active'] and (not state or not state['ready']):
        raise ApiError('Confirm machine import readiness before publishing this exercise', 409)
    repo.call('update_challenge_template', value['id'], parsed['name'], parsed['description'], parsed['category'], parsed['difficulty'],
              parsed['hint'], parsed['solution'], parsed['is_active'])
    return {'success': True, 'message': 'Exercise updated'}


@blueprint.post('/admin/challenges/<identifier>/restore')
def restore(identifier):
    user = require_admin()
    value = owned_template(user, identifier)
    state = repository().call('web_template_state', value['id'], one=True)
    if not state or not state['ready']:
        raise ApiError('Machine templates need reconciliation before this exercise can be restored', 409)
    repository().call('restore_challenge_template', value['id'])
    return {'success': True, 'message': 'Exercise restored'}


@blueprint.get('/admin/challenges/<identifier>/leaderboard')
def leaderboard(identifier):
    user = require_admin()
    value = owned_template(user, identifier)
    page, size, offset = pagination(10)
    repo = repository()
    total = repo.scalar('get_total_leaderboard_entries_for_author', value['id'])
    return {'success': True, 'data': {'leaderboard': repo.call('get_challenge_leaderboard', value['id'], size, offset),
            'total': total, 'total_pages': max(1, math.ceil(total/size)), 'page': page}}


@blueprint.delete('/admin/challenges/<identifier>')
def delete_challenge(identifier):
    user = require_admin()
    value = owned_template(user, identifier)
    force = body().get('force', False)
    if not isinstance(force, bool):
        raise ApiError('Permanent deletion selection must be true or false')
    repo = repository()
    # Retirement is durable before infrastructure work. A failed operation must
    # never make a half-deleted exercise available to students again.
    repo.call('mark_challenge_template_for_soft_deletion', value['id'])
    if not force:
        return {'success': True, 'message': 'Exercise retired; existing instances can finish and grades are retained'}
    for instance in repo.call('get_running_instances_of_challenge_template', value['id']):
        internal().request('stop', {'user_id': instance['user_id']})
    internal().request('delete_templates', {'challenge_id': value['id']})
    state = repo.call('web_template_state', value['id'], one=True)
    if state and state['instances']:
        raise ApiError('Exercise retired. Instance teardown is not yet confirmed; inspect before retrying.', 503)
    with repo.transaction():
        repo.call('web_challenge_grade_lock', value['id'])
        repo.call('delete_challenge_template', value['id'])
    try:
        remove_owned_image(value['image_path'], 'challenge_images', user['id'])
    except OSError:
        current_app.logger.warning('Deleted exercise cover cleanup deferred')
    return {'success': True, 'message': 'Exercise permanently deleted'}
