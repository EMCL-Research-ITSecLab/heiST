"""WSGI process configuration and real HTTP boundary checks without infrastructure."""
import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from heist.api.serve import options


class ServerOptionsTests(unittest.TestCase):
    def test_binding_is_loopback_only_and_config_cannot_enable_privileged_ports(self):
        value = options({})
        self.assertEqual(value['bind'], '127.0.0.1:8001')
        self.assertEqual(value['worker_class'], 'gthread')
        self.assertIsNone(value['accesslog'])
        self.assertFalse(value['preload_app'])
        self.assertEqual(options({'HEIST_WEB_PORT': '12345'})['bind'], '127.0.0.1:12345')
        for value in ('0', '80', '65536', '0.0.0.0:8001', '٨٠٠١', '', None, '8001\n'):
            with self.subTest(port=value), self.assertRaises(ValueError):
                options({'HEIST_WEB_PORT': value})


@unittest.skipUnless(importlib.util.find_spec('gunicorn'), 'Approved Gunicorn web runtime is required')
class GunicornProcessTests(unittest.TestCase):
    def test_real_workers_require_tls_return_json_errors_and_stop_cleanly(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        environment = {'PATH': os.defpath, 'WEB_SESSION_SECRET': 'b'*64, 'DB_USER': 'web_test',
                       'DB_HOST': '127.0.0.1', 'DB_PORT': '1', 'HEIST_WEB_PORT': str(port),
                       'PYTHONPATH': os.environ.get('PYTHONPATH', '')}
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([sys.executable, '-m', 'heist.api.serve'], cwd=Path(__file__).resolve().parents[1],
                                       env=environment, stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic()+10
                while True:
                    try:
                        response = urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/api/unknown', timeout=1)
                    except urllib.error.HTTPError as error:
                        self.assertEqual(error.code, 400)
                        error.close()
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail('Gunicorn did not become ready')
                        time.sleep(.05)
                    else:
                        response.close()
                        self.fail('Plain HTTP was accepted')
                request = urllib.request.Request('http://127.0.0.1:'+str(port)+'/api/unknown', headers={'X-Forwarded-Proto': 'https'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                with caught.exception as result:
                    self.assertEqual(result.code, 404)
                    self.assertIn(b'Not found', result.read())
                    self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
                request = urllib.request.Request('http://127.0.0.1:'+str(port)+'/api/session', headers={'X-Forwarded-Proto': 'https'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=5)
                with caught.exception as result:
                    self.assertEqual(result.code, 503)
                    self.assertNotIn(b'web_test', result.read())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    self.fail('Gunicorn did not stop within the shutdown budget')
            self.assertEqual(process.returncode, 0)
            log.seek(0)
            self.assertNotIn(b'b'*64, log.read())
