"""Bounded OVA envelope inspection without extracting or opening disk images.

This accepts regular-file USTAR/GNU archives with a single UTF-8 OVF and VMDKs.
Extended/sparse headers, links and unexpected payloads are deliberately refused.
OVF capacity is an untrusted declaration: sandboxed disk inspection and conversion
must independently verify it before an image can become available for exercises.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import tarfile
import xml.etree.ElementTree as ET

GIB = 1024**3
OVF = 'http://schemas.dmtf.org/ovf/envelope/1'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z')


class InvalidOva(ValueError):
    """The archive cannot safely enter the image inspection workflow."""


@dataclass(frozen=True)
class Limits:
    archive_bytes: int = 17*GIB
    disk_bytes: int = 16*GIB
    total_disk_bytes: int = 16*GIB
    virtual_bytes: int = 16*GIB
    disks: int = 8
    entries: int = 32
    ovf_bytes: int = 1024**2
    manifest_bytes: int = 65536

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError('OVA limits must be positive integers')


@dataclass(frozen=True)
class Member:
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class Disk:
    member: Member
    declared_capacity: int


@dataclass(frozen=True)
class Envelope:
    descriptor: str
    disks: tuple[Disk, ...]
    archive_bytes: int


def read_exact(stream, size):
    value = stream.read(size)
    if len(value) != size:
        raise InvalidOva('Truncated OVA archive')
    return value


def members(stream, length, limits):
    """Parse only fixed-size headers; never let tarfile consume PAX/GNU metadata."""
    values = {}
    while stream.tell()+512 <= length:
        header = read_exact(stream, 512)
        if header == bytes(512):
            if read_exact(stream, 512) != bytes(512):
                raise InvalidOva('OVA must end with two zero blocks')
            while chunk := stream.read(65536):
                if any(chunk):
                    raise InvalidOva('Unexpected data after OVA end marker')
            return values
        if len(values) >= limits.entries:
            raise InvalidOva('Too many OVA entries')
        if header[257:263] not in (b'ustar\x00', b'ustar '):
            raise InvalidOva('OVA requires USTAR headers')
        try:
            item = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
        except (tarfile.HeaderError, UnicodeError, ValueError):
            raise InvalidOva('Invalid OVA header') from None
        if item.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or item.linkname:
            raise InvalidOva('OVA entries must be regular files without extensions or links')
        if not NAME.fullmatch(item.name) or '..' in item.name or item.name in values:
            raise InvalidOva('Unsafe or duplicate OVA filename')
        suffix = Path(item.name).suffix.lower()
        bound = {'.ovf': limits.ovf_bytes, '.mf': limits.manifest_bytes, '.vmdk': limits.disk_bytes}.get(suffix)
        if bound is None or not 0 < item.size <= bound:
            raise InvalidOva('Unexpected OVA member or member size')
        end = stream.tell()+((item.size+511)//512)*512
        if end > length:
            raise InvalidOva('Truncated OVA member')
        values[item.name] = Member(item.name, stream.tell(), item.size)
        stream.seek(end)
    raise InvalidOva('Missing OVA end marker')


def capacity(value, units, maximum):
    if not value or not re.fullmatch(r'[0-9]{1,20}', value):
        raise InvalidOva('Invalid declared disk capacity')
    units = (units or 'byte').strip().lower()
    exponent = {'byte': 0, 'bytes': 0, 'kb': 10, 'kilobytes': 10,
                'mb': 20, 'megabytes': 20, 'gb': 30, 'gigabytes': 30,
                'tb': 40, 'terabytes': 40}.get(units)
    if exponent is None:
        match = re.fullmatch(r'byte\s*\*\s*2\s*\^\s*([0-9]{1,2})', units)
        if match:
            exponent = int(match[1])
    if exponent is None or exponent > 40:
        raise InvalidOva('Unsupported declared capacity unit')
    size = int(value)*(2**exponent)
    if not 0 < size <= maximum:
        raise InvalidOva('Declared virtual disk size exceeds limit')
    return size


def descriptor(content, entries, limits):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeError:
        raise InvalidOva('OVF must use UTF-8') from None
    if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.IGNORECASE):
        raise InvalidOva('OVF declarations and entities are forbidden')
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        raise InvalidOva('Invalid OVF XML') from None
    if root.tag != '{'+OVF+'}Envelope':
        raise InvalidOva('Invalid OVF namespace or envelope')
    if len(root.findall('.//{'+OVF+'}VirtualSystem')) > 1:
        raise InvalidOva('Import one virtual machine per OVA')
    # The supported importer creates a BIOS/SATA VM. Do not silently publish an
    # explicitly EFI-only image as compatible with that hardware profile.
    for item in root.iter():
        local = item.tag.rsplit('}', 1)[-1].lower()
        attributes = {name.rsplit('}', 1)[-1].lower(): value.strip().lower()
                      for name, value in item.attrib.items()}
        if local == 'config' and attributes.get('key', '').lower() == 'firmware':
            if attributes.get('value') not in ('bios', 'seabios'):
                raise InvalidOva('Only BIOS firmware is currently supported')
        if local == 'firmware' and (attributes.get('type') or (item.text or '').strip().lower()) not in ('bios', 'seabios'):
            raise InvalidOva('Only BIOS firmware is currently supported')
        if local == 'config' and attributes.get('key', '').lower() in ('secureboot', 'uefi.secureboot.enabled') and attributes.get('value') not in ('false', '0'):
            raise InvalidOva('Secure Boot images require an EFI importer')
    attribute = lambda name: '{'+OVF+'}'+name
    references = {}
    for item in root.findall('./{'+OVF+'}References/{'+OVF+'}File'):
        identifier, name = item.get(attribute('id')), item.get(attribute('href'))
        if not identifier or identifier in references or name not in entries or name in references.values():
            raise InvalidOva('Invalid or duplicate OVF file reference')
        if not name.lower().endswith('.vmdk'):
            raise InvalidOva('Only embedded VMDKs may be referenced')
        declared = item.get(attribute('size'))
        if declared is not None and (not re.fullmatch(r'[0-9]{1,20}', declared) or int(declared) != entries[name].size):
            raise InvalidOva('OVF file size does not match the archive')
        if item.get(attribute('compression')) or item.get(attribute('chunkSize')):
            raise InvalidOva('Compressed or chunked OVF files are unsupported')
        references[identifier] = name
    disks, identities, names = [], set(), set()
    for item in root.findall('./{'+OVF+'}DiskSection/{'+OVF+'}Disk'):
        identity, reference = item.get(attribute('diskId')), item.get(attribute('fileRef'))
        name = references.get(reference)
        if not identity or identity in identities or not name or name in names:
            raise InvalidOva('Disk must uniquely reference an embedded VMDK')
        identities.add(identity)
        names.add(name)
        disks.append(Disk(entries[name], capacity(item.get(attribute('capacity')), item.get(attribute('capacityAllocationUnits')), limits.virtual_bytes)))
    archived = {name for name in entries if name.lower().endswith('.vmdk')}
    if not 1 <= len(disks) <= limits.disks or names != archived or set(references.values()) != names:
        raise InvalidOva('OVF disks and archived VMDKs must match exactly')
    if sum(d.declared_capacity for d in disks) > limits.virtual_bytes:
        raise InvalidOva('Total declared virtual size exceeds limit')
    return tuple(disks)


def inspect_envelope(path, limits=Limits()):
    """Inspect a private staged regular file. No extraction or disk parser runs.

    A successful result is not import authorization. The upload worker must retain
    exclusive ownership of the staged file and independently inspect disk content.
    Optional manifests are bounded payloads, not authenticated signatures.
    """
    descriptor_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor_fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 1024 <= before.st_size <= limits.archive_bytes or before.st_size % 512:
            raise InvalidOva('OVA must be a bounded uncompressed regular archive')
        entries = members(stream, before.st_size, limits)
        ovfs = [item for item in entries.values() if item.name.lower().endswith('.ovf')]
        if len(ovfs) != 1 or sum(name.lower().endswith('.mf') for name in entries) > 1:
            raise InvalidOva('OVA requires one descriptor and at most one manifest')
        if sum(item.size for item in entries.values() if item.name.lower().endswith('.vmdk')) > limits.total_disk_bytes:
            raise InvalidOva('Total disk payload exceeds limit')
        ovf = ovfs[0]
        stream.seek(ovf.offset)
        disks = descriptor(read_exact(stream, ovf.size), entries, limits)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise InvalidOva('OVA changed during inspection')
        return Envelope(ovf.name, disks, before.st_size)
