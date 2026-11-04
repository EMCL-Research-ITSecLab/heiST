"""Idempotent image publication; filenames are derived from server upload identities."""
import os
from pathlib import Path
import re
import shutil
import tempfile

from heist.artifacts.normalize import normalize
from heist.files import fsync_directory, sha256, write_json
from heist.platform.jobs.journal import RejectedOperation


class ImageConflict(ValueError):
    pass


class ImageInUse(ImageConflict,RejectedOperation):
    pass


def require_admin(connection, owner):
    with connection.cursor() as cursor:
        cursor.execute('SELECT is_admin FROM public.users WHERE id=%s FOR SHARE', (owner,))
        if cursor.fetchone() != (True,):
            raise ImageConflict('Image owner no longer has administrator access')


def publish(connection, store, owner, identifier, expected_sha256, *, import_directory='/var/lib/vz/import', cache='/var/lib/heist/normalized-images'):
    if not isinstance(expected_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_sha256):
        raise ImageConflict('Invalid image checksum')
    require_admin(connection,owner)
    with store.session(owner,identifier) as (directory,value):
        if value.get('sha256')!=expected_sha256:
            raise ImageConflict('Image transfer checksum differs')
        if value['state']=='READY':
            with connection.cursor() as cursor:
                cursor.execute('SELECT id FROM public.disk_files WHERE id=%s AND user_id=%s AND is_available', (value['artifact_id'],owner))
                if not cursor.fetchone():
                    raise ImageConflict('Previously published image has been retired; this transfer cannot recreate it')
            return {'artifact_id':value['artifact_id']}
        if value['state'] not in ('SEALED','PROCESSING') or value.get('sha256')!=expected_sha256:
            raise ImageConflict('Image transfer is incomplete or its checksum differs')
        source=directory/'payload.ova'
        if sha256(source)!=expected_sha256:
            raise ImageConflict('Staged image checksum differs')
        value['state']='PROCESSING'
        write_json(directory/'metadata.json',value)
        normalize(source,cache)
        target_root=Path(import_directory)
        if target_root.is_symlink():
            raise ImageConflict('Image library must not be a symlink')
        target_root.mkdir(mode=0o700,parents=True,exist_ok=True)
        filename=str(owner)+'-'+identifier+'.ova'
        target=target_root/filename
        if target.exists():
            if target.is_symlink() or sha256(target)!=expected_sha256:
                raise ImageConflict('Image storage identity already has different contents')
        else:
            descriptor,temporary=tempfile.mkstemp(prefix='.image-',dir=target_root)
            try:
                with os.fdopen(descriptor,'wb') as output,source.open('rb') as original:
                    shutil.copyfileobj(original,output,length=1024**2)
                    output.flush();os.fsync(output.fileno())
                os.link(temporary,target)  # publish without overwriting another identity
                fsync_directory(target_root)
            finally:
                Path(temporary).unlink(missing_ok=True)
        display=Path(value['name']).stem
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('heist-image-owner:'||%s::text,0))",(owner,))
                require_admin(connection,owner)
                cursor.execute('SELECT id,proxmox_filename,guest_os,is_available FROM public.disk_files WHERE user_id=%s AND display_name=%s FOR UPDATE',(owner,display))
                previous=cursor.fetchone()
                if previous:
                    artifact_id,stored,guest,available=previous
                    if stored!=filename or guest!=value['guest_os'] or not available:
                        raise ImageConflict('An image with this display name already exists')
                else:
                    cursor.execute('INSERT INTO public.disk_files(user_id,display_name,proxmox_filename,guest_os) VALUES(%s,%s,%s,%s) RETURNING id',
                                   (owner,display,filename,value['guest_os']))
                    artifact_id=cursor.fetchone()[0]
        # If this receipt write is interrupted, the next identical request finds
        # the immutable file and matching committed row instead of inserting again.
        value.update(state='READY',artifact_id=artifact_id,message='Image validated and available')
        write_json(directory/'metadata.json',value)
        store.discard_payload(directory)
        return {'artifact_id':artifact_id}


def retire(connection, artifact_id, owner, *, import_directory='/var/lib/vz/import'):
    require_admin(connection,owner)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT proxmox_filename FROM public.disk_files WHERE id=%s AND user_id=%s FOR UPDATE',(artifact_id,owner))
            row=cursor.fetchone()
            if not row:
                raise ImageConflict('Image not found')
            filename=row[0]
            if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\\.ova',filename) or '..' in filename:
                raise ImageConflict('Invalid managed image storage name')
            cursor.execute('SELECT 1 FROM public.machine_templates WHERE disk_file_id=%s LIMIT 1',(artifact_id,))
            if cursor.fetchone():
                raise ImageInUse('Image is still required by an exercise')
            cursor.execute('UPDATE public.disk_files SET is_available=FALSE WHERE id=%s',(artifact_id,))
    # Availability is durably disabled before touching bytes. Authoring takes a
    # conflicting row lease, so cached option lists cannot create a new reference.
    root=Path(import_directory)
    source=root/filename
    retired=root/('.retired-'+str(artifact_id)+'-'+filename)
    if source.is_symlink() or retired.is_symlink():
        raise ImageConflict('Image files must not be symlinks')
    if source.exists():
        if retired.exists():
            raise ImageConflict('A prior retirement requires reconciliation')
        os.rename(source,retired)
        fsync_directory(root)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM public.disk_files WHERE id=%s AND user_id=%s AND is_available=FALSE',(artifact_id,owner))
    # Keep the retired bytes for maintenance garbage collection. A database
    # commit/response failure must never cause irrevocable deletion of this copy.
    return {'artifact_id':artifact_id}
