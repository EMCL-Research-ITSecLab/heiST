"""Administrator-only upload staging; sealed files are not published images."""
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, request

from heist.artifacts.uploads import UploadError, UploadStore
from .context import body, internal, rate_limit, repository, require_admin
from .errors import ApiError

blueprint = Blueprint('artifacts', __name__)


def staged_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        user = require_admin()
        store = UploadStore(Path(current_app.config['DATA_ROOT'])/'artifact-uploads')
        try:
            return function(store, user['id'], *args, **kwargs)
        except UploadError as error:
            raise ApiError(str(error)) from None
        except BlockingIOError:
            raise ApiError('This upload is busy; check its status before retrying', 409) from None
    return wrapped


@blueprint.post('/admin/artifact-uploads')
@staged_operation
def create(store, owner):
    rate_limit('artifact-upload', str(owner), 20, 3600)
    value = body()
    result = store.create(owner, value.get('name'), value.get('size'), value.get('guest_os'))
    return {'success': True, 'data': result}, 201


@blueprint.get('/admin/artifact-uploads/<identifier>')
@staged_operation
def status(store, owner, identifier):
    return {'success': True, 'data': store.status(owner, identifier)}


@blueprint.put('/admin/artifact-uploads/<identifier>/chunks/<int:index>')
@staged_operation
def chunk(store, owner, identifier, index):
    if request.mimetype != 'application/octet-stream':
        raise ApiError('Chunks require application/octet-stream', 415)
    request.max_content_length = store.CHUNK_BYTES
    return {'success': True, 'data': store.put(owner, identifier, index, request.stream)}


@blueprint.post('/admin/artifact-uploads/<identifier>/seal')
@staged_operation
def seal(store, owner, identifier):
    return {'success': True, 'data': store.seal(owner, identifier),
            'message': 'Transfer sealed in quarantine; disk validation and import are not complete'}, 202


@blueprint.delete('/admin/artifact-uploads/<identifier>')
@staged_operation
def cancel(store, owner, identifier):
    return {'success': True, 'data': store.cancel(owner, identifier),'message':'Transfer receipt closed'}


@blueprint.get('/admin/artifacts')
@staged_operation
def library(store, owner):
    values = repository().call('web_disk_files', owner)
    return {'success': True, 'data': {
        'ovas': [{**item, 'filename': item['display_name']} for item in values],
        'uploads': store.list(owner),
        'limits': {'MAX_FILE_SIZE': store.MAX_BYTES, 'CHUNK_SIZE': store.CHUNK_BYTES}}}


@blueprint.delete('/admin/artifacts/<identifier>')
def retire(identifier):
    from .validation import positive_id
    user = require_admin()
    identifier = positive_id(identifier,'image identifier')
    if not repository().scalar('get_filename_by_id',identifier,user['id']):
        raise ApiError('Image not found',404)
    internal().request('delete_artifact',{'artifact_id':identifier,'user_id':user['id']})
    return {'success':True,'message':'Image retired; its recovery copy is retained for administrator cleanup'}


@blueprint.post('/admin/artifact-uploads/<identifier>/retry')
@staged_operation
def retry(store,owner,identifier):
    rate_limit('retry-image',str(owner),20,3600)
    return {'success':True,'data':store.retry(owner,identifier),'message':'Validation retry queued'}
