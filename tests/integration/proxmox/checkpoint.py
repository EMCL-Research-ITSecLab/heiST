"""Native template VMA backup/corruption/restore on a disposable Proxmox host.

Creates one stopped, tagged 1-GiB sparse template with no NIC, verifies its VMA,
alters guest disk bytes, restores the checkpoint, confirms content and identity,
then removes only the VM created by this test. Existing VMs are never overwritten.
"""
import glob
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import uuid


class TemplateRecoveryTests(unittest.TestCase):
    def test_native_verified_archive_recovers_identity_and_original_guest_bytes(self):
        from heist.infrastructure.proxmox import client
        from heist.infrastructure.proxmox.tasks import wait_for_task
        from heist.rollout.controller import Transaction
        from heist.rollout.pve import PVE
        from heist.rollout.proxmox_api import LocalAPI
        from heist.rollout.tasks import Tasks
        from heist.rollout.template_checkpoint import identity,require_same_vm
        vm=SimpleNamespace(id=int(os.environ['HEIST_TEST_VMID']),vmid=int(os.environ['HEIST_TEST_VMID']))
        self.assertGreater(vm.id,100)
        self.assertFalse(client.vm_exists_api_call(vm),'Use an unused disposable template VM ID')
        name='heist-recovery-test-'+uuid.uuid4().hex[:10]
        storage=os.environ.get('HEIST_TEST_STORAGE','local')
        adapter=PVE.__new__(PVE);adapter.node=socket.gethostname().split('.')[0]
        api=LocalAPI();adapter.request=api.request
        adapter.tasks=Tasks(adapter.node,adapter.request)
        endpoint=f'api2/json/nodes/{client.node}/qemu'
        attempted=False
        expected=None
        with tempfile.TemporaryDirectory(prefix='heist-native-template-checkpoint-',dir=os.environ['HEIST_TEST_BACKUP_DIRECTORY']) as temporary:
            root=Path(temporary)
            transaction=Transaction(root/'transaction',{'backup_directory':str(root)})
            transaction.path.mkdir(mode=0o700)
            try:
                attempted=True
                result=client.make_api_call('POST',endpoint,{'vmid':vm.id,'name':name,'memory':128,'cores':1,'onboot':0,
                    'sata0':storage+':1','tags':client.ownership_tags(vm.id),'description':client.ownership_marker(vm.id,template=True)})
                if result.get('data'):wait_for_task(client.make_api_call,client.node,result,timeout=60)
                def disk():
                    volume=adapter.configuration(vm)['sata0'].split(',')[0]
                    return adapter.command(['pvesm','path',volume]).decode().strip()
                adapter.command(['qemu-io','-c','write -P 0x5a 0 4096',disk()])
                result=client.convert_vm_to_template_api_call(vm.id)
                if result.get('data'):wait_for_task(client.make_api_call,client.node,result,timeout=60)
                configuration=adapter.configuration(vm);expected=identity(configuration)
                adapter.tasks.run(transaction,'backup-template','/nodes/'+adapter.node+'/vzdump',
                    {'vmid':vm.id,'mode':'stop','compress':'zstd','dumpdir':str(root),'remove':0})
                archives=list(root.glob('vzdump-qemu-'+str(vm.id)+'-*.vma.zst'))
                self.assertEqual(len(archives),1)
                adapter._verify_archive(transaction,archives[0])
                # Only this invocation's disposable template is modified. PVE
                # protects base images with the immutable filesystem flag.
                require_same_vm(adapter.configuration(vm),expected)
                adapter.command(['chattr','-i',disk()])
                adapter.command(['qemu-io','-c','write -P 0x33 0 4096',disk()])
                require_same_vm(adapter.configuration(vm),expected)
                adapter.tasks.run(transaction,'restore-template','/nodes/'+adapter.node+'/qemu',
                    {'archive':str(archives[0]),'vmid':vm.id,'force':1})
                require_same_vm(adapter.configuration(vm),expected)
                adapter.command(['qemu-io','-r','-c','read -P 0x5a 0 4096',disk()])
                self.assertTrue(client.vm_is_stopped_api_call(vm))
                self.assertTrue(client.vm_is_template_api_call(vm))
            except subprocess.CalledProcessError as error:
                raise RuntimeError(error.stderr.decode(errors='replace')[-2048:]) from error
            finally:
                if attempted and client.vm_exists_api_call(vm):
                    value=adapter.configuration(vm)
                    self.assertEqual(value['name'],name,'Refusing cleanup of a foreign VM')
                    if expected:require_same_vm(value,expected)
                    client.delete_vm_api_call(vm)
            self.assertFalse(client.vm_exists_api_call(vm))


if __name__=='__main__':
    if os.geteuid()!=0 or os.environ.get('HEIST_ISOLATED_PROXMOX_TESTS')!='1':
        raise SystemExit('Requires root on a disposable Proxmox host and HEIST_ISOLATED_PROXMOX_TESTS=1')
    if not os.environ.get('HEIST_TEST_VMID','').isdigit() or not Path(os.environ.get('HEIST_TEST_BACKUP_DIRECTORY','')).is_absolute():
        raise SystemExit('Declare an unused HEIST_TEST_VMID and independent HEIST_TEST_BACKUP_DIRECTORY')
    from dotenv import dotenv_values
    values=dotenv_values(os.environ['HEIST_TEST_BACKEND_ENV'])
    os.environ.update({key:values[key] for key in ('PROXMOX_URL','PROXMOX_HOSTNAME','PROXMOX_API_TOKEN') if values.get(key)})
    unittest.main(verbosity=2)
