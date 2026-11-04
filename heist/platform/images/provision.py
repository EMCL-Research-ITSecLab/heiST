"""Create a template VM from normalized disks without importing user OVF options."""
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

from heist.artifacts.normalize import normalize
from heist.infrastructure.proxmox import client
from heist.infrastructure.proxmox.tasks import wait_for_task


def marker(vmid):
    return client.ownership_marker(vmid,template=True)


def configuration(vmid):
    value = client.make_api_call('GET', f'api2/json/nodes/{client.node}/qemu/{vmid}/config')['data']
    if not isinstance(value, dict) or value.get('description') != marker(vmid):
        raise RuntimeError('VM identity does not match this heiST import')
    return value


def import_normalized(source, vmid, storage):
    if type(vmid) is not int or not 0 < vmid < 2**31 or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', storage):
        raise ValueError('Invalid import VM or storage identity')
    if client.vm_exists_api_call(SimpleNamespace(id=vmid)):
        raise RuntimeError('VM identifier is already occupied; reconcile before importing')
    directory, receipt = normalize(source, os.environ.get('HEIST_NORMALIZED_IMAGES', '/var/lib/heist/normalized-images'))
    # Reserve the VM through Proxmox's create API, which refuses an occupied ID.
    # An uncertain response is never followed by unlock/destroy or blind retry.
    result = client.make_api_call('POST', f'api2/json/nodes/{client.node}/qemu', {
        'vmid': vmid, 'name': 'heist-template-'+str(vmid), 'description': marker(vmid), 'tags':client.ownership_tags(vmid),
        'memory': 1024, 'cores': 1, 'sockets': 1, 'bios': 'seabios', 'scsihw': 'virtio-scsi-pci'})
    wait_for_task(client.make_api_call,client.node,result,timeout=120)
    for index, item in enumerate(receipt['disks']):
        before = configuration(vmid)
        subprocess.run(['qm', 'importdisk', str(vmid), str(directory/item['name']), storage],
                       check=True, capture_output=True, timeout=1800)
        after = configuration(vmid)
        added = {key: value for key, value in after.items() if re.fullmatch('unused[0-9]+', key) and key not in before}
        if len(added) != 1:
            raise RuntimeError('Imported disk volume could not be identified uniquely')
        volume = next(iter(added.values()))
        if not isinstance(volume, str) or not volume.startswith(storage+':') or ',' in volume:
            raise RuntimeError('Unexpected imported storage volume')
        client.make_api_call('PUT', f'api2/json/nodes/{client.node}/qemu/{vmid}/config', {f'sata{index}': volume})
    configuration(vmid)
    client.make_api_call('PUT', f'api2/json/nodes/{client.node}/qemu/{vmid}/config', {'boot': 'order=sata0'})
    return receipt
