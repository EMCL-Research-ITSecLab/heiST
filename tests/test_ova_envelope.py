"""Adversarial intake tests use tiny synthetic archives, never real VM images."""
from dataclasses import replace
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from heist.artifacts.ova import InvalidOva, Limits, inspect_envelope

XML = b'''<?xml version="1.0"?><Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1"><References><File ovf:id="f1" ovf:href="disk.vmdk" ovf:size="4"/></References><DiskSection><Disk ovf:diskId="d1" ovf:fileRef="f1" ovf:capacity="10" ovf:capacityAllocationUnits="byte * 2^30"/></DiskSection></Envelope>'''


class OvaEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)/'upload.ova'

    def archive(self, xml=XML, extra=(), format=tarfile.USTAR_FORMAT):
        with tarfile.open(self.path, 'w', format=format) as archive:
            for name, data in [('machine.ovf', xml), ('disk.vmdk', b'disk'), *extra]:
                item = tarfile.TarInfo(name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        return self.path

    def test_offsets_reference_only_embedded_files_and_capacity_units(self):
        result = inspect_envelope(self.archive(extra=[('machine.mf', b'manifest')]))
        self.assertEqual(result.descriptor, 'machine.ovf')
        self.assertEqual(result.disks[0].declared_capacity, 10*1024**3)
        with self.path.open('rb') as stream:
            stream.seek(result.disks[0].member.offset)
            self.assertEqual(stream.read(result.disks[0].member.size), b'disk')
        # Payload is deliberately not a VMDK. Envelope success must never be
        # presented as disk/content validation or permission to import.

    def test_links_extended_headers_and_special_files_are_refused(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.DIRTYPE,
                     tarfile.GNUTYPE_SPARSE, tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME):
            with self.subTest(kind=kind):
                with tarfile.open(self.path, 'w', format=tarfile.USTAR_FORMAT) as archive:
                    item = tarfile.TarInfo('special.ovf')
                    item.type = kind
                    archive.addfile(item)
                with self.assertRaises(InvalidOva):
                    inspect_envelope(self.path)

    def test_paths_duplicates_and_unexpected_payloads_are_refused(self):
        for name in ('../escape', '/absolute', 'sub/disk.vmdk', 'a\\b.vmdk', 'disk.vmdk',
                     'script.sh', 'a..vmdk', 'disk%2evmdk', 'other.ovf'):
            with self.subTest(name=name), self.assertRaises(InvalidOva):
                inspect_envelope(self.archive(extra=[(name, b'x')]))

    def test_entity_doctype_invalid_xml_and_utf16_are_refused(self):
        for value in (b'<!DOCTYPE Envelope [<!ENTITY x "boom">]>'+XML,
                      b'<!doctype Envelope>'+XML, b'<Envelope>', XML.decode().encode('utf-16'),
                      XML.replace(b'/ovf/envelope/1', b'/unknown')):
            with self.subTest(xml=value[:30]), self.assertRaises(InvalidOva):
                inspect_envelope(self.archive(value))

    def test_every_disk_requires_unique_local_reference_and_real_size(self):
        for old, new in ((b'disk.vmdk', b'https://host/disk.vmdk'), (b'size="4"', b'size="5"'),
                         (b'fileRef="f1"', b'fileRef="missing"'), (b'capacity="10"', b'capacity="-1"'),
                         (b'capacity="10"', b'capacity="999999999999999999999999"'),
                         (b'byte * 2^30', b'byte * 2^99'),
                         (b'</DiskSection>', b'<Disk ovf:diskId="d1" ovf:fileRef="f1" ovf:capacity="1"/></DiskSection>'),
                         (b'ovf:size="4"', b'ovf:size="4" ovf:compression="gzip"')):
            with self.subTest(change=new), self.assertRaises(InvalidOva):
                inspect_envelope(self.archive(XML.replace(old, new)))
        with self.assertRaises(InvalidOva):
            inspect_envelope(self.archive(extra=[('unused.vmdk', b'payload')]))

    def test_size_entry_virtual_and_descriptor_limits_are_enforced(self):
        path = self.archive()
        for limits in (replace(Limits(), archive_bytes=512), replace(Limits(), disk_bytes=3),
                       replace(Limits(), total_disk_bytes=3), replace(Limits(), virtual_bytes=1024),
                       replace(Limits(), entries=1), replace(Limits(), ovf_bytes=20)):
            with self.subTest(limits=limits), self.assertRaises(InvalidOva):
                inspect_envelope(path, limits)
        with self.assertRaises(ValueError):
            Limits(disks=True)

    def test_corruption_truncation_concatenation_compression_and_symlink(self):
        self.archive()
        original = self.path.read_bytes()
        for data in (original[:800], original[:2560], original+b'x'*512,
                     b'X'+original[1:], b'\x1f\x8b'+original[2:]):
            with self.subTest(length=len(data)), self.assertRaises(InvalidOva):
                self.path.write_bytes(data)
                inspect_envelope(self.path)
        self.path.write_bytes(original)
        link = self.path.with_name('link.ova')
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            inspect_envelope(link)

    def test_non_regular_input_is_rejected_without_blocking(self):
        os.mkfifo(self.path)
        with self.assertRaises(InvalidOva):
            inspect_envelope(self.path)
