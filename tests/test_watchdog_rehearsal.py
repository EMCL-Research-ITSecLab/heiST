"""The native observer test accepts only the exact selected source artifact."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED

from tools.build.watchdog import build
from tools.local.rehearse_watchdog import RUN, verify_artifact


class WatchdogRehearsalTests(unittest.TestCase):
    def test_observer_payload_is_bound_to_immutable_source(self):
        root=Path(__file__).resolve().parents[1]
        commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        with tempfile.TemporaryDirectory() as directory:
            snapshot=Path(directory)/'source'
            for name in ('heist/__init__.py','heist/monitoring/__init__.py','heist/remote.py','heist/monitoring/health.py','heist/monitoring/watchdog.py'):
                target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(subprocess.check_output(['git','-C',str(root),'show',commit+':'+name]))
            path=Path(directory)/'watchdog.pyz'
            with patch('tools.build.watchdog.ROOT',snapshot):build(path)
            self.assertEqual(verify_artifact(path,commit),path.read_bytes())
            with ZipFile(path,'a',compression=ZIP_DEFLATED) as archive:archive.writestr('extra.py','raise RuntimeError()')
            with self.assertRaises(ValueError):verify_artifact(path,commit)
            with self.assertRaises(ValueError):verify_artifact(path,'--not-a-commit')

    def test_offhost_mutation_requires_the_disposable_host_guard(self):
        import sys
        program="import socket;socket.gethostname=lambda:'not-a-disposable-fixture'\n"+RUN
        result=subprocess.run([sys.executable,'-c',program],input=b'{}',capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Require the disposable pilot',result.stderr)
        self.assertEqual(result.stdout,b'')
