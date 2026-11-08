"""Unprivileged Flask browser API. Creating an app performs no provisioning."""
from datetime import datetime, timezone
import os
import re

from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from heist.config import DatabaseSettings
from heist import legal
from heist.security.passwords import hash_password
from .errors import ApiError
from .repository import Repository


def create_app(config=None, *, repository_factory=None, internal_client_factory=None, clock=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(WEB_SESSION_SECRET=os.environ.get('WEB_SESSION_SECRET'), REGISTRATION_ENABLED=os.environ.get('HEIST_REGISTRATION_ENABLED','true')=='true',
                      LECTURE_SIGNUP_TOKEN=os.environ.get('LECTURE_SIGNUP_TOKEN',''),
                      IMPRINT_URL=os.environ.get('HEIST_IMPRINT_URL',legal.IMPRINT_URL),PRIVACY_URL=os.environ.get('HEIST_PRIVACY_URL',legal.PRIVACY_URL),
                      TERMS_URL=os.environ.get('HEIST_TERMS_URL',legal.TERMS_URL),
                      LEGAL_VERSION=os.environ.get('HEIST_LEGAL_VERSION',legal.LEGAL_VERSION),
                      DATA_ROOT=os.environ.get('HEIST_WEB_DATA_ROOT', '/var/lib/heist-web'),
                      MAINTENANCE_FILE=os.environ.get('HEIST_WEB_MAINTENANCE_FILE','/run/heist-web-maintenance'),
                      MAX_CONTENT_LENGTH=1024**3+1024**2, MAX_FORM_MEMORY_SIZE=1024**2, MAX_FORM_PARTS=100)
    app.config.update(config or {})
    secret = app.config['WEB_SESSION_SECRET']
    if not isinstance(secret, str) or not re.fullmatch('[a-fA-F0-9]{64}', secret):
        raise ValueError('Configure a persistent WEB_SESSION_SECRET before starting the web service')
    if repository_factory is None:
        settings = DatabaseSettings.from_mapping(timeout=3)
        if settings.user in ('postgres', 'root'):
            raise ValueError('The public web API requires a restricted application database role')
        repository_factory = lambda: Repository(settings.connect)
    if internal_client_factory is None:
        from .internal_client import InternalClient
        internal_client_factory = InternalClient.from_environment
    app.extensions['internal_client_factory'] = internal_client_factory
    app.extensions['repository_factory'] = repository_factory
    app.extensions['clock'] = clock or (lambda: datetime.now(timezone.utc))
    app.extensions['dummy_password_hash'] = hash_password('non-account-timing-placeholder')
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    from . import administration, artifacts, auth, authoring, challenges, context, health, learning, media, profiles
    app.register_blueprint(health.blueprint,url_prefix='/api')
    app.register_blueprint(auth.blueprint, url_prefix='/api')
    app.register_blueprint(learning.blueprint, url_prefix='/api')
    app.register_blueprint(media.blueprint, url_prefix='/api')
    app.register_blueprint(profiles.blueprint, url_prefix='/api')
    app.register_blueprint(challenges.blueprint, url_prefix='/api')
    app.register_blueprint(administration.blueprint, url_prefix='/api')
    app.register_blueprint(authoring.blueprint, url_prefix='/api')
    app.register_blueprint(artifacts.blueprint, url_prefix='/api')
    app.before_request(context.initialize_request)
    app.after_request(context.finish_request)
    app.teardown_appcontext(context.close_request)

    @app.errorhandler(ApiError)
    def api_error(error):
        return {'success': False, 'message': error.message}, error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: 'Invalid request', 403: 'Request not permitted', 404: 'Not found', 405: 'Method not allowed', 413: 'Request is too large'}
        return {'success': False, 'message': messages.get(error.code, 'Request could not be processed')}, error.code

    @app.errorhandler(Exception)
    def unavailable(error):
        app.logger.error('Public API request failed: %s', type(error).__name__)
        return {'success': False, 'message': 'The service is temporarily unavailable. Please retry.'}, 503

    return app
