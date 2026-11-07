"""Shared browser deployment assembly for the installer and checkpointed rollout.

Admission remains the caller's responsibility. Rollout requires a verified full
checkpoint and persistent maintenance. Private configuration travels over SSH
stdin; only a complete package digest appears in its command arguments.
"""
import io
import json
from pathlib import Path
import re
import secrets
import tarfile

from heist.files import write_file, write_json
from heist.runtime_bundle import digest, inspect_bundle
from heist.ui_assets import inspect_bundle as inspect_ui
from .browser_configuration import configuration
from .browser_role import validate
from .manifest import blob

MAX_PACKAGE_BYTES = 200*1024**2

# The bootstrap deliberately imports only the standard library. Application code
# comes from the approved source-bound runtime, not packages on a web VM's PATH.
BOOTSTRAP = r'''
import hashlib,io,json,os,re,subprocess,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
limit=200*1024**2
payload=sys.stdin.buffer.read(limit+1)
if len(payload)>limit or hashlib.sha256(payload).hexdigest()!=sys.argv[1]:
    raise RuntimeError('Browser deployment package checksum differs')
with tempfile.TemporaryDirectory(prefix='heist-browser-') as temporary:
    root=Path(temporary);seen=set();total=0
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:') as archive:
        for member in archive:
            path=PurePosixPath(member.name)
            allowed=member.name in ('configuration.json','runtime.tar.gz','frontend.tar.gz') or re.fullmatch(r'source/heist/[A-Za-z0-9_./-]+\.py',member.name)
            total+=member.size
            if not allowed or not member.isfile() or path.is_absolute() or '..' in path.parts or str(path)!=member.name or member.name in seen or total>limit or len(seen)>=2048:
                raise RuntimeError('Unsafe browser deployment package')
            seen.add(member.name);target=root/member.name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with archive.extractfile(member) as source,target.open('xb') as output:
                os.chmod(target,0o600)
                while chunk:=source.read(1024**2):output.write(chunk)
    if not {'configuration.json','runtime.tar.gz','frontend.tar.gz','source/heist/rollout/browser_guest.py'}.issubset(seen):
        raise RuntimeError('Incomplete browser deployment package')
    config=json.loads((root/'configuration.json').read_text())
    config.update(runtime_bundle=str(root/'runtime.tar.gz'),ui_bundle=str(root/'frontend.tar.gz'))
    environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(root/'source'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'}
    result=subprocess.run(['/usr/bin/python3','-m','heist.rollout.browser_guest'],input=json.dumps(config).encode(),env=environment,cwd=root,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=900)
    sys.stdout.buffer.write(result.stdout)
'''


def credentials(transaction):
    path = Path(transaction.data['backup_directory'])/'browser-credentials.json'
    if path.is_symlink():
        raise RuntimeError('Browser credentials must not be a symlink')
    if path.exists():
        import os
        info = path.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeError('Browser credential receipt must be private to its owner')
        value = json.loads(path.read_text())
    else:
        value = {'role': 'heist_web_'+secrets.token_hex(12), 'password': secrets.token_urlsafe(48),
                 'session_secret': secrets.token_hex(32)}
        write_json(path, value)
    if set(value) != {'role', 'password', 'session_secret'} or re.fullmatch('[a-f0-9]{64}', value['session_secret']) is None:
        raise RuntimeError('Unknown browser credential receipt')
    validate(value['role'], value['password'])
    return value


