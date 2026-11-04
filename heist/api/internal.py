"""Authenticated internal API with injectable infrastructure and no import side effects."""
import hmac
import importlib
import os
from contextlib import nullcontext
from pathlib import Path
from heist.environment import load_backend_env as load_dotenv
from flask import Flask, redirect, request, send_file
from heist.infrastructure.locking import OperationBusy, operation_guard
from heist.runtime import cleanup_is_complete


def create_app(config=None, services=None):
    application = Flask(__name__)
    application.config.update(BACKEND_AUTHENTICATION_TOKEN=os.getenv('BACKEND_AUTHENTICATION_TOKEN'),
                              TEMPLATE_LOCK_DIRECTORY=os.getenv('HEIST_TEMPLATE_LOCK_DIRECTORY', '/run/heist-template-operations'),
                              CLEANUP_FILE=os.getenv('HEIST_CLEANUP_FILE', '/var/lock/cleanup_complete.lock'),
                              MAX_CONTENT_LENGTH=65536, MAINTENANCE_FILE=os.getenv('HEIST_MAINTENANCE_FILE', '/run/heist-maintenance'))
    application.config.update(config or {})
    services = services or {}

    service_modules = {'launch_challenge': 'heist.platform.challenges.launch', 'stop_challenge': 'heist.platform.challenges.stop', 'import_machine_templates': 'heist.platform.images.import_templates', 'delete_machine_templates': 'heist.platform.images.delete_templates', 'get_user_config': 'heist.platform.users.vpn_config', 'delete_user_config': 'heist.platform.users.delete_vpn'}

    def service(name):
        return services[name] if name in services else getattr(importlib.import_module(service_modules[name]), name)

    def connection():
        if 'get_db_connection' in services:
            return services['get_db_connection']()
        from heist.config import DatabaseSettings
        return DatabaseSettings.from_mapping(timeout=3).connect()

    @application.before_request
    def authenticate():
        if not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=307)
        expected = application.config['BACKEND_AUTHENTICATION_TOKEN']
        supplied = request.headers.get('Authentication-Token', '')
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return {'error': 'Unauthorized', 'success': False}, 401
        if request.method == 'POST' and Path(application.config['MAINTENANCE_FILE']).exists():
            return {'error': 'Maintenance in progress', 'success': False}, 503
        if request.path == '/launch-challenge' and not cleanup_is_complete(application.config['CLEANUP_FILE']):
            return {'error': 'Startup cleanup requires reconciliation', 'success': False}, 503

    @application.errorhandler(413)
    def too_large(_error):
        return {'error': 'Request body too large', 'success': False}, 413

    def identifiers(*names):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('JSON object required')
        result = []
        for name in names:
            value = data.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError('Positive integer required')
            if not str(value).isascii() or not str(value).isdigit() or not 0 < int(value) < 2**63:
                raise ValueError('Positive integer required')
            result.append(int(value))
        return result

    def action(name, fields, message, database=False, download=False):
        try:
            values = identifiers(*fields)
        except ValueError:
            return {'error': 'Invalid input data', 'success': False}, 400
        db = None
        try:
            if database:
                db = connection()
                values.append(db)
            if name == 'launch_challenge':
                values += [os.getenv('MONITORING_VPN_INTERFACE', 'ctf_monitoring'),
                           os.getenv('MONITORING_DMZ_INTERFACE', 'dmz_monitoring')]
            elif name == 'import_machine_templates':
                from heist.infrastructure.network.cloud_init_pool import ip_pool
                values.append(ip_pool)
            guard = operation_guard(application.config['TEMPLATE_LOCK_DIRECTORY'], values[0], shared=name == 'launch_challenge') if name in ('launch_challenge', 'import_machine_templates', 'delete_machine_templates') else nullcontext()
            with guard:
                result = service(name)(*values)
            if download:
                return send_file(result, as_attachment=True)
            response = {'message': message, 'success': True}
            if name == 'launch_challenge':
                response['entrypoints'] = result
            return response, 200
        except OperationBusy:
            return {'error': 'An exercise image operation is still running', 'success': False}, 409
        except Exception:
            application.logger.exception('Backend action failed: %s', name)
            return {'error': 'Backend operation failed', 'success': False}, 500
        finally:
            if db is not None:
                db.close()

    @application.get('/health/live')
    def live():
        return {'success': True, 'status': 'alive'}, 200

    @application.get('/health/ready')
    def ready():
        if not cleanup_is_complete(application.config['CLEANUP_FILE']):
            return {'success': False, 'status': 'cleanup pending'}, 503
        db = None
        try:
            db = connection()
            with db.cursor() as cursor:
                cursor.execute('SELECT 1')
                if cursor.fetchone() != (1,):
                    raise RuntimeError('Unexpected readiness result')
            return {'success': True, 'status': 'ready'}, 200
        except Exception:
            application.logger.exception('Database readiness check failed')
            return {'success': False, 'status': 'not ready'}, 503
        finally:
            if db is not None:
                db.close()

    @application.get('/admin/operations')
    def operations():
        from heist.platform.operations import collect
        return {'success': True, 'data': collect(connection, os.environ, application.config['MAINTENANCE_FILE'])}, 200

    routes = [
        ('launch-challenge', 'launch_challenge', ('challenge_template_id', 'user_id'), 'Challenge launched', False, False),
        ('stop-challenge', 'stop_challenge', ('user_id',), 'Challenge stopped', False, False),
        ('import-machine-templates', 'import_machine_templates', ('challenge_template_id',), 'Machine template imported', True, False),
        ('delete-machine-templates', 'delete_machine_templates', ('challenge_id',), 'Machine templates deleted', True, False),
        ('get-user-config', 'get_user_config', ('user_id',), '', True, True),
        ('delete-user-config', 'delete_user_config', ('user_id',), 'User config deleted', False, False),
    ]
    for route, name, fields, message, database, download in routes:
        def handler(name=name, fields=fields, message=message, database=database, download=download):
            return action(name, fields, message, database, download)
        application.add_url_rule('/' + route, name, handler, methods=['POST'])
    return application


load_dotenv()
app = create_app()

if __name__ == '__main__':
    app.run(host=os.getenv('BACKEND_HOST', '10.0.0.1'), port=int(os.getenv('BACKEND_PORT', '8000')),
            ssl_context=(os.getenv('BACKEND_CERTIFICATE_FILE', '/root/heiST/backend.crt'),
                         os.getenv('BACKEND_CERTIFICATE_KEY_FILE', '/root/heiST/backend.key')))
