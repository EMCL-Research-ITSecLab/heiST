"""Authenticated host intake; only generated identities, never browser filesystem paths."""
import subprocess

from flask import Blueprint, current_app, request

from heist.artifacts.ova import InvalidOva
from heist.artifacts.uploads import UploadError, UploadStore
from heist.platform.images import intake
from heist.platform.jobs.journal import Journal, RecoveryRequired, RejectedOperation
from heist.files import write_json


def blueprint(connection):
    routes = Blueprint('artifact_intake', __name__)

    def store():
        return UploadStore(current_app.config['ARTIFACT_INTAKE_DIRECTORY'])

    def payload():
        request.max_content_length = 65536
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise UploadError('JSON object required')
        return value

    @routes.errorhandler(RejectedOperation)
    @routes.errorhandler(UploadError)
    @routes.errorhandler(intake.ImageConflict)
    def conflict(error):
        return {'success': False, 'code': 'image_conflict', 'message': str(error)}, 409

    @routes.errorhandler(InvalidOva)
    def invalid(_error):
        return {'success': False, 'code': 'invalid_image', 'message': 'The image failed bounded disk validation'}, 422

    @routes.errorhandler(BlockingIOError)
    @routes.errorhandler(RecoveryRequired)
    def busy(_error):
        return {'success': False, 'code': 'busy', 'message': 'Image operation is running or requires reconciliation'}, 409

    @routes.route('/artifacts/<int:owner>/<identifier>', methods=['GET','POST'])
    def transfer(owner,identifier):
        if not 0 < owner < 2**63:
            raise UploadError('Invalid owner')
        uploads = store()
        if request.method == 'GET':
            return {'success': True, 'data': uploads.status(owner,identifier)}
        value = payload()
        db = connection()
        try:
            intake.require_admin(db,owner)
            result = uploads.create(owner,value.get('name'),value.get('size'),value.get('guest_os'),identifier=identifier)
            return {'success': True, 'data': result}
        finally:
            db.close()

    @routes.put('/artifacts/<int:owner>/<identifier>/chunks/<int:index>')
    def chunk(owner,identifier,index):
        if request.mimetype != 'application/octet-stream':
            raise UploadError('Chunks require binary content')
        request.max_content_length = UploadStore.CHUNK_BYTES
        return {'success': True, 'data': store().put(owner,identifier,index,request.stream)}

    @routes.post('/artifacts/<int:owner>/<identifier>/seal')
    def seal(owner,identifier):
        return {'success': True, 'data': store().seal(owner,identifier)}

    @routes.post('/artifacts/<int:owner>/<identifier>/publish')
    def publish(owner,identifier):
        value = payload()
        db = connection()
        try:
            uploads=store()
            try:
                result = intake.publish(db,uploads,owner,identifier,value.get('sha256'),
                                        import_directory=current_app.config['ARTIFACT_LIBRARY_DIRECTORY'],
                                        cache=current_app.config['NORMALIZED_IMAGE_DIRECTORY'])
            except (InvalidOva,subprocess.CalledProcessError,subprocess.TimeoutExpired,intake.ImageConflict) as error:
                with uploads.session(owner,identifier) as (directory,metadata):
                    if metadata['state']!='READY':
                        metadata.update(state='FAILED',message='Image validation or registration was rejected')
                        write_json(directory/'metadata.json',metadata)
                if isinstance(error,intake.ImageConflict):
                    raise
                raise InvalidOva('Image validation failed') from None
            return {'success': True, 'data': result}
        finally:
            db.close()

    @routes.post('/artifacts/retire')
    def retire():
        value = payload()
        owner, identifier = value.get('user_id'), value.get('artifact_id')
        if any(type(item) is not int or not 0 < item < 2**63 for item in (owner,identifier)):
            raise UploadError('Invalid image identity')
        journal = Journal(current_app.config['OPERATION_DIRECTORY'])
        operation_id = Journal.request_id(request.headers.get('Idempotency-Key'))
        db = connection()
        try:
            result = journal.execute('artifact',identifier,'retire_image',value,
                lambda: intake.retire(db,identifier,owner,import_directory=current_app.config['ARTIFACT_LIBRARY_DIRECTORY']),request_id=operation_id)
            return {'success': True, 'data': result}
        finally:
            db.close()

    return routes