def package(runtime, frontend, settings, commit):
    """Construct one bounded transport after validating both reviewed artifacts."""
    _, files = inspect_bundle(runtime, commit)
    ui, _ = inspect_ui(frontend, commit)
    if ui['schema'] != 2:
        raise ValueError('The browser service requires standalone React assets')
    members = {'runtime.tar.gz': runtime, 'frontend.tar.gz': frontend,
               'configuration.json': json.dumps(settings).encode()}
    members.update({name: body for name, body in files.items() if name.startswith('source/')})
    if sum(map(len, members.values())) > MAX_PACKAGE_BYTES-4*1024**2:
        raise ValueError('Browser deployment package exceeds its limit')
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, body in sorted(members.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(body), 0o600
            archive.addfile(member, io.BytesIO(body))
    result = output.getvalue()
    if len(result) > MAX_PACKAGE_BYTES:
        raise ValueError('Browser deployment package exceeds its limit')
    return result


def settings(adapter, transaction, secret, backend_ca):
    key = getattr(adapter.config, 'web_certificate_key', None)
    if not key:
        raise ValueError('Declare web_certificate_key before staging the Flask browser')
    return {'commit': transaction.plan.target,
            'runtime_sha256': transaction.plan.runtime_bundle['sha256'],
            'ui_sha256': transaction.plan.ui_bundle['sha256'],
            'environment': configuration(adapter.environment, role=secret['role'], password=secret['password'],
                                         session_secret=secret['session_secret'], backend_server_name=adapter.node),
            'units': {name: blob(adapter.installation, transaction.plan.target, 'deploy/web/systemd/'+name).decode()
                      for name in ('heist-web.service', 'heist-artifacts.service')},
            'apache_template': blob(adapter.installation, transaction.plan.target, 'deploy/web/apache/heist.conf').decode(),
            'certificate': adapter.config.web_certificate, 'certificate_key': key,
            'hostname': adapter.config.web_hostname, 'backend_ca': backend_ca,
            'legacy_root': adapter.config.web_root}


def deploy_guest(adapter, transaction):
    if not transaction.data.get('checkpoint_ready') or not adapter.marker.is_file():
        raise RuntimeError('Browser rollout requires a complete checkpoint and persistent maintenance')
    if transaction.plan.schema != 3:
        raise ValueError('Browser deployment requires protocol 3')
    runtime = Path(transaction.data['runtime_bundle_checkpoint']).read_bytes()
    frontend = Path(transaction.data['ui_bundle_checkpoint']).read_bytes()
    if digest(runtime) != transaction.plan.runtime_bundle['sha256'] or digest(frontend) != transaction.plan.ui_bundle['sha256']:
        raise RuntimeError('Checkpointed browser artifacts differ from the reviewed plan')
    secret = credentials(transaction)
    config = settings(adapter, transaction, secret, Path('/etc/pve/pve-root-ca.pem').read_text())
    payload = package(runtime, frontend, config, transaction.plan.target)
    result = adapter.config.vm('web').ssh.run(['/usr/bin/python3', '-c', BOOTSTRAP, digest(payload)],
                                             input=payload, timeout=1000)
    receipt = json.loads(result.stdout)
    if (receipt.get('commit') != transaction.plan.target or receipt.get('runtime_sha256') != config['runtime_sha256']
            or receipt.get('ui_sha256') != config['ui_sha256']):
        raise RuntimeError('Web VM did not confirm the reviewed browser deployment')
    transaction.save(browser_deployment=receipt)
    return receipt


def stage_host(adapter, transaction):
    """Install the privileged runtime and journal every mutable host file first."""
    if not transaction.data.get('checkpoint_ready') or adapter.marker.is_symlink() or not adapter.marker.is_file():
        raise RuntimeError('Host runtime deployment requires checkpointed maintenance')
    container = getattr(adapter.config, 'wazuh_container', None)
    if not container:
        raise ValueError('Declare the verified Wazuh manager container before deployment')
    runtime = Path(transaction.data['runtime_bundle_checkpoint']).read_bytes()
    if digest(runtime) != transaction.plan.runtime_bundle['sha256']:
        raise RuntimeError('Privileged runtime differs from the reviewed plan')
    _, files = inspect_bundle(runtime, transaction.plan.target)
    from heist.runtime_bundle import wheel_identity
    wheel = next(body for name, body in files.items() if name.startswith('wheels/')
                 and wheel_identity(Path(name).name, body)[0] == 'gunicorn')
    receipt = {'schema': 1, 'source_commit': transaction.plan.target, 'wheel_sha256': digest(wheel),
               'source_files': {name.removeprefix('source/'): digest(body) for name, body in files.items() if name.startswith('source/')}}
    installation = str(adapter.installation)
    for value in (installation, str(adapter.config.backend_env), str(adapter.state)):
        if re.fullmatch(r'/[A-Za-z0-9_./-]+', value) is None or '..' in Path(value).parts:
            raise ValueError('Use normalized host paths without systemd substitutions')
    vm = adapter.config.vm('monitoring')
    command = (['sudo', '-n'] if vm.user != 'root' else [])+['docker', 'exec', container, 'cat', '/var/ossec/api/configuration/ssl/server.crt']
    leaf = vm.ssh.run(command, timeout=30).stdout
    import ssl
    if len(leaf) > 65536:
        raise ValueError('Monitoring certificate exceeds its limit')
    ssl.PEM_cert_to_DER_cert(leaf.decode('ascii'))
    overlay = {'HEIST_MAINTENANCE_FILE': str(adapter.marker),
               'WAZUH_PINNED_CERTIFICATE_FILE': str(adapter.state/'wazuh-api-leaf.pem'),
               'HEIST_INTERNAL_CERTIFICATE': '/etc/pve/local/pve-ssl.pem',
               'HEIST_INTERNAL_KEY': '/etc/pve/local/pve-ssl.key'}
    original = Path(adapter.config.backend_env).read_bytes()
    environment = original+b'\n# Managed browser-runtime settings\n'+''.join(key+'='+json.dumps(value)+'\n' for key,value in sorted(overlay.items())).encode()
    dropin = ('[Service]\nWorkingDirectory='+installation+'\nExecStart=\nExecStart='+installation+'/.venv/bin/python -m heist.api.internal_serve\n'
              'Environment='+json.dumps('HEIST_BACKEND_ENV='+str(adapter.config.backend_env))+'\n'
              'Environment='+json.dumps('HEIST_INTERNAL_RUNTIME='+str(adapter.state/'internal-runtime/current'))+'\n')
    expiry = blob(adapter.installation, transaction.plan.target, 'deploy/platform/systemd/heist-expiry.service').decode()
    expiry = expiry.replace('/root/heiST', installation).replace('/run/heist-maintenance', str(adapter.marker))
    expiry += 'Environment='+json.dumps('HEIST_BACKEND_ENV='+str(adapter.config.backend_env))+'\n'
    expiry += 'Environment='+json.dumps('HEIST_MAINTENANCE_FILE='+str(adapter.marker))+'\n'
    units = Path('/etc/systemd/system')
    planned = {Path(adapter.config.backend_env): (environment, 0o600),
               adapter.state/'wazuh-api-leaf.pem': (leaf, 0o600),
               units/'backend.service.d/heist-runtime.conf': (dropin.encode(), 0o644),
               units/'heist-expiry.service': (expiry.encode(), 0o644),
               units/'heist-expiry.timer': (blob(adapter.installation, transaction.plan.target, 'deploy/platform/systemd/heist-expiry.timer'), 0o644)}
    version = adapter.state/'internal-runtime/versions'/transaction.plan.target
    hashes = {str(path): digest(body) for path,(body,_) in planned.items()}
    hashes.update({str(version/'metadata.json'): digest((json.dumps(receipt,sort_keys=True)+'\n').encode()),
                   str(version/'gunicorn.whl'): digest(wheel)})
    # Recovery must know expected bytes even if power fails on the first write.
    transaction.save(target_configuration_hashes=hashes)
    from heist.web_runtime import assert_directory, install_internal
    for path, (body, mode) in planned.items():
        assert_directory(path.parent)
        if path.is_symlink():
            raise RuntimeError('Unexpected symlink in host deployment configuration')
    install_internal(runtime, adapter.state/'internal-runtime', transaction.plan.target, transaction.plan.runtime_bundle['sha256'])
    for path, (body, mode) in planned.items():
        write_file(path, body, mode=mode)
    from dotenv import dotenv_values
    adapter.environment = dotenv_values(adapter.config.backend_env)
    adapter.command(['systemctl', 'daemon-reload'])


def adopt_templates(adapter, transaction):
    """Adopt only UUID-bound stopped templates already covered by this checkpoint."""
    from types import SimpleNamespace
    from heist.infrastructure.proxmox.identity import ownership_marker, ownership_tags
    from .template_checkpoint import require_same_vm
    changes = []
    for identifier, saved in transaction.data['template_catalogue'].items():
        if saved.get('absent'):
            continue
        vm = SimpleNamespace(vmid=int(identifier))
        config = adapter.configuration(vm)
        require_same_vm(config, saved)
        if adapter.is_running(vm):
            raise RuntimeError('Cannot adopt a running template')
        tags = config.get('tags', '')
        if any(tag.startswith('heist-vm-') and tag != 'heist-vm-'+identifier for tag in tags.split(';')):
            raise RuntimeError('Template has a conflicting managed ownership tag')
        marker = ownership_marker(vm.vmid, template=True)
        description = config.get('description', '')
        if marker not in description.splitlines():
            description = description+'\n'+marker if description else marker
        changes.append((vm.vmid, ownership_tags(vm.vmid,tags), description))
    # Confirm the entire set before modifying the first template.
    for vmid, tags, description in changes:
        adapter.command(['qm', 'set', vmid, '--tags', tags, '--description', description])


def deploy(adapter, transaction):
    if not getattr(adapter.config, 'web_certificate_key', None) or not getattr(adapter.config, 'web_hostname', None):
        raise ValueError('Declare the browser hostname and certificate key before deployment')
    stage_host(adapter, transaction)
    adopt_templates(adapter, transaction)
    receipt = deploy_guest(adapter, transaction)
    adapter.command(['systemctl', 'start', 'backend'])
    host = {key:dict(value) for key,value in transaction.data['host_services'].items()}
    host['heist-expiry.timer'] = {'installed': True, 'enabled': True, 'active': True}
    host['heist-expiry.service'] = {'installed': True, 'enabled': False, 'active': False}
    web = {key:dict(value) for key,value in transaction.data['web_services'].items()}
    for name in ('apache2','heist-web','heist-artifacts'):
        web[name] = {'installed': True, 'enabled': True, 'active': True}
    transaction.save(target_host_services=host, target_web_services=web)
    return receipt


def verify_guest(adapter, commit):
    program = r'''
import hashlib,json,sys
from pathlib import Path
commit=json.load(sys.stdin)['commit']
current=Path('/opt/heist-web/current')
if not current.is_symlink() or current.readlink()!=Path('versions')/commit:
    raise RuntimeError('Unexpected selected browser runtime')
sys.path.insert(0,str(current/'source'))
from heist.web_runtime import verify
from heist.ui_assets import verify_installation
receipt=json.loads(Path('/var/lib/heist/browser-deployment.json').read_text())
if receipt['commit']!=commit or receipt['static_root']!='/var/www/heist-releases/'+commit:
    raise RuntimeError('Browser deployment receipt differs')
verify(current.parent/'versions'/commit,commit,receipt['runtime_sha256'])
verify_installation(receipt['static_root'],commit)
for name,expected in (('/etc/heist/web.env',receipt['web_environment_sha256']),('/etc/apache2/sites-available/heist.conf',receipt['apache_sha256'])):
    if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
        raise RuntimeError('Browser deployment configuration changed')
'''
    adapter.remote(adapter.config.vm('web'), program, {'commit': commit})
