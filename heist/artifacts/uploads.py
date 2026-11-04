"""Private resumable upload storage with durable sealing and immutable chunks.

Sealed files remain quarantined until a separate disk-validation/import job
accepts them. This module neither registers disk_files nor contacts Proxmox.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from heist.files import fsync_directory, maintenance_lock, private_directory, write_file, write_json


class UploadError(ValueError):
    """Invalid or conflicting upload request."""


class UploadStore:
    CHUNK_BYTES = 4*1024**2
    MAX_BYTES = 16*1024**3
    MAX_PENDING = 2
    EXPIRY_SECONDS = 24*3600
    RESERVE_BYTES = 256*1024**2

    def __init__(self, root, *, clock=time.time):
        self.root = private_directory(root)
        self.clock = clock

    def owner_directory(self, owner):
        if type(owner) is not int or owner <= 0:
            raise UploadError('Invalid upload owner')
        return private_directory(self.root/str(owner))

    @contextmanager
    def session(self, owner, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier):
            raise UploadError('Invalid upload identifier')
        directory = self.owner_directory(owner)/identifier
        if not directory.is_dir() or directory.is_symlink():
            raise UploadError('Upload not found')
        with maintenance_lock(directory):
            metadata = json.loads((directory/'metadata.json').read_text())
            if metadata['owner'] != owner or metadata['id'] != identifier:
                raise UploadError('Upload ownership mismatch')
            yield directory, metadata

    def available(self, size):
        if shutil.disk_usage(self.root).free < size+self.RESERVE_BYTES:
            raise UploadError('Insufficient staging storage')

    def create(self, owner, name, size, guest_os, *, identifier=None):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,190}\.ova', name, re.IGNORECASE) or '..' in name:
            raise UploadError('Choose a simple .ova filename')
        if type(size) is not int or not 0 < size <= self.MAX_BYTES:
            raise UploadError('Invalid upload size')
        if guest_os not in ('linux', 'windows'):
            raise UploadError('Invalid guest operating system')
        owner_directory = self.owner_directory(owner)
        with maintenance_lock(owner_directory):
            if identifier is not None:
                if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
                    raise UploadError('Invalid upload identifier')
                existing = owner_directory/identifier
                if existing.exists():
                    with self.session(owner, identifier) as (_, previous):
                        if (previous['name'],previous['size'],previous['guest_os']) != (name,size,guest_os):
                            raise UploadError('Existing upload identity has different input')
                        return self.summary(previous)
            pending = []
            for child in owner_directory.iterdir():
                if re.fullmatch('[0-9a-f]{32}', child.name) and child.is_dir() and not child.is_symlink():
                    state = json.loads((child/'metadata.json').read_text())
                    if state['state'] not in ('CANCELLED','READY','FAILED'):
                        pending.append(state)
            if len(pending) >= self.MAX_PENDING:
                raise UploadError('Finish or cancel an existing upload first')
            self.available(size*2+sum(item['size']*2 for item in pending))
            identifier = identifier or uuid.uuid4().hex
            directory = private_directory(owner_directory/('.initializing-'+identifier))
            value = {'schema': 1, 'id': identifier, 'owner': owner, 'name': name, 'size': size,
                     'guest_os': guest_os, 'created': self.clock(), 'state': 'RECEIVING',
                     'chunks': {}, 'chunk_bytes': self.CHUNK_BYTES}
            try:
                write_json(directory/'metadata.json', value)
            except BaseException:
                shutil.rmtree(directory)
                raise
            os.rename(directory, owner_directory/identifier)
            fsync_directory(owner_directory)
            return self.summary(value)

    def summary(self, value):
        return {key: value[key] for key in ('id', 'name', 'size', 'guest_os', 'state', 'chunk_bytes')} | {
            'received': sorted(int(index) for index in value['chunks']),
            'expires': value['created']+self.EXPIRY_SECONDS,
            **{key:value[key] for key in ('message','artifact_id') if key in value}}

    def status(self, owner, identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
            raise UploadError('Invalid upload identifier')
        directory=self.owner_directory(owner)/identifier
        if directory.is_symlink() or not directory.is_dir():
            raise UploadError('Upload not found')
        value=json.loads((directory/'metadata.json').read_text())
        if value['id']!=identifier or value['owner']!=owner:
            raise UploadError('Upload ownership mismatch')
        return self.summary(value)

    def list(self, owner):
        directory = self.owner_directory(owner)
        values = []
        for path in directory.iterdir():
            if not re.fullmatch('[0-9a-f]{32}', path.name) or path.is_symlink() or not path.is_dir():
                continue
            metadata = json.loads((path/'metadata.json').read_text())
            if metadata['owner'] != owner or metadata['id'] != path.name:
                raise UploadError('Upload ownership mismatch')
            if metadata['state'] != 'CANCELLED':
                values.append(self.summary(metadata))
        return sorted(values, key=lambda value: value['expires'], reverse=True)

    def receiving(self, value):
        if value['state'] != 'RECEIVING':
            raise UploadError('Upload no longer accepts chunks')
        if self.clock() >= value['created']+self.EXPIRY_SECONDS:
            raise UploadError('Upload expired; cancel it before starting another')

    def put(self, owner, identifier, index, stream):
        with self.session(owner, identifier) as (directory, value):
            self.receiving(value)
            chunk_bytes = value['chunk_bytes']
            count = (value['size']+chunk_bytes-1)//chunk_bytes
            if type(index) is not int or not 0 <= index < count:
                raise UploadError('Invalid chunk index')
            expected = min(chunk_bytes, value['size']-index*chunk_bytes)
            # The HTTP layer must also bound the whole request. Read one extra
            # byte here so missing Content-Length cannot evade the chunk bound.
            data = stream.read(expected+1)
            if len(data) != expected:
                raise UploadError('Chunk length does not match the upload')
            digest = hashlib.sha256(data).hexdigest()
            path = directory/f'{index}.chunk'
            if path.exists():
                if path.is_symlink() or path.stat().st_size != expected or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise UploadError('A different chunk already occupies this index')
            else:
                self.available(expected)
                write_file(path, data)
            # A crash after the chunk rename but before this receipt is repaired
            # by replaying the same bytes; a different replay remains rejected.
            value['chunks'][str(index)] = digest
            write_json(directory/'metadata.json', value)
            return self.summary(value)

    def seal(self, owner, identifier):
        with self.session(owner, identifier) as (directory, value):
            if value['state'] in ('SEALED','PROCESSING','READY'):
                return self.summary(value)
            self.receiving(value)
            chunk_bytes = value['chunk_bytes']
            count = (value['size']+chunk_bytes-1)//chunk_bytes
            if set(value['chunks']) != {str(index) for index in range(count)}:
                raise UploadError('Upload is missing chunks')
            self.available(value['size'])
            partial, sealed = directory/'assembling', directory/'payload.ova'
            digest = hashlib.sha256()
            try:
                # The directory is private and exclusively locked. An unfinished
                # assembly is always rebuilt from immutable, receipted chunks.
                partial.unlink(missing_ok=True)
                descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, 'wb') as output:
                    for index in range(count):
                        path = directory/f'{index}.chunk'
                        if path.is_symlink():
                            raise UploadError('Unsafe chunk file')
                        data = path.read_bytes()
                        expected = min(chunk_bytes, value['size']-index*chunk_bytes)
                        if len(data) != expected or hashlib.sha256(data).hexdigest() != value['chunks'][str(index)]:
                            raise UploadError('Chunk integrity check failed')
                        output.write(data)
                        digest.update(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(partial, sealed)
                fsync_directory(directory)
                value.update(state='SEALED', sha256=digest.hexdigest())
                write_json(directory/'metadata.json', value)
            finally:
                partial.unlink(missing_ok=True)
            return self.summary(value)

    def discard_payload(self, directory):
        directory=Path(directory)
        for path in directory.glob('*.chunk'):
            path.unlink()
        for name in ('assembling','payload.ova'):
            (directory/name).unlink(missing_ok=True)
        fsync_directory(directory)

    def expire(self, owner):
        # Parent and child leases follow the same order as initialization. Live
        # chunk/conversion work is skipped; no process is killed to reclaim space.
        count=0
        parent=self.owner_directory(owner)
        with maintenance_lock(parent):
            for path in parent.iterdir():
                if not re.fullmatch('[a-f0-9]{32}',path.name) or path.is_symlink() or not path.is_dir():
                    continue
                try:
                    with self.session(owner,path.name) as (directory,value):
                        if value['state'] in ('READY','FAILED','CANCELLED'):
                            self.discard_payload(directory)
                        elif value['state']=='RECEIVING' and self.clock()>=value['created']+self.EXPIRY_SECONDS:
                            value.update(state='CANCELLED',message='Incomplete transfer expired')
                            write_json(directory/'metadata.json',value)
                            self.discard_payload(directory)
                            count+=1
                except BlockingIOError:
                    continue
        return count

    def cancel(self, owner, identifier):
        with self.session(owner, identifier) as (directory, value):
            if value['state'] not in ('RECEIVING', 'CANCELLED','FAILED','READY'):
                raise UploadError('Running or uncertain validation requires reconciliation before closing its receipt')
            value['state'] = 'CANCELLED'
            write_json(directory/'metadata.json', value)
            for path in directory.glob('*.chunk'):
                path.unlink()
            (directory/'assembling').unlink(missing_ok=True)
            (directory/'payload.ova').unlink(missing_ok=True)
            fsync_directory(directory)
            return self.summary(value)

    def retry(self,owner,identifier):
        with self.session(owner,identifier) as (directory,value):
            if value['state']!='NEEDS_REVIEW':
                raise UploadError('Only an interrupted transfer awaiting review can be retried')
            if not (directory/'payload.ova').is_file():
                raise UploadError('Original staged bytes are unavailable; begin a new transfer')
            value.update(state='PROCESSING',attempts=0,next_attempt=0,message='Retry queued with the original image identity')
            write_json(directory/'metadata.json',value)
            return self.summary(value)
