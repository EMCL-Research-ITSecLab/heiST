"""Export a stopped template's read-only raw block disks without starting QEMU.

This covers Proxmox #6675 without changing installed Proxmox code or making
base volumes writable. The caller must still verify the VMA and rehearse restore.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from heist.files import fsync_directory, private_directory


def command(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30).stdout


@dataclass(frozen=True)
class Template:
    vmid: int
    configuration: str
    disks: tuple[tuple[str, str, str, int, int], ...]

    def archive_configuration(self):
        mappings = ''.join(f'#qmdump#map:{name}:drive-{name}:{storage}:raw:\n'
                           for name, _, storage, _, _ in self.disks)
        return self.configuration.rstrip()+'\n'+mappings


def inspect(vmid, expected_uuid, *, run=command, metadata=os.stat):
    if type(vmid) is not int or not 100 <= vmid <= 999999999:
        raise ValueError('Declare a valid Proxmox template ID')
    expected_uuid = str(uuid.UUID(expected_uuid))
    if run(['qm', 'status', str(vmid)]).strip() != 'status: stopped':
        raise RuntimeError('Only stopped templates may use read-only export')
    text = run(['qm', 'config', str(vmid), '--current', '1'])
    values = {}
    for line in text.splitlines():
        if not line or ': ' not in line:
            raise RuntimeError('Unrecognized template configuration')
        name, value = line.split(': ', 1)
        if name in values or name.startswith(('unused', 'hostpci', 'usb', 'virtiofs')) or name in ('args', 'lock', 'net30'):
            raise RuntimeError('Template contains unsupported or changing state')
        values[name] = value
    match = re.search(r'(?:^|,)uuid=([^,]+)', values.get('smbios1', ''))
    if values.get('template') != '1' or not match or str(uuid.UUID(match[1])) != expected_uuid:
        raise RuntimeError('Template identity differs from the checkpoint')
    disks = []
    for name, value in sorted(values.items()):
        if not re.fullmatch(r'(?:ide|sata|scsi|virtio)\d+', name):
            continue
        if 'media=cdrom' in value:
            continue
        volume = value.split(',')[0]
        if ('cloudinit' in value or 'backup=0' in value or 'shared=1' in value
                or not re.fullmatch(r'[A-Za-z0-9_-]+:[A-Za-z0-9_./-]+', volume)):
            raise RuntimeError('Every template disk must be an exclusively backed-up raw base volume')
        path = run(['pvesm', 'path', volume]).strip()
        info = metadata(path)
        if not path.startswith('/dev/') or not stat.S_ISBLK(info.st_mode):
            raise RuntimeError('Read-only template export requires managed raw block storage')
        if run(['blockdev', '--getro', path]).strip() != '1':
            raise RuntimeError('Template base volume must already be read-only')
        size = int(run(['blockdev', '--getsize64', path]).strip())
        if size <= 0:
            raise RuntimeError('Cannot confirm template disk capacity')
        disks.append((name, path, volume.split(':', 1)[0], size, info.st_rdev))
    if not disks:
        raise RuntimeError('No read-only raw template disks were found')
    # Recheck state after resolving all storage paths; this never acquires a
    # backup lock or alters the template/base volume.
    if run(['qm', 'status', str(vmid)]).strip() != 'status: stopped':
        raise RuntimeError('Template state changed during inspection')
    return Template(vmid, text, tuple(disks))


def create(vmid, expected_uuid, destination, *, timeout=7200):
    if os.geteuid() != 0 or not Path('/etc/pve/local').is_dir():
        raise RuntimeError('Run on the declared Proxmox host as root')
    destination = Path(destination)
    parent = private_directory(destination.parent)
    if any(p.is_symlink() for p in parent.parents):
        raise RuntimeError('Backup path contains a symlink')
    if not re.fullmatch(r'vzdump-qemu-'+str(vmid)+r'-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.vma\.zst', destination.name):
        raise ValueError('Use a canonical vzdump filename for qmrestore')
    partial = destination.with_suffix(destination.suffix+'.partial')
    log = destination.with_suffix(destination.suffix+'.log')
    if any(p.exists() or p.is_symlink() for p in (destination, partial, log)):
        raise RuntimeError('Backup output exists; inspect the prior export before retrying')
    template = inspect(vmid, expected_uuid)
    if shutil.disk_usage(parent).free < sum(disk[3] for disk in template.disks)+2*1024**3:
        raise RuntimeError('Reserve all raw template capacities plus 2 GiB before export')
    started = time.monotonic()
    producer = consumer = None
    with tempfile.TemporaryDirectory(prefix='.template-', dir=parent) as temporary:
        configuration = Path(temporary)/'qemu-server.conf'
        configuration.write_text(template.archive_configuration())
        configuration.chmod(0o600)
        with partial.open('xb') as output, log.open('xb') as diagnostics:
            os.fchmod(output.fileno(), 0o600)
            os.fchmod(diagnostics.fileno(), 0o600)
            try:
                arguments = ['ionice', '-c', '2', '-n', '7', 'nice', '-n', '10',
                             'vma', 'create', 'exec:cat', '-c', str(configuration)]
                for name, path, _, _, _ in template.disks:
                    arguments.extend(['-d', 'format=raw:drive-'+name+'='+path])
                producer = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=diagnostics,
                                            cwd=temporary, start_new_session=True)
                consumer = subprocess.Popen(['nice', '-n', '10', 'zstd', '-q', '-T1', '-1', '-c'],
                                            stdin=producer.stdout, stdout=output, stderr=diagnostics,
                                            start_new_session=True)
                producer.stdout.close()
                consumer_exit = consumer.wait(timeout=timeout)
                producer_exit = producer.wait(timeout=max(1, timeout-(time.monotonic()-started)))
                if consumer_exit or producer_exit:
                    raise RuntimeError('Template export failed; inspect the private archive log')
                output.flush()
                os.fsync(output.fileno())
            finally:
                for process in (consumer, producer):
                    if process is not None and process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=30)
    if inspect(vmid, expected_uuid) != template:
        raise RuntimeError('Template configuration or read-only source changed during backup')
    os.rename(partial, destination)
    fsync_directory(parent)
    return {'vmid': vmid, 'file': destination.name, 'bytes': destination.stat().st_size,
            'configuration_sha256': hashlib.sha256(template.configuration.encode()).hexdigest(),
            'mode': 'stopped read-only raw template export', 'native_restore_accepted': False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vmid', type=int, required=True)
    parser.add_argument('--uuid', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.vmid, args.uuid, args.output)))


if __name__ == '__main__':
    main()
