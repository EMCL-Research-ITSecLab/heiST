#!/usr/bin/env python3
"""Export a stopped nested pilot as a restricted OVA with one management NIC.

This creates a candidate. Cold import and real functional retesting remain
required. Nested virtualization must be enabled by the target hypervisor.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET

from ova_inspect import inspect
from ovf import OVF, RASD, ovf_document, sha256

CHUNK_BYTES = 2 * 1024**3
USTAR_MAX_BYTES = 8 * 1024**3 - 1
ROOT = Path(__file__).resolve().parents[2]


class SliceReader:
    def __init__(self, stream, count):
        self.stream, self.remaining = stream, count

    def read(self, size=-1):
        count = self.remaining if size < 0 else min(size, self.remaining)
        value = self.stream.read(count)
        self.remaining -= len(value)
        return value


def disk_parts(disk, chunk_bytes=CHUNK_BYTES):
    """Hash USTAR-safe slices without creating another copy of the VMDK."""
    total = disk.stat().st_size
    if chunk_bytes <= 0 or chunk_bytes > USTAR_MAX_BYTES:
        raise ValueError('Chunk size must fit USTAR')
    parts = []
    with disk.open('rb') as stream:
        offset = 0
        while offset < total:
            count = min(chunk_bytes, total - offset)
            digest = hashlib.sha256()
            remaining = count
            while remaining:
                block = stream.read(min(8 * 1024**2, remaining))
                if not block:
                    raise ValueError('Disk changed while hashing')
                digest.update(block)
                remaining -= len(block)
            parts.append({'name': disk.name + f'.{len(parts):09d}', 'offset': offset,
                          'bytes': count, 'sha256': digest.hexdigest()})
            offset += count
    return parts


def descriptor(name, disk_name, disk_size, capacity, memory_mib, cpus, chunk_bytes=None):
    root = ET.fromstring(ovf_document(name, disk_name, disk_size, capacity, memory_mib, cpus))
    q = lambda namespace, key: '{' + namespace + '}' + key
    if chunk_bytes is not None:
        root.find(q(OVF, 'References')).find(q(OVF, 'File')).set(q(OVF, 'chunkSize'), str(chunk_bytes))
    network = ET.Element(q(OVF, 'NetworkSection'))
    ET.SubElement(network, q(OVF, 'Info')).text = 'One isolated management network'
    entry = ET.SubElement(network, q(OVF, 'Network'), {q(OVF, 'name'): 'management'})
    ET.SubElement(entry, q(OVF, 'Description')).text = 'Use an isolated NAT network; enable nested virtualization separately'
    system = root.find(q(OVF, 'VirtualSystem'))
    root.insert(list(root).index(system), network)
    system.find(q(OVF, 'Info')).text = 'Private nested Proxmox/heiST pilot appliance'
    hardware = system.find(q(OVF, 'VirtualHardwareSection'))
    hardware.find(q(OVF, 'Info')).text = 'CPU, memory, SATA boot disk and one management NIC'
    nic = ET.SubElement(hardware, q(OVF, 'Item'))
    for key, value in (('InstanceID', '5'), ('ResourceType', '10'), ('ElementName', 'Management NIC'),
                       ('ResourceSubType', 'E1000'), ('Connection', 'management'), ('AutomaticAllocation', 'true')):
        ET.SubElement(nic, q(RASD, key)).text = value
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def inspect_appliance(path):
    # The shared verifier checks every supplied manifest record and rejects
    # traversal/links. Add coverage and ordering checks for a chunked disk.
    report = inspect(path, verify=True)
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        ovf = next(member for member in members if member.name.endswith('.ovf'))
        root = ET.fromstring(archive.extractfile(ovf).read())
        references = root.findall('.//{' + OVF + '}References/{' + OVF + '}File')
        if len(references) != 1:
            raise ValueError('Expected one appliance disk file reference')
        entry = references[0]
        name = entry.attrib['{' + OVF + '}href']
        if Path(name).name != name or not name.endswith('.vmdk'):
            raise ValueError('Expected a flat VMDK reference')
        size = int(entry.attrib['{' + OVF + '}size'])
        chunk = int(entry.attrib.get('{' + OVF + '}chunkSize', '0'))
        if size <= 0 or chunk < 0 or chunk > USTAR_MAX_BYTES:
            raise ValueError('Invalid appliance disk or chunk size')
        names = [name] if not chunk else [name + f'.{i:09d}' for i in range((size + chunk - 1) // chunk)]
        by_name = {member.name: member for member in members}
        for index, item in enumerate(names):
            expected = size if not chunk else min(chunk, size - index * chunk)
            if item not in report['supplied_manifest_verified'] or item not in by_name or by_name[item].size != expected:
                raise ValueError('Missing, uncovered or incorrectly sized appliance disk chunk')
        manifests = [member.name for member in members if member.name.endswith('.mf')]
        if len(manifests) != 1 or [member.name for member in members] != [ovf.name, manifests[0], *names]:
            raise ValueError('Unexpected appliance members or ordering')
        report.update(appliance_disk=name, appliance_disk_bytes=size, disk_members=names, chunk_bytes=chunk)
    return report


def export(work, output):
    if any(not path.is_absolute() or path == ROOT or ROOT in path.parents for path in (work, output)):
        raise ValueError('Use absolute private work and release directories outside the source checkout')
    if (work / 'qmp.sock').exists():
        raise RuntimeError('Pilot QMP socket exists; wait for a clean shutdown before export')
    source = work / 'disk.qcow2'
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(source)]))
    if info.get('backing-filename') or info['format'] != 'qcow2':
        raise ValueError('Export requires a stopped standalone QCOW2')
    proof = json.loads((work / 'pilot-shutdown-proof.json').read_text())
    if not all(proof.get(key) is True for key in ('all_guests_stopped', 'portable_management_nic', 'cloud_init_disabled')):
        raise ValueError('Run the guest export preparation and retain its shutdown proof first')
    config = json.loads((work / 'pilot.json').read_text())
    if config.get('attach_backup_disk'):
        raise ValueError('Single-disk OVA export cannot include the attached backup disk')
    if output.exists():
        raise FileExistsError(output)
    # VMDK plus OVA coexist during packing; reserve room for both and metadata.
    if shutil.disk_usage(output.parent).free < info['virtual-size'] * 2 + 8 * 1024**3:
        raise ValueError('Need free space for two full virtual-disk capacities plus an 8-GiB reserve')
    output.mkdir(mode=0o700)
    name = 'heiST-nested-pilot'
    target = output / (name + '.ova')
    with tempfile.TemporaryDirectory(dir=output, prefix='pack-') as folder:
        stage = Path(folder)
        disk = stage / (name + '.vmdk')
        subprocess.run(['qemu-img', 'convert', '-p', '-f', 'qcow2', '-O', 'vmdk', '-o',
                        'subformat=streamOptimized', str(source), str(disk)], check=True)
        ovf = stage / (name + '.ovf')
        chunked = disk.stat().st_size > USTAR_MAX_BYTES
        parts = disk_parts(disk, chunk_bytes=CHUNK_BYTES) if chunked else [{'name': disk.name, 'offset': 0,
                                                  'bytes': disk.stat().st_size, 'sha256': sha256(disk)}]
        ovf.write_bytes(descriptor(name, disk.name, disk.stat().st_size, info['virtual-size'],
                                   config['memory_mib'], config['cpus'], CHUNK_BYTES if chunked else None))
        manifest = stage / (name + '.mf')
        manifest.write_text(f'SHA256({ovf.name})= {sha256(ovf)}\n' + ''.join(
            f'SHA256({part["name"]})= {part["sha256"]}\n' for part in parts))
        with target.open('xb') as stream, tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for path in (ovf, manifest):
                archive.add(path, arcname=path.name)
            with disk.open('rb') as payload:
                for part in parts:
                    payload.seek(part['offset'])
                    member = tarfile.TarInfo(part['name'])
                    member.size, member.mode = part['bytes'], 0o600
                    archive.addfile(member, SliceReader(payload, part['bytes']))
    target.chmod(0o600)
    report = inspect_appliance(target)
    receipt = {'ova': target.name, 'ova_sha256': sha256(target), 'ova_bytes': target.stat().st_size,
               'virtual_disk_bytes': info['virtual-size'], 'memory_mib': config['memory_mib'],
               'vcpus': config['cpus'], 'management_nics': 1, 'cold_import': 'NOT_RUN',
               'chunk_bytes': report['chunk_bytes'],
               'production_accepted': False, 'manifest_verified': report['supplied_manifest_verified']}
    (output / 'appliance-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    shutil.copy2(work / 'pilot-shutdown-proof.json', output / 'pilot-shutdown-proof.json')
    (output / 'README.md').write_text(
        '# Private heiST appliance candidate\n\n'
        'Contains instructor credentials and solutions. Never distribute to students.\n'
        'Cold import and functional acceptance are pending. Enable nested VT-x/AMD-V,\n'
        'use an isolated management network and the declared SATA disk/E1000 NIC.\n'
        'The guest expects management 10.0.2.15/24, gateway 10.0.2.2; adapt this\n'
        'through its console for another isolated network. Its single management\n'
        'NIC is named heistmgmt0 independently of its imported PCI location.\n')
    owner = work.stat()
    for path in [output, *output.rglob('*')]:
        path.chmod(0o700 if path.is_dir() else 0o600)
        if os.geteuid() == 0:
            os.chown(path, owner.st_uid, owner.st_gid)
    print('Exported private appliance candidate; cold import remains required:', target)
    return target


def cold_import(ova, work, access_source):
    if not work.is_absolute() or work == ROOT or ROOT in work.parents or work.exists():
        raise ValueError('Use a new absolute private import workspace outside the source checkout')
    report = inspect_appliance(ova)
    owner = access_source.stat()
    for name in ('id_ed25519', 'known_hosts'):
        if not (access_source / name).is_file():
            raise ValueError('Supply the original private pilot access directory')
    with tarfile.open(ova, 'r:') as archive:
        member = next(item for item in archive.getmembers() if item.name.endswith('.ovf'))
        root = ET.fromstring(archive.extractfile(member).read())
        disk = root.find('.//{' + OVF + '}Disk')
        capacity = int(disk.attrib['{' + OVF + '}capacity'])
        if disk.attrib.get('{' + OVF + '}capacityAllocationUnits') != 'byte':
            raise ValueError('Expected a byte-sized appliance disk capacity')
        hardware = report['hardware']
        cpus = [int(item['VirtualQuantity']) for item in hardware if item.get('ResourceType') == '3']
        memory = [int(item['VirtualQuantity']) for item in hardware if item.get('ResourceType') == '4']
        nics = [item for item in hardware if item.get('ResourceType') == '10']
        if len(cpus) != 1 or len(memory) != 1 or len(nics) != 1 or nics[0].get('ResourceSubType') != 'E1000':
            raise ValueError('Unexpected appliance CPU, memory or NIC declaration')
        if cpus[0] <= 0 or memory[0] <= 0 or capacity <= 0:
            raise ValueError('Invalid appliance resources')
        if shutil.disk_usage(work.parent).free < capacity * 2 + 8 * 1024**3:
            raise ValueError('Need room for the reassembled disk and its independent cold-import copy')
        work.mkdir(mode=0o700)
        with tempfile.TemporaryDirectory(dir=work, prefix='unpack-') as folder:
            vmdk = Path(folder) / report['appliance_disk']
            with vmdk.open('xb') as stream:
                for name in report['disk_members']:
                    with archive.extractfile(name) as source:
                        shutil.copyfileobj(source, stream, length=8 * 1024**2)
            info = json.loads(subprocess.check_output(['qemu-img', 'info', '-f', 'vmdk', '--output=json', str(vmdk)]))
            if info.get('backing-filename') or info['virtual-size'] != capacity:
                raise ValueError('Disk backing dependency or capacity differs from the descriptor')
            subprocess.run(['qemu-img', 'convert', '-p', '-f', 'vmdk', '-O', 'qcow2', str(vmdk), str(work / 'disk.qcow2')], check=True)
    for name in ('id_ed25519', 'id_ed25519.pub', 'known_hosts'):
        if (access_source / name).is_file():
            shutil.copy2(access_source / name, work / name)
            os.chown(work / name, owner.st_uid, owner.st_gid)
            (work / name).chmod(0o600)
    config = {'memory_mib': memory[0], 'cpus': cpus[0], 'attach_seed': False,
              'disk_bus': 'sata', 'nic_model': 'e1000', 'production_accepted': False,
              'source_ova_sha256': sha256(ova), 'cold_import': 'PREPARED_NOT_BOOTED'}
    (work / 'pilot.json').write_text(json.dumps(config, indent=2) + '\n')
    os.chown(work / 'pilot.json', owner.st_uid, owner.st_gid)
    (work / 'pilot.json').chmod(0o600)
    (work / 'disk.qcow2').chmod(0o600)
    os.chown(work, owner.st_uid, owner.st_gid)
    print('Prepared independent cold import with SATA/E1000 and no cloud-init seed; boot and retest it:', work)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('export', 'cold-import'))
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--ova', type=Path)
    parser.add_argument('--access-source', type=Path)
    args = parser.parse_args()
    if args.action == 'export':
        if args.output is None:
            parser.error('export requires --output')
        export(args.work.resolve(), args.output.resolve())
    else:
        if args.ova is None or args.access_source is None:
            parser.error('cold-import requires --ova and --access-source')
        cold_import(args.ova.resolve(), args.work.resolve(), args.access_source.resolve())
