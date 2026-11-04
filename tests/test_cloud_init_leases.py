"""Crash-safe shared IP allocation, including process contention and gateway exclusion."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from heist.infrastructure.network.cloud_init_pool import IPPoolManager


def allocate(value):
    directory,vm_id=value
    return IPPoolManager(directory,network='10.32.0.0/29').allocate_ip(vm_id,timeout=0)


def lease_then_exit(directory):
    IPPoolManager(directory,network='10.32.0.0/29').allocate_ip(100)
    os._exit(23)


class CloudInitLeaseTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'leases'

    def test_process_restart_retains_lease_and_never_allocates_the_gateway(self):
        process=multiprocessing.get_context('fork').Process(target=lease_then_exit,args=(self.root,))
        process.start();process.join(10)
        self.assertEqual(process.exitcode,23)
        restarted=IPPoolManager(self.root,network='10.32.0.0/29')
        self.assertEqual(restarted.get_allocated_ip(100),'10.32.0.2')
        self.assertEqual(restarted.allocate_ip(100),'10.32.0.2')
        self.assertEqual(restarted.allocate_ip(101),'10.32.0.3')
        self.assertFalse(restarted.is_ip_allocated('10.32.0.1'))
        with self.assertRaises(RuntimeError):
            restarted.cleanup()
        with self.assertRaises(ValueError):
            restarted.allocate_ip(100,reuse_existing=False)

    def test_independent_processes_claim_different_addresses_without_overwriting(self):
        # Initialize once so every child tests contention on the same database.
        manager=IPPoolManager(self.root,network='10.32.0.0/29')
        self.assertEqual(manager.get_pool_status()['allocated_ips'],0)
        with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('fork')) as pool:
            addresses=list(pool.map(allocate,[(self.root,vm) for vm in range(200,204)]))
        self.assertEqual(len(set(addresses)),4)
        self.assertNotIn('10.32.0.1',addresses)
        self.assertEqual(manager.get_pool_status()['allocated_vms'],[200,201,202,203])

    def test_exhaustion_is_bounded_and_release_returns_only_the_owned_lease(self):
        manager=IPPoolManager(self.root,network='10.32.0.0/30')
        self.assertEqual(manager.allocate_ip(1),'10.32.0.2')
        self.assertIsNone(manager.allocate_ip(2,timeout=0))
        self.assertFalse(manager.release_ip(999))
        self.assertTrue(manager.release_ip(1))
        self.assertEqual(manager.allocate_ip(2,timeout=0),'10.32.0.2')
        with self.assertRaises(ValueError):
            IPPoolManager(self.root,network='10.32.1.0/30').get_pool_status()
        for value in (True,0,-1,2**63):
            with self.assertRaises(ValueError):
                manager.allocate_ip(value)
