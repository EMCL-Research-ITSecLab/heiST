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
