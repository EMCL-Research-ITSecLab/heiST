"""Real TLS through a forwarded path with a packet-size black hole."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from heist.infrastructure.network.vpn_transport import CHAIN, configure


@unittest.skipUnless(os.getenv('HEIST_PRIVILEGED_TESTS') == '1', 'Explicit private-netns test opt-in required')
class VpnTransportTests(unittest.TestCase):
    def test_verified_tls_bidirectional_idempotence_and_removal(self):
        token = uuid.uuid4().hex[:6]
        router, client, guest = ['hmss-' + token + suffix for suffix in ('r', 'c', 'g')]
        for ns in (router, client, guest):
            subprocess.run(['ip', 'netns', 'add', ns], check=True)
            self.addCleanup(subprocess.run, ['ip', 'netns', 'delete', ns], check=True)

        def execute(ns, args, **kwargs):
            return subprocess.run(['ip', 'netns', 'exec', ns, *args], **kwargs)

        def firewall(args, **kwargs):
            return execute(router, args, **kwargs)

        for suffix, peer, interface, address, gateway in (
            ('c', client, 'tun0', '10.64.0.2', '10.64.0.1'),
            ('g', guest, 'vrt000abc1', '10.128.0.2', '10.128.0.1'),
        ):
            left, right = 'hm' + token + suffix, 'hp' + token + suffix
            subprocess.run(['ip', 'link', 'add', left, 'type', 'veth', 'peer', 'name', right], check=True)
            subprocess.run(['ip', 'link', 'set', left, 'netns', router], check=True)
            subprocess.run(['ip', 'link', 'set', right, 'netns', peer], check=True)
            execute(router, ['ip', 'link', 'set', left, 'name', interface], check=True)
            for ns, device, ip in ((router, interface, gateway), (peer, right, address)):
                execute(ns, ['ip', 'link', 'set', 'lo', 'up'], check=True)
                execute(ns, ['ip', 'link', 'set', device, 'up'], check=True)
                execute(ns, ['ip', 'address', 'add', ip + '/24', 'dev', device], check=True)
            execute(peer, ['ip', 'route', 'add', 'default', 'via', gateway], check=True)
        execute(router, ['sysctl', '-qw', 'net.ipv4.ip_forward=1'], check=True)
        firewall(['iptables', '-A', 'FORWARD', '-m', 'length', '--length', '1201:65535', '-j', 'DROP'], check=True)
        with tempfile.TemporaryDirectory() as directory:
            cert, key = [str(Path(directory) / name) for name in ('ca.crt', 'key.pem')]
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=portal.test',
                            '-addext', 'subjectAltName=DNS:portal.test'],
                           check=True, capture_output=True, timeout=15)
            program = '''import http.server,ssl,sys
class Handler(http.server.BaseHTTPRequestHandler):
 def do_POST(self):
  body=self.rfile.read(int(self.headers['Content-Length']))
  self.send_response(200);self.end_headers();self.wfile.write(body)
 def log_message(self,*args): pass
server=http.server.ThreadingHTTPServer(('10.128.0.2',443),Handler)
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(*sys.argv[1:])
server.socket=ctx.wrap_socket(server.socket,server_side=True)
server.serve_forever()
'''
            process = subprocess.Popen(['ip', 'netns', 'exec', guest, sys.executable, '-c', program, cert, key],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def stop():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self.addCleanup(stop)
            deadline = time.monotonic() + 5
            while True:
                ready = execute(guest, [sys.executable, '-c',
                    "import socket;socket.create_connection(('10.128.0.2',443),.2).close()"], capture_output=True)
                if ready.returncode == 0:
                    break
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.05)
            client_code = """import http.client,socket,ssl,sys
context=ssl.create_default_context(cafile=sys.argv[1])
connection=http.client.HTTPConnection('portal.test',443,timeout=2)
raw=socket.create_connection(('10.128.0.2',443),2)
connection.sock=context.wrap_socket(raw,server_hostname='portal.test')
connection.request('POST','/',sys.stdin.buffer.read())
response=connection.getresponse()
assert response.status==200
sys.stdout.buffer.write(response.read())
"""
            request = [sys.executable, '-c', client_code, cert]
            body = 'verified bidirectional TLS\n' * 4096
            def probe():
                return execute(client, request, input=body, text=True, capture_output=True, timeout=5)
            self.assertNotEqual(probe().returncode, 0, 'Must reproduce TLS stall before repair')
            configure(run=firewall)
            configure(run=firewall)
            rules = firewall(['iptables', '-t', 'mangle', '-S'], capture_output=True, text=True, check=True).stdout
            self.assertEqual(rules.count('-j ' + CHAIN), 2)
            answer = probe()
            self.assertEqual(answer.returncode, 0, answer.stderr)
            self.assertEqual(answer.stdout, body)
            configure(remove=True, run=firewall)
            configure(remove=True, run=firewall)
            self.assertNotEqual(probe().returncode, 0, 'Removal restores original failure')
            policy = firewall(['iptables', '-S', 'FORWARD'], capture_output=True, text=True, check=True).stdout
            self.assertIn('--length 1201:65535 -j DROP', policy)
