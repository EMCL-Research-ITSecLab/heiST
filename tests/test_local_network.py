from pathlib import Path
import json
from tempfile import TemporaryDirectory
from unittest import TestCase
from nested_pilot import management_network, management_ports, PORTS, ssh_args
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

    def test_concurrent_pilot_proof_and_ssh_require_its_own_ports(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            ports = {name: value + 10000 for name, value in PORTS.items()}
            (work / 'pilot.json').write_text(json.dumps({'ports': ports}))
            network = management_network({'ports': ports})
            command = ['qemu-system-x86_64', '-drive', f'file={work}/disk.qcow2,format=qcow2', '-netdev', network]
            self.assertEqual(len(validate_command(command, work)), 64)
            self.assertEqual(ssh_args(work)[2], str(ports['ssh']))
            self.assertIn('hostfwd=tcp:127.0.0.1:32220-:22', network)
            for wrong in (management_network({}), management_network({'ports': ports}, online=True)):
                with self.subTest(network=wrong), self.assertRaises(RuntimeError):
                    validate_command(command[:-1] + [wrong], work)

    def test_invalid_port_profiles_cannot_generate_a_network_or_ssh_command(self):
        for ports in (None, [], {}, {**PORTS, 'extra': 12345},
                      {**PORTS, 'ssh': True}, {**PORTS, 'ssh': '22220'},
                      {**PORTS, 'ssh': 22}, {**PORTS, 'ssh': 65536},
                      {**PORTS, 'ssh': PORTS['web']}):
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                management_ports({'ports': ports})
        self.assertEqual(management_ports({}), PORTS)
