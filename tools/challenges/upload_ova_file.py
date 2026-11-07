"""Stream OVA chunks through Flask and wait for confirmed artifact publication."""
import math
from pathlib import Path
import re
import time

from .client import artifact_name, request
from .yaml_parser import retrieve_ova_data


class ArtifactPending(RuntimeError):
    """The receipt remains authoritative; a timeout never starts another upload."""


def upload_ova_file(file_path, session, target_filename=None, prints=False, *,
                    timeout=1800, guest_os='linux', clock=time.monotonic, sleep=time.sleep):
    path = Path(file_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Use a regular OVA file')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Set a positive finite publication timeout')
    if guest_os not in ('linux', 'windows'):
        raise ValueError('Declare the Linux or Windows guest operating system')
    name = artifact_name(target_filename or path.name)
    library = request(session, 'GET', '/api/admin/artifacts')['data']
    limit = library['limits']['MAX_FILE_SIZE']
    size = path.stat().st_size
    if type(limit) is not int or not 0 < size <= limit:
        raise ValueError('OVA size exceeds the declared upload limit')
    metadata = request(session, 'POST', '/api/admin/artifact-uploads',
                       json={'name': name, 'size': size, 'guest_os': guest_os})['data']
    identifier, chunk_bytes = metadata.get('id'), metadata.get('chunk_bytes')
    if not isinstance(identifier, str) or re.fullmatch('[a-f0-9]{32}', identifier) is None:
        raise RuntimeError('The server returned an invalid upload identity')
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= 16*1024**2:
        raise RuntimeError('The server returned an invalid chunk size')
    prefix = '/api/admin/artifact-uploads/'+identifier
    if prints:
        print('Upload receipt:', identifier)
    with path.open('rb') as stream:
        for index in range(math.ceil(size/chunk_bytes)):
            chunk = stream.read(min(chunk_bytes, size-index*chunk_bytes))
            if len(chunk) != min(chunk_bytes, size-index*chunk_bytes):
                raise RuntimeError('Source OVA changed; inspect upload '+identifier)
            request(session, 'PUT', prefix+'/chunks/'+str(index), data=chunk,
                    headers={'Content-Type': 'application/octet-stream'}, timeout=(10, 1800))
        if stream.read(1):
            raise RuntimeError('Source OVA changed; inspect upload '+identifier)
    request(session, 'POST', prefix+'/seal', json={})
    deadline = clock()+timeout
    while True:
        value = request(session, 'GET', prefix)['data']
        if value.get('state') == 'READY' and type(value.get('artifact_id')) is int and value['artifact_id'] > 0:
            return value['artifact_id']
        if value.get('state') not in ('SEALED', 'PROCESSING') or clock() >= deadline:
            raise ArtifactPending('Publication is not confirmed for '+identifier+'; inspect this receipt before retrying')
        sleep(min(2, max(0, deadline-clock())))


def upload_all_ova_files(admin_session, path_to_yaml, prints=False):
    return [upload_ova_file(ova['path'], admin_session, target_filename=ova['name'], prints=prints, guest_os=ova.get('guest_os','linux'))
            for ova in retrieve_ova_data(path_to_yaml)]
