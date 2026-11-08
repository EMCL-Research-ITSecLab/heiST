"""Normalize bounded OVA payloads before privileged hypervisor imports."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

from heist.files import maintenance_lock, private_directory, sha256, write_json
from .ova import InvalidOva, Limits, inspect_envelope


def qcow_header(path, capacity):
    """Check the standalone QCOW2 envelope before any privileged consumer runs."""
    with path.open('rb') as stream:
        header = stream.read(104)
    if len(header) < 104 or header[:4] != b'QFI\xfb':
        raise InvalidOva('Converted disk is not QCOW2')
    version = struct.unpack_from('>I', header, 4)[0]
    backing, backing_size, cluster_bits, virtual, encryption = struct.unpack_from('>QIIQI', header, 8)
    if version != 3 or backing or backing_size or not 9 <= cluster_bits <= 21 or virtual != capacity or encryption:
        raise InvalidOva('Converted disk has unsupported size, backing or encryption metadata')
    incompatible = struct.unpack_from('>Q', header, 72)[0]
    if incompatible:
        raise InvalidOva('Converted disk uses unsupported incompatible features')


def verify(directory, expected_digest):
    directory = Path(directory)
    if directory.is_symlink():
        raise InvalidOva('Normalized image directory must not be a symlink')
    value = json.loads((directory/'receipt.json').read_text())
    if value.get('schema') != 1 or value.get('source_sha256') != expected_digest:
        raise InvalidOva('Normalized image receipt differs')
    for index, item in enumerate(value['disks']):
        if item['name'] != f'disk{index}.qcow2':
            raise InvalidOva('Invalid normalized disk name')
        path = directory/item['name']
        if path.is_symlink() or sha256(path) != item['sha256']:
            raise InvalidOva('Normalized disk checksum differs')
        qcow_header(path, item['capacity'])
    if not 1 <= len(value['disks']) <= 8:
        raise InvalidOva('Invalid normalized disk count')
    return value


def normalize(source, cache, *, limits=Limits(), worker=None):
    if os.geteuid() != 0:
        raise ValueError('Disk normalization requires the privileged isolated worker')
    if worker is None:
        from .conversion_account import account
        user = account()
        worker = (user.pw_uid, user.pw_gid)
    if len(worker) != 2 or any(type(value) is not int or value < 100 for value in worker):
        raise ValueError('Use a dedicated unprivileged disk worker account')
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise InvalidOva('OVA must be a private regular file')
    envelope = inspect_envelope(source, limits)
    source_digest = sha256(source)
    cache = private_directory(cache)
    # Serialize cache publication, including repeated identical uploads.
    with maintenance_lock(cache):
        destination = cache/source_digest
        if destination.exists():
            return destination, verify(destination, source_digest)
        maximum = sum(item.declared_capacity for item in envelope.disks)+128*1024**2
        if shutil.disk_usage(cache).free < maximum+sum(item.member.size for item in envelope.disks)+256*1024**2:
            raise InvalidOva('Insufficient isolated conversion storage')
        with tempfile.TemporaryDirectory(prefix='.normalize-', dir=cache) as temporary:
            stage = Path(temporary)
            inputs, outputs, root = stage/'input', stage/'output', stage/'root'
            for path in (inputs, outputs, root):
                path.mkdir(mode=0o755)
            os.chown(outputs, *worker)
            outputs.chmod(0o700)
            with source.open('rb') as original:
                for item in envelope.disks:
                    original.seek(item.member.offset)
                    path = inputs/item.member.name
                    with path.open('xb') as target:
                        remaining = item.member.size
                        while remaining:
                            block = original.read(min(1024**2, remaining))
                            if not block:
                                raise InvalidOva('OVA changed during extraction')
                            target.write(block)
                            remaining -= len(block)
                    path.chmod(0o444)
            if sha256(source) != source_digest:
                raise InvalidOva('OVA changed during conversion preparation')
            specification = {'maximum_output': maximum, 'uid': worker[0], 'gid': worker[1], 'disks': [
                {'name': item.member.name, 'capacity': item.declared_capacity} for item in envelope.disks]}
            write_json(stage/'specification.json', specification)
            helper = Path(__file__).with_name('sandbox.py')
            result = subprocess.run(['setpriv','--pdeathsig','KILL','unshare', '--mount', '--net', '--pid', '--fork', '--kill-child',
                                     sys.executable, '-I', str(helper), str(root), str(inputs), str(outputs), str(stage/'specification.json')],
                                    check=True, capture_output=True, timeout=1800,
                                    env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
            if len(result.stdout) > 65536:
                raise InvalidOva('Conversion report exceeds limit')
            value = json.loads(result.stdout)
            expected = [{'name': f'disk{index}.qcow2', 'capacity': item.declared_capacity} for index, item in enumerate(envelope.disks)]
            if value != {'schema': 1, 'disks': expected}:
                raise InvalidOva('Unexpected conversion report')
            receipt = {'schema': 1, 'source_sha256': source_digest, 'disks': []}
            published = stage/'published'
            published.mkdir(mode=0o700)
            for item in expected:
                path = outputs/item['name']
                if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
                    raise InvalidOva('Invalid normalized disk output')
                qcow_header(path, item['capacity'])
                os.chown(path, os.geteuid(), os.getegid())
                path.chmod(0o600)
                os.rename(path, published/item['name'])
                receipt['disks'].append(item | {'sha256': sha256(published/item['name'])})
            write_json(published/'receipt.json', receipt)
            for path in published.iterdir():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
            os.rename(published, destination)
            descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return destination, verify(destination, source_digest)
