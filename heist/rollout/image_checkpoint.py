"""Copy opaque image-library bytes into independent, checksum-bound checkpoints.

No archive or guest disk is opened. Writers must remain quiesced throughout.
Recovery preserves newer/conflicting files in a separate quarantine directory.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile

from heist.files import fsync_directory, private_directory, sha256, write_json


def directory(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('Image checkpoint paths must be absolute without symlinks')
    return path


def inventory(root):
    root=directory(root)
    if not root.exists():
        return {}
    files={}
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or path.name in ('.','..') or len(files)>=100000:
            raise RuntimeError('Image library contains an unsupported entry; reconcile it before maintenance')
        files[path.name]={'sha256':sha256(path),'bytes':path.stat().st_size}
    return files


def copy_file(source,target,expected):
    descriptor,temporary=tempfile.mkstemp(prefix='.image-copy-',dir=target.parent)
    try:
        with os.fdopen(descriptor,'wb') as output,source.open('rb') as stream:
            shutil.copyfileobj(stream,output,8*1024**2)
            output.flush();os.fsync(output.fileno())
        temporary=Path(temporary)
        if temporary.stat().st_size!=expected['bytes'] or sha256(temporary)!=expected['sha256']:
            raise RuntimeError('Image changed while checkpoint bytes were copied')
        os.replace(temporary,target)
        fsync_directory(target.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def create(root,destination):
    root=directory(root)
    destination=directory(destination)
    if root==destination or root in destination.parents or destination in root.parents:
        raise RuntimeError('Image checkpoint must be outside its source library')
    destination=private_directory(destination)
    files=inventory(root)
    if shutil.disk_usage(destination).free<sum(item['bytes'] for item in files.values()):
        raise RuntimeError('Insufficient space for independent image checkpoint')
    payload=private_directory(destination/'files')
    for name,item in files.items():
        copy_file(root/name,payload/name,item)
    if inventory(root)!=files:
        raise RuntimeError('Image library changed during checkpoint')
    manifest={'schema':1,'library':str(root),'files':files}
    write_json(destination/'manifest.json',manifest)
    return {'path':str(destination),'manifest_sha256':sha256(destination/'manifest.json')}


def inspect(checkpoint,root):
    source=directory(checkpoint['path'])
    manifest=source/'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size>32*1024**2 or sha256(manifest)!=checkpoint['manifest_sha256']:
        raise RuntimeError('Image checkpoint manifest checksum differs')
    value=json.loads(manifest.read_text())
    if set(value)!={'schema','library','files'} or value['schema']!=1 or value['library']!=str(directory(root)):
        raise RuntimeError('Image checkpoint does not belong to this library')
    # Computing an inventory validates regular files, names, sizes and every hash;
    # an unlisted payload cannot enter recovery through a forged relative path.
    if not isinstance(value['files'],dict) or inventory(source/'files')!=value['files']:
        raise RuntimeError('Image checkpoint payload is incomplete or corrupt')
    return source,value['files']


def restore(checkpoint,root,quarantine):
    source,files=inspect(checkpoint,root)
    root=directory(root)
    current=inventory(root)
    quarantine=private_directory(directory(quarantine))
    if root==quarantine or root in quarantine.parents or quarantine in root.parents:
        raise RuntimeError('Image recovery quarantine must be outside the library')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<sum(item['bytes'] for name,item in files.items() if current.get(name)!=item):
        raise RuntimeError('Insufficient space to restore image checkpoint')
    for name,item in current.items():
        if files.get(name)==item:
            continue
        target=quarantine/(item['sha256']+'.blob')
        if target.exists():
            if target.is_symlink() or not target.is_file() or sha256(target)!=item['sha256']:
                raise RuntimeError('Newer image recovery copy has conflicting contents')
            # A previous recovery may have copied these same bytes. Preserve the
            # live file until the exact copy is confirmed, then remove the alias.
            (root/name).unlink()
        else:
            if root.stat().st_dev==quarantine.stat().st_dev:
                os.replace(root/name,target)
            else:
                copy_file(root/name,target,item)
                (root/name).unlink()
        fsync_directory(quarantine);fsync_directory(root)
    for name,item in files.items():
        if current.get(name)!=item:
            copy_file(source/'files'/name,root/name,item)
    if inventory(root)!=files:
        raise RuntimeError('Recovered image library does not match its checkpoint')
    return {'quarantine':str(quarantine),'files':len(files)}
