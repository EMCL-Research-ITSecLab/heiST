from pathlib import Path
from unittest import TestCase
from verify_pilot_offline import validate_command


class LocalNetworkTests(TestCase):
    def test_online_extra_network_and_wrong_disk_are_rejected(self):
        network = 'user,id=mgmt,restrict=on,hostfwd=tcp:127.0.0.1:22220-:22,hostfwd=tcp:127.0.0.1:18443-:443,hostfwd=tcp:127.0.0.1:18006-:8006,hostfwd=udp:127.0.0.1:11194-:1194'
        good = ['qemu-system-x86_64', '-drive', 'file=/tmp/local-test/disk.qcow2,format=qcow2', '-netdev', network]
        self.assertEqual(len(validate_command(good, Path('/tmp/local-test'))), 64)
        for bad in (good[:-1] + [network.replace('restrict=on', 'restrict=off')], good + ['-nic', 'user'],
                    good + ['-netdev', 'user,id=extra'], good):
            work = Path('/tmp/wrong') if bad is good else Path('/tmp/local-test')
            with self.subTest(command=bad), self.assertRaises(RuntimeError):
                validate_command(bad, work)
