"""Native namespace/QEMU normalization; creates only private synthetic images."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from heist.artifacts.normalize import normalize, verify

XML = '''<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1"><References><File ovf:id="f1" ovf:href="disk.vmdk" ovf:size="SIZE"/></References><DiskSection><Disk ovf:diskId="d1" ovf:fileRef="f1" ovf:capacity="67108864"/></DiskSection></Envelope>'''


class NativeDiskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='heist-private-disk-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ova = self.root/'test.ova'

    def archive(self, disk):
        with tarfile.open(self.ova, 'w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in [('machine.ovf', XML.replace('SIZE', str(len(disk))).encode()), ('disk.vmdk', disk)]:
                item = tarfile.TarInfo(name)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))

    def test_native_conversion_preserves_disk_bytes_and_reuses_only_verified_cache(self):
        raw = self.root/'original.raw'
        with raw.open('wb') as stream:
            stream.write(b'heiST isolated disk normalization test\n')
            stream.truncate(64*1024**2)
        disk = self.root/'source.vmdk'
        subprocess.run(['qemu-img', 'convert', '-f', 'raw', '-O', 'vmdk', str(raw), str(disk)], check=True, capture_output=True)
        self.archive(disk.read_bytes())
        directory, receipt = normalize(self.ova, self.root/'cache', worker=(65534,65534))
        subprocess.run(['qemu-img', 'compare', '-f', 'raw', '-F', 'qcow2', str(raw), str(directory/'disk0.qcow2')], check=True, capture_output=True)
        self.assertEqual(normalize(self.ova, self.root/'cache', worker=(65534,65534)), (directory, receipt))
        with (directory/'disk0.qcow2').open('ab') as stream:
            stream.write(b'tamper')
        with self.assertRaises(ValueError):
            verify(directory, receipt['source_sha256'])

    def test_absolute_external_extent_cannot_access_host_configuration(self):
        descriptor = b'''# Disk DescriptorFile
version=1
CID=fffffffe
parentCID=ffffffff
createType="monolithicFlat"
RW 131072 FLAT "/etc/passwd" 0
'''
        self.archive(descriptor)
        with self.assertRaises(subprocess.CalledProcessError):
            normalize(self.ova, self.root/'cache', worker=(65534,65534))
        self.assertEqual(list((self.root/'cache').glob('*/receipt.json')), [])


if __name__ == '__main__':
    if os.geteuid() != 0 or os.environ.get('HEIST_ISOLATED_IMAGE_TESTS') != '1':
        raise SystemExit('Run only as root on the disposable test host with HEIST_ISOLATED_IMAGE_TESTS=1')
    unittest.main(verbosity=2)
