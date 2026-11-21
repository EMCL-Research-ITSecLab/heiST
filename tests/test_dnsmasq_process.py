"""PID ownership and native stop behavior without trusting a numeric PID alone."""
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from heist.infrastructure.network.dnsmasq_process import stop


class DNSProcessTests(unittest.TestCase):
    def test_recycled_pid_of_unrelated_process_is_never_signaled(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory)/'dnsmasq.pid'
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', 'dnsmasq', '--pid-file='+str(pidfile)])
            try:
                pidfile.write_text(str(child.pid))
                self.assertFalse(stop(pidfile))
                self.assertIsNone(child.poll())
            finally:
                child.terminate()
                child.wait(timeout=3)

    def test_missing_invalid_init_pid_and_symlink_files_cannot_trigger_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory)/'dnsmasq.pid'
            self.assertFalse(stop(pidfile))
            for value in ('1', '-2', '2147483648', 'x'*100, '١٢'):
                pidfile.write_text(value)
                with self.assertRaises((ValueError, UnicodeError)):
                    stop(pidfile)
            pidfile.unlink()
            external = Path(directory)/'external'
            external.write_text('1')
            pidfile.symlink_to(external)
            with self.assertRaises(OSError):
                stop(pidfile)
            self.assertEqual(external.read_text(), '1')

    @unittest.skipUnless(shutil.which('dnsmasq'), 'Existing dnsmasq binary is required')
    def test_owned_native_daemon_stops_through_stable_pid_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory)/'dnsmasq.pid'
            with tempfile.TemporaryFile() as log:
                child = subprocess.Popen(['dnsmasq', '--keep-in-foreground', '--conf-file=/dev/null', '--port=0', '--no-hosts', '--no-resolv',
                                          '--user='+pwd.getpwuid(os.geteuid()).pw_name, '--pid-file='+str(pidfile)], stdout=log, stderr=log)
                try:
                    deadline = time.monotonic()+3
                    while not pidfile.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.02)
                    if child.poll() is not None:
                        log.seek(0)
                        self.fail('Owned test daemon failed to start: '+log.read().decode())
                    self.assertTrue(pidfile.is_file(), 'Test daemon did not publish its PID file')
                    self.assertTrue(stop(pidfile))
                    child.wait(timeout=3)
                    self.assertIsNotNone(child.returncode)
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=3)

    def test_start_requires_owned_identity_and_uses_independent_forking_service(self):
        from unittest.mock import Mock
        from heist.infrastructure.network.dnsmasq_process import start
        run = Mock()
        command=['dnsmasq','--pid-file=/etc/dnsmasq-instances/dnsmasq_vrt123abc.pid']
        start(command,run=run)
        args=run.call_args.args[0]
        self.assertEqual(args[0],'systemd-run')
        self.assertIn('--service-type=forking',args)
        self.assertIn('--collect',args)
        self.assertIn('--unit=heist-dnsmasq-vrt123abc',args)
        self.assertEqual(args[-2:],command)
        for bad in (['dnsmasq'],['dnsmasq','--pid-file=relative.pid'],
                    ['python','--pid-file=/tmp/dnsmasq_vrt123.pid'],
                    ['dnsmasq','--pid-file=/tmp/dnsmasq_other.pid']):
            with self.assertRaises(ValueError):start(bad,run=run)
        run.assert_called_once()

    @unittest.skipUnless(os.getenv('HEIST_PRIVILEGED_TESTS') == '1', 'Explicit native systemd test opt-in required')
    def test_daemon_survives_parent_service_stop_and_owned_stop_still_cleans_it(self):
        import uuid
        token=uuid.uuid4().hex[:8]
        parent='heist-dhcp-test-parent-'+token
        child='heist-dnsmasq-vrt'+token
        def cleanup():
            subprocess.run(['systemctl','stop',parent,child],capture_output=True,timeout=15)
        self.addCleanup(cleanup)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            pidfile=root/('dnsmasq_vrt'+token+'.pid')
            command=['/usr/sbin/dnsmasq','--conf-file=/dev/null','--port=0','--no-hosts','--no-resolv',
                     '--user=root','--pid-file='+str(pidfile)]
            program='from heist.infrastructure.network.dnsmasq_process import start; import time; r=start('+repr(command)+'); r.check_returncode(); time.sleep(60)'
            subprocess.run(['systemd-run','--quiet','--collect','--unit='+parent,'--service-type=exec',
                            '--setenv=PYTHONPATH='+str(Path(__file__).resolve().parents[1]),
                            sys.executable,'-c',program],check=True,capture_output=True,timeout=15)
            deadline=time.monotonic()+10
            while not pidfile.exists():
                self.assertLess(time.monotonic(),deadline,'Independent daemon did not start')
                time.sleep(.05)
            pid=int(pidfile.read_text())
            group=Path('/proc',str(pid),'cgroup').read_text()
            self.assertIn(child+'.service',group)
            self.assertNotIn(parent,group)
            subprocess.run(['systemctl','stop',parent],check=True,capture_output=True,timeout=15)
            os.kill(pid,0)
            self.assertTrue(stop(pidfile))
            deadline=time.monotonic()+5
            while Path('/proc',str(pid)).exists():
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.05)
