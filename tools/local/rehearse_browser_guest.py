#!/usr/bin/env python3
"""Install the real browser service on the disposable pilot, then restore its web VM.

Uses a previously verified complete pilot checkpoint and an independent scratch
SQL database. This is web-role acceptance, not a platform upgrade approval. The
production schema-3 admission gate is never bypassed or changed.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import uuid
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rehearse_recovery import require_fixture
from heist.files import maintenance_lock, private_directory, sha256, write_json
from heist.rollout import web
from heist.rollout.browser_configuration import configuration
from heist.rollout.browser_deployment import BOOTSTRAP, package
from heist.rollout.config import Deployment
from heist.rollout.controller import Transaction
from heist.rollout.manifest import Plan, blob, revision, web_files
from heist.runtime_bundle import digest


def main(argv=None):
    import argparse
    from heist.rollout.pve import PVE
    from tests.test_web_database import WebDatabaseTests
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--runtime-bundle', required=True, type=Path)
    parser.add_argument('--ui-bundle', required=True, type=Path)
    args = parser.parse_args(argv)
    require_fixture()
    config = Deployment.load(args.config)
    adapter = PVE(config, sha256(args.config))
    checkpoint = Transaction.load(args.checkpoint)
    source = revision(adapter.installation, 'HEAD')
    commit = revision(ROOT, 'HEAD')
    if (checkpoint.data['phase'] != 'COMPLETE' or not checkpoint.data.get('checkpoint_ready') or
            checkpoint.plan.source != source or checkpoint.data.get('failures') or
            config.vm('web').vmid != 1000 or (adapter.state/'active.json').exists()):
        raise RuntimeError('Require the unchanged, recovered pilot baseline and no active rollout')
    if not config.web_certificate_key or not config.web_hostname:
        raise ValueError('Declare the pilot web certificate key and hostname')
    saved = checkpoint.data['snapshots']['web']
    archive = Path(saved['path'])
    if archive.is_symlink() or archive.stat().st_size != saved['bytes'] or sha256(archive) != saved['sha256']:
        raise RuntimeError('The complete web VM recovery archive differs')
    runtime, frontend = args.runtime_bundle.read_bytes(), args.ui_bundle.read_bytes()
    # Validate both artifacts before even creating the disposable SQL fixture.
    package(runtime, frontend, {}, commit)
    files = web_files(adapter.installation, source, production=True)
    baseline = Plan(1, str(adapter.installation), source, source, 'web-role-rehearsal', 'unused',
                    'unused', sha256(args.config), (), files, files, rollback=True)
    name = 'native-browser-'+uuid.uuid4().hex[:12]
    with maintenance_lock(adapter.state):
        adapter.preflight(baseline)
        if adapter.protected_hashes(checkpoint.plan.protected_tables) != checkpoint.data['protected_hashes']:
            raise RuntimeError('The current pilot differs from the recovered checkpoint')
        transaction = Transaction(private_directory(adapter.state/'transactions'/name),
                                  {'plan': baseline.to_dict(), 'kind': 'web-role-rehearsal',
                                   'committed': False, 'backup_directory': str(checkpoint.data['backup_directory']),
                                   'checkpoint_ready': True})
        transaction.save('PREPARED', target_commit=commit, recovery_archive_sha256=saved['sha256'])
        environment = adapter.environment
        previous_url = os.environ.get('TEST_DATABASE_URL')
        os.environ['TEST_DATABASE_URL'] = ('postgresql://'+quote(environment['DB_USER'],safe='')+':'+
            quote(environment['DB_PASSWORD'],safe='')+'@'+environment['DB_HOST']+':'+environment.get('DB_PORT','5432')+'/'+environment['DB_NAME'])
        created = False
        mutated = False
        try:
            WebDatabaseTests.setUpClass()
            created = True
            fixture = WebDatabaseTests()
            fixture.setUp()
            try:
                host = {**environment, 'DB_NAME': WebDatabaseTests.database}
                settings = {'commit': commit, 'runtime_sha256': digest(runtime), 'ui_sha256': digest(frontend),
                    'environment': configuration(host, role=WebDatabaseTests.role, password=WebDatabaseTests.password,
                                                 session_secret=secrets.token_hex(32), backend_server_name=adapter.node),
                    'units': {name: blob(ROOT, commit, 'deploy/web/systemd/'+name).decode()
                              for name in ('heist-web.service','heist-artifacts.service')},
                    'apache_template': blob(ROOT, commit, 'deploy/web/apache/heist.conf').decode(),
                    'certificate': config.web_certificate, 'certificate_key': config.web_certificate_key,
                    'hostname': config.web_hostname, 'backend_ca': Path('/etc/pve/pve-root-ca.pem').read_text(),
                    'legacy_root': config.web_root}
                payload = package(runtime, frontend, settings, commit)
                services = json.loads(adapter.remote(config.vm('web'), web.CAPTURE_SERVICES))
                transaction.save('QUIESCING', web_services=services)
                # Mark intent first: even a lost SSH response requires VM recovery.
                mutated = True
                adapter.remote(config.vm('web'), web.INSTALL_GUARD, {'program': web.FIREWALL})
                adapter.remote(config.vm('web'), web.QUIESCE)
                transaction.save('DEPLOYING')
                result = config.vm('web').ssh.run(['/usr/bin/python3','-c',BOOTSTRAP,digest(payload)],input=payload,timeout=1000)
                receipt = json.loads(result.stdout)
                if receipt.get('commit') != commit or receipt.get('runtime_sha256') != digest(runtime):
                    raise AssertionError('Native guest did not confirm the reviewed runtime')
                transaction.save('VERIFYING', browser_deployment=receipt)
                # No host API or challenge operation is necessary for this check.
                # Verify Apache TLS, static routing and the real proxied Gunicorn API.
                probe = """import hashlib,hmac,http.client,json,ssl
