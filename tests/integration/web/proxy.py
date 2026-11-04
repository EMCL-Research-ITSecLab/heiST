"""Run a private Apache TLS/static/proxy process on an isolated web VM.

Requires the already-installed Apache modules and OpenSSL, root, and explicit
HEIST_ISOLATED_WEB_TESTS=1. Creates its own certificate, ports and temporary tree;
never edits /etc/apache2, installed certificates, services or application data.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from heist.rollout.web_proxy import render


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'path': self.path, 'forwarded': self.headers.get('Forwarded'),
                           'host': self.headers.get('X-Forwarded-Host'),
                           'address': self.headers.get('X-Forwarded-For'),
                           'protocol': self.headers.get('X-Forwarded-Proto')}).encode()
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers();self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ApacheBoundaryTests(unittest.TestCase):
    def test_native_tls_spa_static_files_api_status_and_forwarded_identity(self):
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        with tempfile.TemporaryDirectory(prefix='heist-apache-', dir='/var/tmp') as temporary:
            root = Path(temporary);root.chmod(0o755)
            static = root/'static';static.mkdir(mode=0o755)
            (static/'index.html').write_text('<html>heiST private SPA test</html>')
            (static/'app.js').write_text('console.log("fixture");')
            (static/'forbidden.php').write_text('private fixture must not be served')
            (root/'run').mkdir()
            certificate,key = root/'tls.pem',root/'tls.key'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
                            '-keyout',str(key),'-out',str(certificate)],check=True,capture_output=True,timeout=20)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            template = (Path(__file__).resolve().parents[3]/'deploy/web/apache/heist.conf').read_text()
            virtual_host = render(template,web_root=str(static),certificate=str(certificate),
                                  certificate_key=str(key),hostname='localhost',
                                  api_port=upstream.server_port,bind='127.0.0.1:'+str(port))
            modules = ['mpm_event','authz_core','authz_host','dir','mime','headers','proxy','proxy_http','ssl','alias','setenvif']
            config = '\n'.join('LoadModule '+name+'_module /usr/lib/apache2/modules/mod_'+name+'.so' for name in modules)
            config += f'\nServerRoot "{root}"\nDefaultRuntimeDir "{root}/run"\nPidFile "{root}/apache.pid"\nErrorLog "{root}/error.log"\nServerName localhost\nListen 127.0.0.1:{port}\nUser www-data\nGroup www-data\nTypesConfig /etc/mime.types\nServerLimit 1\nStartServers 1\nThreadsPerChild 8\nMinSpareThreads 1\nMaxSpareThreads 8\nMaxRequestWorkers 8\n'
            configuration=root/'apache.conf';configuration.write_text(config+virtual_host)
            subprocess.run(['apache2','-t','-f',str(configuration)],check=True,capture_output=True,timeout=10)
            context=ssl.create_default_context(cafile=str(certificate))
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
            process=subprocess.Popen(['apache2','-DFOREGROUND','-f',str(configuration)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
            origin='https://127.0.0.1:'+str(port)
            try:
                deadline=time.monotonic()+15
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('Private Apache failed: '+process.stderr.read().decode()[-2000:])
                    try:
                        with opener.open(origin+'/dashboard',timeout=2) as response:
                            self.assertIn(b'heiST private SPA test',response.read())
                            self.assertEqual(response.headers['Cache-Control'],'no-store')
                        break
                    except urllib.error.URLError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                with opener.open(origin+'/app.js',timeout=2) as response:
                    self.assertEqual(response.read(),b'console.log("fixture");')
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    opener.open(origin+'/forbidden.php',timeout=2)
                self.assertEqual(denied.exception.code,403);denied.exception.close()
                request=urllib.request.Request(origin+'/api/test?fixture=1',headers={
                    'Forwarded':'for=198.51.100.2;proto=http', 'X-Forwarded-Host':'foreign.invalid',
                    'X-Forwarded-For':'198.51.100.2','X-Forwarded-Proto':'http'})
                with self.assertRaises(urllib.error.HTTPError) as api:
                    opener.open(request,timeout=2)
                with api.exception as response:
                    self.assertEqual(response.code,401)
                    value=json.loads(response.read())
                    self.assertEqual(value,{'path':'/api/test?fixture=1','forwarded':None,'host':None,'address':'127.0.0.1','protocol':'https'})
            finally:
                if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5);raise
                process.stderr.close()
            self.assertEqual(process.returncode,0)


if __name__ == '__main__':
    if os.geteuid()!=0 or os.environ.get('HEIST_ISOLATED_WEB_TESTS')!='1':
        raise SystemExit('Use an isolated disposable web VM with HEIST_ISOLATED_WEB_TESTS=1')
    unittest.main(verbosity=2)
