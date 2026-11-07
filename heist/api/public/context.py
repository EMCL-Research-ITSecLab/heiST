"""Request-scoped resources and server-side authorization for the browser API."""
import hashlib
import json
from pathlib import Path

from flask import current_app, g, request

from heist.security.sessions import Sessions
from .errors import ApiError


def repository():
    if 'web_repository' not in g:
        g.web_repository = current_app.extensions['repository_factory']()
    return g.web_repository


def internal():
    if 'internal_client' not in g:
        g.internal_client = current_app.extensions['internal_client_factory']()
    return g.internal_client


def sessions():
    if 'web_sessions' not in g:
        g.web_sessions = Sessions(repository(), current_app.config['WEB_SESSION_SECRET'], clock=current_app.extensions['clock'])
    return g.web_sessions


def body():
    if 'web_body' in g:
        return g.web_body
    request.max_content_length = 65536
    if request.content_length and request.content_length > 65536:
        raise ApiError('Request is too large', 413)
    if request.is_json:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON field')
                result[key] = value
            return result
        try:
            raw = request.stream.read(65537)
            if len(raw) > 65536:
                raise ApiError('Request is too large', 413)
            value = json.loads(raw, object_pairs_hook=unique_pairs)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ApiError('Invalid JSON object') from None
        if not isinstance(value, dict):
            raise ApiError('A JSON object is required')
        g.web_body = value
        return value
    if any(len(values) != 1 for _, values in request.form.lists()):
        raise ApiError('Duplicate form field')
    g.web_body = request.form.to_dict()
    return g.web_body


def require_user(*, allow_reset=False):
    user = getattr(g, 'user', None)
    if not user:
        raise ApiError('Please sign in', 401)
    if user.get('password_reset') and not allow_reset:
        raise ApiError('Change your password before continuing', 403)
    return user


def require_admin():
    user = require_user()
    if user.get('is_admin') is not True:
        raise ApiError('Administrator access required', 403)
    return user


def rate_limit(name, identity, limit, window=300):
    value = hashlib.sha256((name+':'+identity).encode()).hexdigest()
    if not repository().scalar('web_rate_limit', value, limit, window, current_app.extensions['clock']()):
        raise ApiError('Too many attempts. Please wait before trying again.', 429)


def rotate_session(user=None):
    g.raw_session = sessions().rotate(getattr(g, 'raw_session', None), user['id'] if user else None,
                                      user.get('auth_version', 0) if user else 0)
    g.session_cookie = True
    g.user = user
    g.web_session = {'user_id': user['id'] if user else None}


def initialize_request():
    g.user = None
    g.web_session = None
    g.raw_session = request.cookies.get('__Host-heist_session')
    g.session_cookie = False
    if not request.path.startswith('/api/'):
        return
    if not request.is_secure:
        raise ApiError('HTTPS is required', 400)
    if request.endpoint in ('health.live','health.ready','authentication.site_settings'):
        g.raw_session=None
        return
    if Path(current_app.config['MAINTENANCE_FILE']).exists():
        raise ApiError('Scheduled maintenance is in progress',503)
    if request.endpoint is None or request.endpoint == 'media.get_media':
        return
    if g.raw_session:
        g.web_session = sessions().load(g.raw_session)
        if g.web_session and g.web_session['user_id'] is not None:
            user = repository().call('web_user_identity', g.web_session['user_id'], one=True)
            if user and user['auth_version'] == g.web_session['auth_version']:
                g.user = user
            else:
                sessions().revoke(g.raw_session)
                g.web_session = None
        if not g.web_session:
            g.session_cookie = True
            g.raw_session = None
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if origin is not None and origin != request.host_url.rstrip('/'):
            raise ApiError('Request origin is not permitted', 403)
        token = request.headers.get('X-CSRF-Token')
        if token is None and request.content_length is not None and request.content_length <= 65536:
            token = body().get('csrf_token')
        if not g.web_session or not sessions().valid_csrf(g.raw_session, token):
            raise ApiError('Your session token is missing or expired. Reload the page.', 403)
        if g.user:
            if not repository().scalar('web_user_mutation_lock', g.user['id']):
                raise ApiError('Another account operation is running. Wait for it to finish.', 409)
            # Authorization might have changed while this request was in flight.
            identity = repository().call('web_user_identity', g.user['id'], one=True)
            if not identity or identity['auth_version'] != g.web_session['auth_version']:
                raise ApiError('Your session changed. Please sign in again.', 401)
            g.user = identity


def finish_request(response):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Vary'] = 'Cookie'
    if request.endpoint == 'media.get_media' and response.status_code == 200:
        response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
        response.headers.pop('Vary', None)
    if getattr(g, 'raw_session', None) and getattr(g, 'web_session', None):
        response.set_cookie('__Host-heist_session', g.raw_session, max_age=3600, secure=True, httponly=True, samesite='Strict', path='/')
    elif getattr(g, 'session_cookie', False):
        response.delete_cookie('__Host-heist_session', secure=True, httponly=True, samesite='Strict', path='/')
    return response


def close_request(error=None):
    value = g.pop('web_repository', None)
    if value is not None:
        value.close()
    client = g.pop('internal_client', None)
    if client is not None:
        client.close()
