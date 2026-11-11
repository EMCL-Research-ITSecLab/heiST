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
from heist.platform.jobs.journal import Journal, RecoveryRequired


def create_app(config=None, services=None):
    application = Flask(__name__)
    application.config.update(BACKEND_AUTHENTICATION_TOKEN=os.getenv('BACKEND_AUTHENTICATION_TOKEN'),
                              TEMPLATE_LOCK_DIRECTORY=os.getenv('HEIST_TEMPLATE_LOCK_DIRECTORY', '/run/heist-template-operations'),
                              CLEANUP_FILE=os.getenv('HEIST_CLEANUP_FILE', '/var/lock/cleanup_complete.lock'),
                              OPERATION_DIRECTORY=os.getenv('HEIST_OPERATION_DIRECTORY', '/var/lib/heist/operations'),
                              ARTIFACT_INTAKE_DIRECTORY=os.getenv('HEIST_ARTIFACT_INTAKE', '/var/lib/heist/artifact-intake'),
                              ARTIFACT_LIBRARY_DIRECTORY=os.getenv('HEIST_ARTIFACT_LIBRARY', '/var/lib/vz/import'),
                              NORMALIZED_IMAGE_DIRECTORY=os.getenv('HEIST_NORMALIZED_IMAGES', '/var/lib/heist/normalized-images'),
                              MAX_CONTENT_LENGTH=4*1024**2, MAINTENANCE_FILE=os.getenv('HEIST_MAINTENANCE_FILE', '/run/heist-maintenance'))
    application.config.update(config or {})
    services = services or {}

    service_modules = {'launch_challenge': 'heist.platform.challenges.launch', 'stop_challenge': 'heist.platform.challenges.stop', 'import_machine_templates': 'heist.platform.images.import_templates', 'delete_machine_templates': 'heist.platform.images.delete_templates', 'get_user_config': 'heist.platform.users.vpn_config', 'delete_user_config': 'heist.platform.users.delete_vpn', 'teardown_challenge':'heist.platform.challenges.teardown'}

    def service(name):
        return services[name] if name in services else getattr(importlib.import_module(service_modules[name]), name)

    def connection():
        if 'get_db_connection' in services:
            return services['get_db_connection']()
        from heist.config import DatabaseSettings
        return DatabaseSettings.from_mapping(timeout=3).connect(autocommit=True)

    @application.before_request
    def authenticate():
        if not request.is_secure:
            return redirect(request.url.replace('http://', 'https://', 1), code=307)
        expected = application.config['BACKEND_AUTHENTICATION_TOKEN']
        supplied = request.headers.get('Authentication-Token', '')
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            return {'error': 'Unauthorized', 'success': False}, 401
        if request.method in ('POST','PUT','DELETE') and Path(application.config['MAINTENANCE_FILE']).exists():
            return {'error': 'Maintenance in progress', 'success': False}, 503
        if request.path == '/launch-challenge' and not cleanup_is_complete(application.config['CLEANUP_FILE']):
            return {'error': 'Startup cleanup requires reconciliation', 'success': False}, 503

    @application.errorhandler(413)
    def too_large(_error):
        return {'error': 'Request body too large', 'success': False}, 413

    def identifiers(*names):
        request.max_content_length = 65536
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
            operation_id = Journal.request_id(request.headers.get('Idempotency-Key'))
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
                if name in ('launch_challenge', 'stop_challenge', 'import_machine_templates', 'delete_machine_templates'):
                    scope = 'user' if name in ('launch_challenge', 'stop_challenge') else 'template'
                    identifier = values[1] if name == 'launch_challenge' else values[0]
                    journal = Journal(application.config['OPERATION_DIRECTORY'])
                    result = journal.execute(scope, identifier, name, request.get_json(),
                                             lambda: service(name)(*values), request_id=operation_id)
                else:
                    result = service(name)(*values)
            if download:
                return send_file(result, as_attachment=True)
            response = {'message': message, 'success': True}
            if name == 'launch_challenge':
                response['entrypoints'] = result
            return response, 200
        except (OperationBusy, BlockingIOError, RecoveryRequired):
            return {'error': 'An operation is running or requires reconciliation; inspect before retrying', 'success': False}, 409
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

    def administrator_service():
        from heist.platform.administration import Administration
        return Administration(connection,Journal(application.config['OPERATION_DIRECTORY']),
            status=services.get('vm_status'),vm_control=services.get('vm_control'),
            stop=lambda *args,**kwargs:service('stop_challenge')(*args,**kwargs),
            teardown=lambda *args,**kwargs:service('teardown_challenge')(*args,**kwargs),
            launch=lambda template,user:service('launch_challenge')(template,user,
                os.getenv('MONITORING_VPN_INTERFACE','ctf_monitoring'),os.getenv('MONITORING_DMZ_INTERFACE','dmz_monitoring')))
    from heist.api.administration import blueprint as administrator_routes
    application.extensions['administrator_service']=administrator_service
    application.register_blueprint(administrator_routes(administrator_service))

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
    @application.post('/admin/challenges/parse-yaml')
    def parse_challenge_yaml():
        from heist.platform.challenges.yaml_definition import parse_yaml
        from heist.platform.challenges.definition import DefinitionError
        request.max_content_length = 2*1024**2
        value = request.get_json(silent=True)
        try:
            return {'success':True,'data':parse_yaml(value.get('yaml') if isinstance(value,dict) else None)}
        except DefinitionError as error:
            return {'success':False,'error':str(error)},400

    from heist.api.artifact_intake import blueprint as artifact_blueprint
    application.register_blueprint(artifact_blueprint(connection))
    return application


load_dotenv()
app = create_app()

if __name__ == '__main__':
    from heist.api.internal_serve import main
    raise SystemExit(main())
