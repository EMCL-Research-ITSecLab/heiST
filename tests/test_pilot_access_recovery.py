"""Serial recovery must prove local isolation before reading/sending credentials."""
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock

from tools.local.nested_pilot import management_network, ssh_args
from tools.local.recover_pilot_access import authorize, receive, validate


class PilotAccessTests(unittest.TestCase):
    def test_cold_import_requires_the_existing_host_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            (work/'pilot.json').write_text(json.dumps({'attach_seed':False}))
            self.assertIn('StrictHostKeyChecking=yes',ssh_args(work))
            self.assertIn('ForwardAgent=no',ssh_args(work))
            (work/'pilot.json').write_text(json.dumps({'attach_seed':True}))
            self.assertIn('StrictHostKeyChecking=accept-new',ssh_args(work))

    def test_only_the_canonical_proxmox_managed_key_symlink_can_be_appended(self):
        connection=Mock();connection.recv.side_effect=[b'root@heist-pilot:~#',b'HEIST-ACCESS-RECOVERED\r\n']
        key='ssh-ed25519 '+'A'*68+' fixture'
        authorize(connection,'fixture-password',key)
        command=connection.sendall.call_args.args[0].decode()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ssh=root/'ssh';ssh.mkdir()
            marker=root/'pilot-marker';marker.touch()
            managed=root/'managed-keys';managed.write_text('old-key\n');managed.chmod(0o600)
            foreign=root/'foreign-keys';foreign.write_text('do-not-change\n');foreign.chmod(0o600)
            script=command.replace('/root/pilot-cloud-init-ready',str(marker)).replace('/root/.ssh',str(ssh))
            script=script.replace('/etc/pve/priv/authorized_keys',str(managed)).replace('test "$(hostname)" = heist-pilot','true')
            target=ssh/'authorized_keys';target.symlink_to(managed)
            result=subprocess.run(['sh','-c',script],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(managed.read_text(),'old-key\n'+key+'\n')
            target.unlink();target.symlink_to(foreign)
            result=subprocess.run(['sh','-c',script],capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(foreign.read_text(),'do-not-change\n')

    def test_password_is_sent_only_after_login_and_never_embedded_in_the_shell_command(self):
        connection=Mock()
        connection.recv.side_effect=[b'heist-pilot login:',b'Password:',b'root@heist-pilot:~#',b'HEIST-ACCESS-RECOVERED\r\n']
        authorize(connection,'fixture-console-password','ssh-ed25519 '+'A'*68+' fixture')
        sent=[call.args[0] for call in connection.sendall.call_args_list]
        self.assertEqual(sent[1:3],[b'root\n',b'fixture-console-password\n'])
        self.assertNotIn(b'fixture-console-password',sent[-1])
        self.assertIn(b'test -f /root/pilot-cloud-init-ready',sent[-1])

    def test_invalid_key_and_failed_login_never_authorize_or_retry(self):
        connection=Mock()
        with self.assertRaises(ValueError):authorize(connection,'fixture','ssh-ed25519 bad\ncommand')
        connection.sendall.assert_not_called()
        connection.recv.side_effect=[b'login:',b'Password:',b'Login incorrect']
        with self.assertRaises(RuntimeError):authorize(connection,'fixture','ssh-ed25519 '+'A'*68)
        self.assertEqual(connection.sendall.call_count,3)

    def test_console_receive_handles_split_prompts_and_closed_connections(self):
        connection=Mock();connection.recv.side_effect=[b'Pass',b'word:']
        self.assertEqual(receive(connection,(b'Password:',)),b'Password:')
        connection.recv.side_effect=[b'']
        with self.assertRaises(RuntimeError):receive(connection,(b'Password:',))

    def test_online_or_wrong_qemu_process_cannot_use_console_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)/'copy';work.mkdir()
            proc=Path(directory)/'proc';(proc/'123').mkdir(parents=True)
            config={'production_accepted':False,'cold_import':'PREPARED_NOT_BOOTED','source_ova_sha256':'a'*64}
            (work/'pilot.json').write_text(json.dumps(config));(work/'qemu.pid').write_text('123')
            (work/'network-mode').write_text('offline-pilot\n')
            arguments=['qemu-system-x86_64','-pidfile',str(work/'qemu.pid'),'-netdev',management_network(config,online=False),
                '-chardev',f'socket,id=console,path={work}/console.sock,server=on,wait=off,logfile={work}/serial.log,logappend=on',
                '-drive',f'file={work}/disk.qcow2,format=qcow2,if=virtio']
            (proc/'123/cmdline').write_bytes('\0'.join(arguments).encode())
            self.assertEqual(validate(work,proc=proc),work)
            (work/'network-mode').write_text('online-provisioning\n')
            with self.assertRaises(ValueError):validate(work,proc=proc)
            (work/'network-mode').write_text('offline-pilot\n')
            arguments[4]=management_network(config,online=True)
            (proc/'123/cmdline').write_bytes('\0'.join(arguments).encode())
            with self.assertRaises(ValueError):validate(work,proc=proc)
