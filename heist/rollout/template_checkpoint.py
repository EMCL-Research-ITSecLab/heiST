"""Validate identities of registered, stopped template VMs before checkpointing."""
import hashlib
import json
import re
import uuid


def disk_capacity(configuration):
    total=0
    for name,value in configuration.items():
        if name.startswith('unused'):
            raise RuntimeError('Detach/reconcile unused template volumes before checkpointing')
        if not re.fullmatch(r'(?:sata|scsi|virtio|ide)\d+',name) or 'media=cdrom' in value or 'cloudinit' in value:
            continue
        if 'backup=0' in value or 'shared=1' in value or not re.match(r'[A-Za-z0-9_-]+:',value):
            raise RuntimeError('Every template disk must use exclusively backed-up managed storage')
        match=re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([KMGT])(?:,|$)',value)
        if not match:raise RuntimeError('Cannot determine template checkpoint disk capacity')
        total+=int(float(match[1])*1024**('KMGT'.index(match[2])+1))
    return total


def identity(configuration):
    disk_capacity(configuration)
    if configuration.get('template')!='1' or configuration.get('lock') or 'net30' in configuration:
        raise RuntimeError('Registered templates must be stopped templates without provisioning locks or temporary NICs')
    if any(name.startswith(('hostpci','virtiofs','usb')) or name=='args' for name in configuration):
        raise RuntimeError('Template checkpoint cannot cover external/passthrough state')
    match=re.search(r'(?:^|,)uuid=([^,]+)',configuration.get('smbios1',''))
    if not match:
        raise RuntimeError('Template VM has no stable UUID')
    return {'uuid':str(uuid.UUID(match[1])),'name':configuration.get('name'),
            'configuration_sha256':hashlib.sha256(json.dumps(configuration,sort_keys=True).encode()).hexdigest()}


def require_same_vm(configuration,expected):
    actual=identity(configuration)
    if actual['uuid']!=expected['uuid'] or actual['name']!=expected['name']:
        raise RuntimeError('Refusing to overwrite a foreign template VM identity')
