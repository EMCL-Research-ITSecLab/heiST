"""Administrator-only upload staging; sealed files are not published images."""
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, request

from heist.artifacts.uploads import UploadError, UploadStore
from .context import body, rate_limit, require_admin
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
    return {'success': True, 'data': store.cancel(owner, identifier)}
