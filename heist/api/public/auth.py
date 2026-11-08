"""Browser authentication contracts with revocable sessions and legacy hash upgrades."""
import re
import hmac
from flask import Blueprint, current_app, g, request

from heist.security.passwords import hash_password, needs_rehash, verify_password
from .context import body, rate_limit, repository, require_user, rotate_session, sessions
from .errors import ApiError
from .registration import legal_settings, registration_enabled

blueprint = Blueprint('authentication', __name__)


def encoded_password(password, *, enforce_policy=True):
    try:
        return hash_password(password, enforce_policy=enforce_policy)
    except ValueError as error:
        raise ApiError(str(error)) from None


def credentials(value):
    username, password = value.get('username'), value.get('password')
    if not isinstance(username, str) or not re.fullmatch('[A-Za-z0-9_]{3,20}', username):
        raise ApiError('Invalid username or password', 401)
    if not isinstance(password, str) or not 1 <= len(password) <= 72:
        raise ApiError('Invalid username or password', 401)
    return username, password


def auth_record(username, password):
    record = repository().call('web_auth_record', username, one=True)
    if record is None:
        verify_password(current_app.extensions['dummy_password_hash'], password)
        raise ApiError('Invalid username or password', 401)
    valid = verify_password(record['password_hash'], password, record['password_salt'])
    if needs_rehash(record['password_hash']) and not valid:
        verify_password(current_app.extensions['dummy_password_hash'], password)
    if not valid:
        raise ApiError('Invalid username or password', 401)
    return record


def user_result():
    from .media import public_url
    if not g.user:
        return None
    return {'username': g.user['username'], 'avatar_url': public_url(g.user.get('avatar_url', '/assets/avatars/avatar1.png')),
            'is_admin': g.user.get('is_admin') is True}


@blueprint.get('/site')
def site_settings():
    return {'success':True,'data':{'registration_enabled':registration_enabled(current_app.config),
                                  'legal':legal_settings(current_app.config)}}


@blueprint.get('/session')
def bootstrap():
    if not g.web_session:
        rate_limit('guest-session', request.remote_addr or 'unknown', 120, 300)
        rotate_session()
    return {'success': True, 'data': {'is_logged_in': g.user is not None, 'user': user_result(),
            'requires_password_change': bool(g.user and g.user.get('password_reset')),
            'csrf_token': sessions().csrf(g.raw_session),
            'registration_enabled': registration_enabled(current_app.config),
            'legal': legal_settings(current_app.config)}}


@blueprint.post('/login')
def login():
    value = body()
    rate_limit('login-ip', request.remote_addr or 'unknown', 30)
    username, password = credentials(value)
    rate_limit('login-account', username.lower(), 20)
    record = auth_record(username, password)
    if needs_rehash(record['password_hash']):
        repository().call('web_password_replace', record['id'], record['password_hash'], encoded_password(password, enforce_policy=False), '', False)
    repository().call('update_last_login', record['id'])
    rotate_session(record)
    return {'success': True, 'csrf_token': sessions().csrf(g.raw_session),
            'redirect': '/reset-password' if record.get('password_reset') else '/dashboard'}


@blueprint.post('/logout')
def logout():
    sessions().revoke(g.raw_session)
    g.raw_session = None
    g.web_session = None
    g.user = None
    g.session_cookie = True
    return {'success': True, 'message': 'Signed out', 'redirect': '/login'}


@blueprint.post('/signup')
def signup():
    if not registration_enabled(current_app.config):
        raise ApiError('Registration is currently closed', 403)
    rate_limit('signup-ip', request.remote_addr or 'unknown', 5, 3600)
    value = body()
    supplied = value.get('lecture_token')
    if not isinstance(supplied,str) or len(supplied)>256 or not hmac.compare_digest(supplied.encode(),current_app.config['LECTURE_SIGNUP_TOKEN'].encode()):
        raise ApiError('Invalid lecture code',403)
    legal = legal_settings(current_app.config)
    accepted = value.get('accept_legal')
    if accepted is not True and accepted != 'true':
        raise ApiError('Accept the Terms of Service and privacy policy to register')
    if value.get('legal_version') != legal['version']:
        raise ApiError('The registration policies changed. Reload the page and review them.',409)
    username, password = credentials(value)
    email = value.get('email')
    if not isinstance(email, str) or len(email) > 255 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise ApiError('Enter a valid email address')
    if value.get('confirm-password') != password:
        raise ApiError('The passwords do not match')
    encoded = encoded_password(password)
    from psycopg2.errors import UniqueViolation
    try:
        repo = repository()
        with repo.transaction():
            created = repo.call('create_user', username, email, encoded, '', request.remote_addr, one=True)
            repo.call('web_record_registration',created['id'],legal['version'],legal['imprint_url'],legal['privacy_url'],legal['terms_url'])
    except UniqueViolation:
        raise ApiError('Username or email is unavailable', 409) from None
    record = repository().call('web_user_identity', created['id'], one=True)
    rotate_session(record)
    return {'success': True, 'csrf_token': sessions().csrf(g.raw_session), 'redirect': '/dashboard'}


@blueprint.post('/reset-password')
def reset_password():
    user = require_user(allow_reset=True)
    return change_password(user, body())


def change_password(user, value):
    rate_limit('password-change', str(user['id']), 10)
    current, new, confirm = value.get('current_password'), value.get('new_password'), value.get('confirm_password')
    if not isinstance(current, str) or not 1 <= len(current) <= 72:
        raise ApiError('Enter your current password')
    if new != confirm:
        raise ApiError('The passwords do not match')
    record = auth_record(user['username'], current)
    if record.get('password_reset') and not record.get('reset_valid'):
        raise ApiError('Your reset window expired. Ask your tutor to reset your account.', 403)
    encoded = encoded_password(new)
    repository().call('web_password_replace', user['id'], record['password_hash'], encoded, '', True)
    updated = repository().call('web_user_identity', user['id'], one=True)
    rotate_session(updated)
    return {'success': True, 'message': 'Password changed', 'csrf_token': sessions().csrf(g.raw_session), 'redirect': '/dashboard'}
