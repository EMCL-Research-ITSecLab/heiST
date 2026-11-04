"""Privileged WSGI boot must match its offline wheel and complete source receipt."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from heist.api.internal_serve import load_runtime, options
from heist.runtime_bundle import digest


class InternalServerTests(unittest.TestCase):
    def test_mismatched_source_or_wheel_is_refused_before_importing_gunicorn(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            runtime,source=root/'runtime',root/'source'
            runtime.mkdir();(source/'heist/api').mkdir(parents=True)
            entry=source/'heist/api/internal_serve.py'
            entry.write_bytes(b'pass\n')
            wheel=runtime/'gunicorn.whl';wheel.write_bytes(b'approved fixture wheel')
            receipt={'schema':1,'source_commit':'a'*40,'wheel_sha256':digest(wheel.read_bytes()),
                     'source_files':{'heist/api/internal_serve.py':digest(entry.read_bytes())}}
            (runtime/'metadata.json').write_text(json.dumps(receipt))
            with patch('sys.path',list(sys.path)):
                load_runtime(runtime,source)
                self.assertEqual(sys.path[0],str(wheel))
            entry.write_text('changed\n')
            with self.assertRaises(ValueError):
                load_runtime(runtime,source)
            entry.write_bytes(b'pass\n');wheel.write_bytes(b'changed wheel')
            with self.assertRaises(ValueError):
                load_runtime(runtime,source)

    def test_single_process_private_binding_and_managed_tls_do_not_enable_header_trust(self):
        value=options({'BACKEND_HOST':'10.0.0.1','BACKEND_PORT':'8000'})
        self.assertEqual(value['workers'],1)
        self.assertEqual(value['bind'],'10.0.0.1:8000')
        self.assertEqual(value['forwarded_allow_ips'],'')
        self.assertEqual(value['certfile'],'/etc/pve/local/pve-ssl.pem')
        self.assertEqual(options({'BACKEND_HOST':'::1'})['bind'],'[::1]:8000')
        for settings in ({'BACKEND_HOST':'0.0.0.0;command'},{'BACKEND_PORT':'80'},{'BACKEND_PORT':'-1'}):
            with self.assertRaises(ValueError):
                options(settings)
