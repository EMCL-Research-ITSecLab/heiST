"""Account profiles. Identity comes exclusively from the authenticated session."""
import re

from flask import Blueprint, Response, request
from psycopg2.errors import UniqueViolation

from . import auth
from .context import body, internal, rate_limit, repository, require_user
from .errors import ApiError
from .media import MAX_BYTES, remove_owned_image, save_image
from .validation import choice, email, text, username, website

blueprint = Blueprint('profiles', __name__)


def basic_profile(user_id, *, public=False):
    value = repository().call('get_public_profile_data' if public else 'get_basic_profile_data', user_id, one=True)
    if value is None:
        raise ApiError('Profile not found', 404)
    value['join_date'] = value['created_at']
    value['rank'] = repository().scalar('get_user_rank', user_id, value['total_points'])
    return value


def profile_stats(user_id):
    value = repository().call('get_profile_stats', user_id, one=True)
    categories = [item['category'] for item in repository().call('get_all_challenge_categories')]
    totals = {item['category']: item['total'] for item in repository().call('get_challenge_count_by_categories')}
    solved = {item['category']: item['solved'] for item in repository().call('get_user_solved_challenge_count_by_categories', user_id)}
    return {**value, 'solved_count': value['solved'], 'total_solved': value['solved'],
            'total_attempts': value['attempts'], 'categories': categories,
            'solved_counts': [solved.get(category, 0) for category in categories],
            'percentages': [round(solved.get(category, 0)/totals[category]*100) if totals.get(category) else 0 for category in categories],
            'success_rate': round(value['solved']/value['attempts']*100) if value['attempts'] else 0}


def profile_data(user_id, *, public=False, section='full'):
    loaders = {'basic': lambda: basic_profile(user_id, public=public),
               'stats': lambda: profile_stats(user_id),
               'badges': lambda: repository().call('get_profile_badges', user_id),
               'activity': lambda: repository().call('get_recent_activity', user_id, 5)}
    if section != 'full':
        return loaders[section]()
    result = {key: load() for key, load in loaders.items()}
    result['stats']['rank'] = result['basic']['rank']
    if public:
        result['profile'] = result.pop('basic')
    return result


@blueprint.get('/profile')
def get_profile():
    user = require_user()
    section = choice(request.args.get('type', 'full'), ('full', 'basic', 'stats', 'badges', 'activity'), 'profile section')
    return {'success': True, 'data': profile_data(user['id'], section=section)}


@blueprint.get('/profiles/<requested_username>')
def public_profile(requested_username):
    require_user()
    name = username(requested_username)
    user_id = repository().scalar('get_id_by_username', name)
    if user_id is None:
        raise ApiError('Profile not found', 404)
    return {'success': True, 'data': profile_data(user_id, public=True)}


def update_avatar(user, value, upload=None):
    old = repository().scalar('get_user_avatar', user['id'])
    if upload is not None:
        url = save_image(upload, 'avatars', user['id'])
    else:
        selected = choice(value.get('avatar'), ('avatar1', 'avatar2', 'avatar3'), 'avatar selection')
        url = '/assets/avatars/'+selected+'.png'
    try:
        repository().call('update_user_avatar', user['id'], url)
    except BaseException:
        remove_owned_image(url, 'avatars', user['id'])
        raise
    # A cleanup failure must not turn a committed update into a failed response.
    try:
        remove_owned_image(old, 'avatars', user['id'])
    except OSError:
        from flask import current_app
        current_app.logger.warning('Previous avatar cleanup deferred')
    return {'success': True, 'message': 'Avatar updated', 'avatar_url': url}


@blueprint.post('/profile')
def update_profile():
    user = require_user()
    rate_limit('profile-update', str(user['id']), 60)
    if request.mimetype == 'multipart/form-data':
        request.max_content_length = MAX_BYTES+65536
        if any(len(values) != 1 for _, values in request.form.lists()) or any(len(values) != 1 for _, values in request.files.lists()):
            raise ApiError('Duplicate upload field')
        if request.form.get('action') != 'upload_avatar' or set(request.files) != {'avatar'}:
            raise ApiError('Choose an avatar image to upload')
        return update_avatar(user, {}, request.files['avatar'])
    value = body()
    action = value.get('action')
    if action == 'get_vpn_config':
        rate_limit('vpn-download', str(user['id']), 5)
        data = internal().request('vpn', {'user_id': user['id']}, download=True)
        filename = re.sub('[^A-Za-z0-9_]', '', user['username'])+'.ovpn'
        return Response(data, mimetype='application/octet-stream', headers={'Content-Disposition': 'attachment; filename="'+filename+'"'})
    if action == 'change_password':
        return auth.change_password(user, {**value, 'confirm_password': value.get('new_password')})
    if action == 'update_avatar':
        return update_avatar(user, value)
    try:
        if action == 'update_username':
            repository().call('update_username', user['id'], username(value.get('username')), request.remote_addr)
        elif action == 'update_email':
            repository().call('update_email', user['id'], email(value.get('email')), request.remote_addr)
        elif action == 'update_full_name':
            repository().call('update_full_name', user['id'], text(value.get('full_name'), name='Full name', maximum=30))
        elif action == 'update_bio':
            repository().call('update_bio', user['id'], text(value.get('bio'), name='Biography', maximum=500))
        elif action == 'update_social':
            repository().call('update_urls', user['id'], website(value.get('github', ''), 'GitHub URL'),
                              website(value.get('twitter', ''), 'Social URL'), website(value.get('website', '')))
        else:
            raise ApiError('Invalid profile action')
    except UniqueViolation:
        raise ApiError('Username or email is unavailable', 409) from None
    return {'success': True, 'message': 'Profile updated'}


@blueprint.delete('/profile')
def delete_profile():
    user = require_user()
    rate_limit('account-deletion', str(user['id']), 5, 3600)
    password = body().get('password')
    if not isinstance(password, str) or not 1 <= len(password) <= 72:
        raise ApiError('Enter your current password')
    record = auth.auth_record(user['username'], password)
    repo = repository()
    from psycopg2.errors import ObjectNotInPrerequisiteState
    messages = {'Transfer or delete your exercises and VM images before deleting your account',
                'Create another administrator before deleting your account',
                'Stop your running exercise before deleting your account'}
    try:
        repo.call('web_account_deletion_check', user['id'], record['password_hash'])
        avatar = repo.scalar('get_user_avatar', user['id'])
        if repo.scalar('get_user_running_challenge', user['id']) is not None:
            internal().request('stop', {'user_id': user['id']})
        # A failed revocation leaves the account and reserved IP intact. Do not
        # free the IP while an old VPN certificate/session could still use it.
        internal().request('delete_vpn', {'user_id': user['id']})
        repo.call('web_account_remove', user['id'], record['password_hash'], request.remote_addr)
    except ObjectNotInPrerequisiteState as error:
        if error.diag.message_primary in messages:
            raise ApiError(error.diag.message_primary, 409) from None
        raise
    try:
        remove_owned_image(avatar, 'avatars', user['id'])
    except OSError:
        from flask import current_app
        current_app.logger.warning('Deleted account avatar cleanup deferred')
    result = auth.logout()
    result.update(message='Account deleted', redirect='/landing')
    return result
