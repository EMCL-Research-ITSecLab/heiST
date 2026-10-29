import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pilot_appliance as appliance


class PilotApplianceTests(unittest.TestCase):
    def test_live_pilot_is_rejected_before_conversion_or_destination_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'qmp.sock').touch()
            output = work / 'release'
            with patch('pilot_appliance.subprocess.check_output') as command:
                with self.assertRaisesRegex(RuntimeError, 'clean shutdown'):
                    appliance.export(work, output)
                command.assert_not_called()
            self.assertFalse(output.exists())

    def test_descriptor_declares_one_management_nic_and_exact_capacity(self):
        root = ET.fromstring(appliance.descriptor('pilot', 'disk.vmdk', 100, 256 * 1024**3, 49152, 12))
        ns = {'ovf': appliance.OVF, 'rasd': appliance.RASD}
        disk = root.find('.//ovf:Disk', ns)
        self.assertEqual(disk.get('{' + appliance.OVF + '}capacity'), str(256 * 1024**3))
        nics = [item for item in root.findall('.//ovf:Item', ns) if item.findtext('rasd:ResourceType', namespaces=ns) == '10']
        self.assertEqual(len(nics), 1)
        self.assertEqual(nics[0].findtext('rasd:Connection', namespaces=ns), 'management')
        self.assertEqual(nics[0].findtext('rasd:ResourceSubType', namespaces=ns), 'E1000')

    def fixture(self, folder):
        work, output = folder / 'work', folder / 'release'
        work.mkdir()
        (work / 'disk.qcow2').write_bytes(b'fixture')
        (work / 'pilot.json').write_text(json.dumps({'memory_mib': 49152, 'cpus': 12}))
        (work / 'pilot-shutdown-proof.json').write_text(json.dumps({
            'all_guests_stopped': True, 'portable_management_nic': True, 'cloud_init_disabled': True}))
        payload = b'complete guest disk payload fixture'
        def convert(argv, **kwargs):
            Path(argv[-1]).write_bytes(payload)
        with patch('pilot_appliance.subprocess.check_output', return_value=b'{"format":"qcow2","virtual-size":1024}'), patch('pilot_appliance.subprocess.run', side_effect=convert), patch('pilot_appliance.shutil.disk_usage', return_value=SimpleNamespace(free=1024**4)), patch('pilot_appliance.USTAR_MAX_BYTES', 16), patch('pilot_appliance.CHUNK_BYTES', 7):
            path = appliance.export(work, output)
        return path, payload

    def test_chunked_archive_roundtrip_covers_every_byte_with_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path, payload = self.fixture(Path(directory))
            report = appliance.inspect_appliance(path)
            self.assertGreater(len(report['disk_members']), 1)
            with tarfile.open(path) as archive:
                recovered = b''.join(archive.extractfile(name).read() for name in report['disk_members'])
            self.assertEqual(recovered, payload)

    def test_manifest_cannot_omit_a_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.fixture(Path(directory))
            altered = Path(directory) / 'uncovered.ova'
            with tarfile.open(path) as source, tarfile.open(altered, 'w', format=tarfile.USTAR_FORMAT) as target:
                for member in source.getmembers():
                    body = source.extractfile(member).read()
                    if member.name.endswith('.mf'):
                        body = b'\n'.join(body.splitlines()[:-1]) + b'\n'
                    item = tarfile.TarInfo(member.name)
                    item.size = len(body)
                    target.addfile(item, io.BytesIO(body))
            with self.assertRaisesRegex(ValueError, 'uncovered'):
                appliance.inspect_appliance(altered)
