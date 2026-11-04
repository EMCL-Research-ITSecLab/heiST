"""Native normalized import of a private synthetic disk into an unused test VM."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.integration.images.normalization import XML


class NativeImageImportTests(unittest.TestCase):
    def test_real_normalized_import_attaches_expected_disk_and_boot_order(self):
        from heist.infrastructure.proxmox import client
        from heist.platform.images import provision
        from heist.artifacts.normalize import normalize
        vmid = int(os.environ['HEIST_TEST_VMID'])
        self.assertTrue(100 < vmid < 100000000)
        vm = SimpleNamespace(id=vmid)
        self.assertFalse(client.vm_exists_api_call(vm), 'Test VM ID is already occupied')
        with tempfile.TemporaryDirectory(prefix='heist-native-image-import-') as temporary:
            root = Path(temporary)
            raw, vmdk, ova = root/'original.raw', root/'disk.vmdk', root/'test.ova'
            with raw.open('wb') as stream:
                stream.write(b'heiST native private disk import test\n')
                stream.truncate(64*1024**2)
            subprocess.run(['qemu-img','convert','-f','raw','-O','vmdk',str(raw),str(vmdk)],check=True,capture_output=True)
            with tarfile.open(ova,'w',format=tarfile.USTAR_FORMAT) as archive:
                for name,data in [('machine.ovf',XML.replace('SIZE',str(vmdk.stat().st_size)).encode()),('disk.vmdk',vmdk.read_bytes())]:
                    item=tarfile.TarInfo(name);item.size=len(data)
                    archive.addfile(item,io.BytesIO(data))
            try:
                with patch.object(provision,'normalize',side_effect=lambda source,cache:normalize(source,root/'cache',worker=(65534,65534))):
                    receipt=provision.import_normalized(ova,vmid,os.environ.get('HEIST_TEST_STORAGE','local-lvm'))
                self.assertEqual(receipt['disks'][0]['capacity'],64*1024**2)
                config=provision.configuration(vmid)
                self.assertIn('sata0',config)
                self.assertEqual(config['boot'],'order=sata0')
                self.assertEqual(config['bios'],'seabios')
                self.assertFalse(any(key.startswith('net') for key in config))
                self.assertTrue(client.vm_is_stopped_api_call(vm))
            except subprocess.CalledProcessError as error:
                raise RuntimeError(error.stderr.decode(errors='replace')[-4000:]) from error
            finally:
                if client.vm_exists_api_call(vm):
                    provision.configuration(vmid)  # refuse cleanup of an unexpected identity
                    client.delete_vm_api_call(vm)
            self.assertFalse(client.vm_exists_api_call(vm))


if __name__ == '__main__':
    if os.geteuid()!=0 or os.environ.get('HEIST_ISOLATED_IMAGE_TESTS')!='1':
        raise SystemExit('Use only the disposable test host with HEIST_ISOLATED_IMAGE_TESTS=1')
    from dotenv import dotenv_values
    config=dotenv_values(os.environ['HEIST_TEST_BACKEND_ENV'])
    os.environ.update({key:config[key] for key in ('PROXMOX_URL','PROXMOX_HOSTNAME','PROXMOX_API_TOKEN') if config.get(key)})
    unittest.main(verbosity=2)
