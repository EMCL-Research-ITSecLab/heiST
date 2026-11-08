"""Validate identities of registered, stopped template VMs before checkpointing."""
import hashlib
import json
import re
import uuid
import subprocess


def require_backup_support(configurations, version):
    """Reject Proxmox #6675 before maintenance, without changing template disks."""
    if not any(re.fullmatch(r'(?:ide|sata)\d+', name)
               and 'media=cdrom' not in value and 'cloudinit' not in value
               for config in configurations for name, value in config.items()):
        return
    if not isinstance(version, str) or not re.fullmatch(r'(?:\d+:)?\d+\.\d+\.\d+(?:[+~.-][A-Za-z0-9.+~:-]+)?', version):
        raise RuntimeError('Cannot confirm qemu-server template backup compatibility')
    # Epochs do not change which upstream code contains the fix. Debian's
    # ordering still handles package revisions and prereleases correctly.
    upstream_version=version.split(':',1)[-1]
    affected = (subprocess.run(['dpkg', '--compare-versions', upstream_version, 'ge', '9.0.0'], check=False).returncode,
                subprocess.run(['dpkg', '--compare-versions', upstream_version, 'lt', '9.0.18'], check=False).returncode)
    if any(code not in (0, 1) for code in affected):
        raise RuntimeError('Cannot confirm qemu-server template backup compatibility')
    if affected == (0, 0):
        raise RuntimeError('qemu-server '+version+' cannot safely back up IDE/SATA templates '
                           '(Proxmox #6675). Install a supported version with the 9.0.18 fix '
                           'and verify template backup/restore before maintenance.')


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
