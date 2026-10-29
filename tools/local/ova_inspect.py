#!/usr/bin/env python3
"""Inspect OVAs without booting them; optionally extract one disk into a private build directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import xml.etree.ElementTree as ET


def inspect(path, verify=False, extract=None):
    report = {'source_name': path.name, 'source_bytes': path.stat().st_size,
              'patch_state': 'UNKNOWN_UNTIL_GUEST_INVENTORY', 'boot_verified': False}
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('OVA contains duplicate member names')
        for member in members:
            parts = PurePosixPath(member.name)
            if parts.is_absolute() or '..' in parts.parts or not member.isfile():
                raise ValueError(f'Unsupported/unsafe OVA member: {member.name}')
        descriptors = [m for m in members if m.name.endswith('.ovf')]
        disks = [m for m in members if m.name.endswith('.vmdk')]
        if len(descriptors) != 1 or descriptors[0].size > 4*1024*1024:
            raise ValueError('Expected one reasonably sized OVF')
        root = ET.fromstring(archive.extractfile(descriptors[0]).read())
        ns = {'ovf': 'http://schemas.dmtf.org/ovf/envelope/1',
              'rasd': 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData'}
        os_section = root.find('.//ovf:OperatingSystemSection', ns)
        report['declared_os'] = os_section.findtext('ovf:Description', namespaces=ns) if os_section is not None else None
        report['disks'] = [dict(name=m.name, bytes=m.size) for m in disks]
        report['hardware'] = []
        for item in root.findall('.//ovf:VirtualHardwareSection/ovf:Item', ns):
            data = {child.tag.split('}')[-1]: child.text for child in item}
            report['hardware'].append({k: data[k] for k in ('ResourceType', 'ResourceSubType', 'VirtualQuantity', 'HostResource') if k in data})
        if verify:
            manifests = [m for m in members if m.name.endswith('.mf')]
            if len(manifests) != 1 or manifests[0].size > 1024*1024:
                raise ValueError('Expected one checksum manifest')
            checks = {}
            for line in archive.extractfile(manifests[0]).read().decode('utf-8-sig').splitlines():
                if not line.strip():
                    continue
                match = re.fullmatch(r'(SHA1|SHA256)\s*\((.+)\)\s*=\s*([a-fA-F0-9]+)', line.strip())
                if not match or match[2] not in names:
                    raise ValueError('Unsupported manifest record')
                digest = hashlib.new(match[1].lower())
                with archive.extractfile(match[2]) as stream:
                    for block in iter(lambda: stream.read(8*1024*1024), b''):
                        digest.update(block)
                if digest.hexdigest().lower() != match[3].lower():
                    raise ValueError(f'Checksum mismatch: {match[2]}')
                checks[match[2]] = match[1]
            if not {descriptors[0].name, *(m.name for m in disks)} <= checks.keys():
                raise ValueError('Descriptor and every disk must be covered by the manifest')
            report['supplied_manifest_verified'] = checks
        if extract:
            if len(disks) != 1:
                raise ValueError('The disposable probe supports one guest disk only')
            extract.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(extract, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output, archive.extractfile(disks[0]) as stream:
                shutil.copyfileobj(stream, output, length=8*1024*1024)
            report['extracted_disk'] = str(extract)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ova', type=Path)
    p.add_argument('--verify', action='store_true')
    p.add_argument('--extract-disk', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    report = inspect(a.ova, a.verify, a.extract_disk)
    value = json.dumps(report, indent=2) + '\n'
    if a.output:
        with os.fdopen(os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write(value)
    print(value, end='')