from pathlib import Path
certificate=Path(@CERTIFICATE@)
context=ssl.create_default_context(cafile=str(certificate))
context.check_hostname=False
connection=http.client.HTTPSConnection('127.0.0.1',443,context=context,timeout=15)
try:
 connection.connect()
 expected=hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).digest()
 assert hmac.compare_digest(expected,hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest())
 def get(path):
  connection.request('GET',path)
  response=connection.getresponse();body=response.read(2*1024**2)
  assert response.status==200
  return response,body
 _,html=get('/login')
 assert b'id="root"' in html
 _,body=get('/api/health/live')
 assert json.loads(body)['status']=='alive'
 response,body=get('/api/session')
 assert json.loads(body)['success'] is True
 cookie=response.getheader('Set-Cookie','')
 assert 'Secure' in cookie and 'HttpOnly' in cookie
 print(json.dumps({'apache_spa':True,'gunicorn_liveness':True,'session_api':True,'secure_cookie':True,'tls_peer_pinned':True}))
finally:
 connection.close()
""".replace('@CERTIFICATE@',repr(config.web_certificate))
                checks = json.loads(config.vm('web').ssh.run(['/usr/bin/python3','-c',probe],timeout=30).stdout)
                # Simulate worker failure; systemd must restart a real worker.
                config.vm('web').ssh.run(['systemctl','kill','--signal=SIGKILL','--kill-whom=main','heist-web'],timeout=30)
                adapter.wait(lambda: json.loads(config.vm('web').ssh.run(['/usr/bin/python3','-c',probe],timeout=30).stdout),
                             'native Gunicorn recovery')
                transaction.save('WEB_ROLE_VERIFIED', checks=checks, worker_restart=True,
                                 platform_upgrade_approved=False)
            finally:
                fixture.doCleanups()
        except BaseException as error:
            transaction.failure(error)
            raise
        finally:
            try:
                if mutated:
                    transaction.save('RESTORING_WEB')
                    vm = config.vm('web')
                    if adapter.is_running(vm):adapter.command(['qm','shutdown',vm.vmid,'--timeout','180'],timeout=210)
                    if adapter.is_running(vm):raise RuntimeError('Refusing to restore a running web VM')
                    adapter.tasks.run(transaction, 'restore-web', '/nodes/'+adapter.node+'/qemu',
                                      {'archive': str(archive), 'vmid': vm.vmid, 'force': 1})
                    adapter.command(['qm','start',vm.vmid])
                    adapter.wait(lambda: adapter.remote(vm, web.CAPTURE_SERVICES), 'restored web SSH')
                    adapter.remote(vm, web.INSTALL_GUARD, {'program': web.FIREWALL})
                    adapter.remote(vm, web.FINISH, {'services': transaction.data['web_services'], 'open': False})
                    adapter.wait(lambda: adapter._health(legacy=True,local_web=True), 'restored legacy web health')
                    adapter.remote(vm, web.FINISH, {'services': transaction.data['web_services'], 'open': True})
                    transaction.save('RECOVERED', recovery_verified=True)
            except BaseException as recovery_error:
                transaction.failure(recovery_error)
                transaction.save('RECOVERY_REQUIRED')
                raise
            finally:
                if created:WebDatabaseTests.tearDownClass()
                if previous_url is None:os.environ.pop('TEST_DATABASE_URL',None)
                else:os.environ['TEST_DATABASE_URL'] = previous_url
        print(json.dumps({'transaction': name, 'phase': transaction.data['phase'],
                          'checks': transaction.data.get('checks',{}), 'failures': len(transaction.data.get('failures',[])),
                          'platform_upgrade_approved': False}))


if __name__ == '__main__':
    main()
