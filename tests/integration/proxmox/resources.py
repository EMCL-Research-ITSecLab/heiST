#!/usr/bin/env python3
"""Explicit native VM resource rehearsal on an isolated disposable Proxmox host.

Uses an empty diskless VM with no NIC and a unique name. Refuses an occupied VM
ID and never destroys a VM whose name does not match this invocation.
"""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid


class ResourceTests(unittest.TestCase):
    def test_native_start_stop_template_and_confirmed_delete(self):
        from heist.infrastructure.proxmox import client
        from heist.infrastructure.proxmox.tasks import wait_for_task
        vm = SimpleNamespace(id=int(os.environ['HEIST_TEST_VMID']))
        self.assertGreater(vm.id, 100)
        self.assertLess(vm.id, 100000000)
        self.assertFalse(client.vm_exists_api_call(vm), 'Choose an unused disposable VM ID')
        name = 'heist-resource-test-'+uuid.uuid4().hex[:10]
        endpoint = f'api2/json/nodes/{client.node}/qemu'
        created = False
        try:
            created = True
            result = client.make_api_call('POST', endpoint, {'vmid': vm.id, 'name': name, 'memory': 128, 'cores': 1, 'sockets': 1, 'kvm': 0, 'onboot': 0})
            if isinstance(result.get('data'), str) and result['data'].startswith('UPID:'):
                wait_for_task(client.make_api_call, client.node, result, timeout=30)
            self.assertTrue(client.vm_exists_api_call(vm))
            self.assertTrue(client.vm_is_stopped_api_call(vm))
            self.assertFalse(client.vm_is_template_api_call(vm))
            wait_for_task(client.make_api_call, client.node, client.launch_vm_api_call(vm), timeout=30)
            self.assertFalse(client.vm_is_stopped_api_call(vm))
            client.stop_vm_api_call(vm)
            self.assertTrue(client.vm_is_stopped_api_call(vm))
            result = client.convert_vm_to_template_api_call(vm.id)
            if isinstance(result.get('data'), str) and result['data'].startswith('UPID:'):
                wait_for_task(client.make_api_call, client.node, result, timeout=30)
            self.assertTrue(client.vm_is_template_api_call(vm))
            client.delete_vm_api_call(vm)
            self.assertFalse(client.vm_exists_api_call(vm))
            self.assertTrue(client.delete_vm_api_call(vm)['already_absent'])
        finally:
            if created and client.vm_exists_api_call(vm):
                configuration = client.make_api_call('GET', endpoint+'/'+str(vm.id)+'/config')['data']
                self.assertEqual(configuration['name'], name, 'Refusing cleanup of an unexpected VM identity')
                client.stop_vm_api_call(vm)
                client.delete_vm_api_call(vm)


if __name__ == '__main__':
    if os.environ.get('HEIST_ISOLATED_PROXMOX_TESTS') != '1' or not os.environ.get('HEIST_TEST_VMID'):
        raise SystemExit('Requires an isolated Proxmox host, HEIST_ISOLATED_PROXMOX_TESTS=1 and an unused HEIST_TEST_VMID')
    from dotenv import dotenv_values
    path = Path(os.environ.get('HEIST_TEST_BACKEND_ENV', ''))
    if not path.is_absolute() or not path.is_file():
        raise SystemExit('Set HEIST_TEST_BACKEND_ENV to the private test-host configuration file')
    values = dotenv_values(path)
    os.environ.update({key: values[key] for key in ('PROXMOX_URL', 'PROXMOX_HOSTNAME', 'PROXMOX_API_TOKEN') if values.get(key)})
    unittest.main(verbosity=2)
