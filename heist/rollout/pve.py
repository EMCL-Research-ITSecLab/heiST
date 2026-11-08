"""Proxmox adapter for the release state machine. No work is performed at import."""
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import uuid
from types import SimpleNamespace

from heist.config import DatabaseSettings
from heist import ui_assets

from heist.files import fsync_directory, private_directory, sha256, write_file, write_json
from heist.maintenance.database import Backups, PostgreSQL
from .health import probe
from .manifest import blob, build_plan, git, revision
from .migrations import migrate
from .legacy import module_for
from .host import prediction_cron
from . import web
from .tasks import Tasks


UI_AGENT = Path(ui_assets.__file__).read_text().split("if __name__ == '__main__':")[0]

class PVE:
    units = ('pool_manager','cleanup','backend','heist-expiry.timer','heist-expiry.service')

    def __init__(self, config, config_sha256):
        self.config, self.config_sha256 = config, config_sha256
        self.installation = Path(config.installation)
        self.state = Path(config.state_directory)
        self.marker = self.state/'maintenance'
        from dotenv import dotenv_values
        self.environment = dotenv_values(config.backend_env)
        self.database = DatabaseSettings.from_mapping(self.environment)
        self.node = socket.gethostname().split('.')[0]
        from .proxmox_api import LocalAPI
        self.api = LocalAPI()
        self.tasks = Tasks(self.node,self.request)

    def command(self, arguments, *, timeout=600):
        return subprocess.run(list(map(str,arguments)),check=True,capture_output=True,timeout=timeout).stdout

    def request(self, method, path, arguments):
        return self.api.request(method, path, arguments)

    def logged(self, transaction, name, arguments, *, timeout=7200):
        directory=Path(transaction.data['backup_directory'])
        with (directory/(name+'.log')).open('ab') as log:
            subprocess.run(list(map(str,arguments)),check=True,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)

    def remote(self, vm, program, payload=None, *, timeout=600):
        return vm.ssh.run(['python3','-c',program],input=None if payload is None else json.dumps(payload).encode(),timeout=timeout).stdout

    def configuration(self, vm):
        result={}
        for line in self.command(['qm','config',vm.vmid]).decode().splitlines():
            if ': ' in line:
                name,value=line.split(': ',1);result[name]=value
        return result

    def is_running(self, vm):
        return self.command(['qm','status',vm.vmid]).decode().strip()=='status: running'

    def template_configuration(self,vm):
        values=dict(self.configuration(vm))
        stores={}
        for name,value in tuple(values.items()):
            if not re.fullmatch(r'(?:sata|scsi|virtio|ide)\d+',name) or 'media=cdrom' in value or 'cloudinit' in value or re.search(r'(?:^|,)size=',value):
                continue
            volume=value.split(',')[0]
            if ':' not in volume:raise RuntimeError('Template disk does not use managed storage')
            storage=volume.split(':')[0]
            if storage not in stores:
                records=self.request('GET','/nodes/'+self.node+'/storage/'+storage+'/content',{'vmid':vm.vmid})
                if not isinstance(records,list):raise RuntimeError('Template storage capacity was not confirmed')
                stores[storage]={item.get('volid'):item.get('size') for item in records if isinstance(item,dict)}
            size=stores[storage].get(volume)
            if type(size) is not int or size<=0:raise RuntimeError('Template disk virtual capacity was not confirmed')
            # Legacy imports may omit size= in qm config. Use the authenticated
            # storage inventory; never inspect untrusted guest disks as root.
            values[name]=value+',size='+str((size+1023)//1024)+'K'
        return values

    def wait(self, operation, description):
        deadline=time.monotonic()+self.config.timeout
        while True:
            try:
                return operation()
            except (OSError,RuntimeError,subprocess.SubprocessError):
                if time.monotonic()>=deadline:raise RuntimeError('Timed out waiting for '+description)
                time.sleep(2)

    def start_vms(self):
        for role in ('database','monitoring','web'):
            vm=self.config.vm(role)
            def start():
                if not self.is_running(vm):self.command(['qm','start',vm.vmid],timeout=120)
            self.wait(start,'VM start on '+role)
            self.wait(lambda:vm.ssh.run(['true'],timeout=15),'SSH on '+role)
        self.wait(self.database_ready,'database startup')

    def database_ready(self):
        from psycopg2 import OperationalError
        try:
            with closing(self.database.connect()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    if cursor.fetchone() != (1,):
                        raise RuntimeError('Database is not ready')
        except OperationalError as error:
            raise RuntimeError('Database connection is not ready') from error

    def template_catalogue(self):
        from .template_checkpoint import identity
        with closing(self.database.connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT m.id,t.ready_to_launch FROM machine_templates m JOIN challenge_templates t ON t.id=m.challenge_template_id')
                registered=dict(cursor.fetchall())
        inventory=self.request('GET','/nodes/'+self.node+'/qemu',None)
        if not isinstance(inventory,list) or any(not isinstance(item,dict) or type(item.get('vmid')) is not int for item in inventory):
            raise RuntimeError('Template VM inventory was not confirmed')
        present={item['vmid'] for item in inventory}
        result={}
        for identifier,ready in registered.items():
            if identifier in {vm.vmid for vm in self.config.vms}:
                raise RuntimeError('Template identity overlaps infrastructure')
            if identifier not in present:
                if ready:raise RuntimeError('A launchable exercise is missing a template VM')
                result[str(identifier)]={'absent':True}
                continue
            vm=SimpleNamespace(vmid=identifier)
            if self.is_running(vm):raise RuntimeError('Template VMs must be stopped before maintenance')
            result[str(identifier)]=identity(self.template_configuration(vm))
        return result

    def assert_idle(self, *, allow_ready):
        with closing(self.database.connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM users WHERE running_challenge IS NOT NULL')
                if cursor.fetchone()[0]:raise RuntimeError('Students still have active challenges; drain them before maintenance')
                if allow_ready:cursor.execute("SELECT count(*) FROM challenges WHERE lifecycle_state<>'READY'")
                else:cursor.execute('SELECT count(*) FROM challenges')
                if cursor.fetchone()[0]:raise RuntimeError('Challenge provisioning/teardown must finish before rollout')

    def protected_hashes(self, tables):
        from psycopg2 import sql
        class Sink:
            def __init__(self):self.digest=hashlib.sha256()
            def write(self,data):self.digest.update(data.encode() if isinstance(data,str) else data)
        result={}
        with closing(self.database.connect()) as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                for table in tables:
                    sink=Sink()
                    query=sql.SQL('COPY (SELECT to_jsonb(t)::text FROM {} AS t ORDER BY to_jsonb(t)::text) TO STDOUT').format(sql.Identifier('public',table))
                    cursor.copy_expert(query.as_string(connection),sink)
                    result[table]=sink.digest.hexdigest()
        return result

    def preflight(self, plan):
        if plan.schema == 3:
            raise RuntimeError('Browser runtime deployment/recovery adapter is not yet approved; no maintenance was entered')
        if os.geteuid()!=0 or not Path('/etc/pve/local').is_dir():
            raise RuntimeError('Rollouts require root on the declared Proxmox host')
        if sys.version_info<(3,12):raise RuntimeError('Rollout runner requires Python 3.12 or newer')
        if self.config_sha256!=plan.config_sha256:raise RuntimeError('Deployment configuration differs from the reviewed plan')
        if not self.command(['pveversion']).decode().startswith('pve-manager/9.'):
            raise RuntimeError('Release protocol v1 supports Proxmox VE 9 only')
        if str(self.installation.resolve())!=plan.installation or revision(self.installation,'HEAD')!=plan.source:
            raise RuntimeError('Installed source changed after planning')
        if not plan.rollback:
            if build_plan(self.installation,plan.target,plan.manifest_path,self.config_sha256,
                          plan.ui_bundle['path'] if plan.ui_bundle else None,
                          plan.runtime_bundle['path'] if plan.runtime_bundle else None)!=plan:
                raise RuntimeError('Release/configuration changed after planning')
        if self.database.host!=self.config.vm('database').host:
            raise RuntimeError('The configured database is not the checkpointed database VM')
        # Unknown source changes still fail; operator-reviewed hashes are bound
        # to the immutable deployment configuration and privately checkpointed.
        from .source_overrides import capture, for_source
        values=for_source(getattr(self.config,'reviewed_source_files',{}),
                          getattr(self.config,'reviewed_source_commit',None),plan.source)
        reviewed,modes=capture(self.installation,values)
        self.generated_modes=modes
        dirty=git(self.installation,'diff','--name-only','HEAD').decode().splitlines()
        generated=dict(reviewed)
        for name in dirty:
            path=self.installation/name
            if name in reviewed:
                generated[name]=reviewed[name]
                continue
            if name.startswith('heist.egg-info/'):
                generated[name]=path.read_bytes().hex()
                continue
            if name in ('bin/install','bin/api','bin/cleanup','bin/pool_manager') and self._old_shim(path):
                generated[name]=path.read_bytes().hex()
                continue
            raise RuntimeError('Tracked installation source is locally modified: '+name)
        self.generated = generated
        tracked = set(git(self.installation, 'ls-files', '-z').decode().split('\0'))
        source_files = set(git(self.installation, 'ls-tree', '-r', '--name-only', plan.source).decode().splitlines())
        target_files = set(git(self.installation, 'ls-tree', '-r', '--name-only', plan.target).decode().splitlines())
        self.legacy_shims = {}
        for path in (self.installation/'bin').iterdir():
            name = str(path.relative_to(self.installation))
            if name in tracked:
                continue
            module = module_for(path, self.installation)
            if module and module.replace('.', '/') + '.py' in source_files | target_files:
                self.legacy_shims[name] = path.read_bytes().hex()
        for name in target_files:
            path = self.installation/name
            if name not in tracked and (path.exists() or path.is_symlink()) and name not in self.legacy_shims:
                raise RuntimeError('Target source collides with an untracked local file: ' + name)
        capacity=0
        for vm in self.config.vms:
            config=self.configuration(vm)
            if config.get('name')!=vm.name or config.get('template')=='1':raise RuntimeError('VM identity differs: '+vm.role)
            if any(key.startswith(('hostpci','virtiofs','usb')) or key=='args' for key in config):
                raise RuntimeError('Checkpoint cannot cover passthrough/external state: '+vm.role)
            for key,value in config.items():
                if re.fullmatch(r'(?:sata|scsi|virtio|ide)\d+',key) and 'media=cdrom' not in value and 'cloudinit' not in value:
                    if 'backup=0' in value or 'shared=1' in value:raise RuntimeError('Every infrastructure data disk must be backed up exclusively')
                    match=re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([KMGT])(?:,|$)',value)
                    if not match:raise RuntimeError('Cannot determine checkpoint disk capacity')
                    capacity+=int(float(match[1])*1024**('KMGT'.index(match[2])+1))
            if not self.is_running(vm):raise RuntimeError('All infrastructure VMs must be running for baseline verification')
            actual=vm.ssh.run((['sudo','-n'] if vm.user!='root' else [])+['cat','/sys/class/dmi/id/product_uuid']).stdout.decode().strip().lower()
            declared=re.search(r'(?:^|,)uuid=([^,]+)',config.get('smbios1',''))
            if not declared or str(uuid.UUID(declared[1]))!=str(uuid.UUID(actual)):
                raise RuntimeError('SSH endpoint does not match the declared VM UUID: '+vm.role)
        backup=Path(self.config.backup_directory)
        if not backup.is_dir() or backup.stat().st_dev==self.installation.stat().st_dev:
            raise RuntimeError('Provide a mounted backup filesystem separate from installation source')
        templates=self.template_catalogue()
        from .template_checkpoint import disk_capacity, needs_readonly_export
        template_configurations={}
        self.readonly_template_backups={}
        for identifier,item in templates.items():
            if not item.get('absent'):
                configuration=self.template_configuration(SimpleNamespace(vmid=int(identifier)))
                template_configurations[identifier]=configuration
                capacity+=disk_capacity(configuration)
        if template_configurations:
            version=self.command(['dpkg-query','--show','--showformat=${Version}','qemu-server']).decode().strip()
            from heist.maintenance.template_archive import inspect
            for identifier,configuration in template_configurations.items():
                if needs_readonly_export(configuration,version):
                    # Confirm stopped identity and already-read-only raw block
                    # storage before entering maintenance. No disk permissions
                    # or installed Proxmox packages are changed.
                    expected=templates[identifier]['uuid']
                    inspect(int(identifier),expected)
                    self.readonly_template_backups[identifier]=expected
        from .image_checkpoint import inventory
        capacity+=sum(item['bytes'] for item in inventory(self.environment.get('HEIST_ARTIFACT_LIBRARY','/var/lib/vz/import')).values())
        if shutil.disk_usage(backup).free<capacity+16*1024**3:
            raise RuntimeError('Backup volume needs all infrastructure virtual capacities plus 16 GiB free')
        if self.marker.exists():raise RuntimeError('An existing maintenance transaction must be resumed first')
        self.config.vm('web').ssh.run(['sh', '-c',
            'command -v iptables ip6tables iptables-restore ip6tables-restore composer apache2ctl python3 >/dev/null'])
        before = {name: hashlib.sha256(blob(self.installation, plan.source, 'webserver/html/' + name)).hexdigest()
                  for name in plan.web_before if name != 'composer.lock'}
        self.remote(self.config.vm('web'), web.VALIDATE,
                    {'root': self.config.web_root, 'before': before, 'after': {name: None for name in plan.web_after if name != 'composer.lock'}})
        # Prove the asynchronous API transport before entering maintenance.
        self.request('GET', '/nodes/' + self.node + '/qemu', None)
        self.assert_idle(allow_ready=True)
        self._health(legacy=True,local_web=False)

    def _old_shim(self, path):
        expected = {'install': 'setup.install', 'api': 'backend.api',
                    'cleanup': 'backend.cleanup', 'pool_manager': 'backend.pool_manager'}
        return expected.get(path.name) is not None and module_for(path, self.installation) == expected[path.name]

    def browser_runtime_active(self):
        root = getattr(self, 'installation', None)
        state = getattr(self, 'state', None)
        return bool(root and state and (root/'heist/api/internal_serve.py').is_file()
                    and (state/'internal-runtime/current').is_symlink())

    def legacy_browser_role(self):
        if self.browser_runtime_active():return None
        from .browser_configuration import legacy_database_role
        from .browser_role import inspect_legacy
        name=legacy_database_role(self.installation,self.environment)
        with closing(self.database.connect()) as connection:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:inspect_legacy(cursor,name)
        return name

    def _health(self, *, legacy, local_web, frontend=False):
        endpoint=self.config.api_url.rstrip('/')+'/health/ready'
        browser = self.browser_runtime_active()
        certificate = '/etc/pve/local/pve-ssl.pem' if browser else self.config.api_certificate
        status=probe(endpoint,certificate,
            headers={'Authentication-Token':self.environment['BACKEND_AUTHENTICATION_TOKEN']},
            statuses=(200,404) if legacy and not browser else (200,), ready_json=True)
        if status==404 and not legacy:raise RuntimeError('New backend has no readiness endpoint')
        with closing(self.database.connect()) as connection:
            with connection.cursor() as cursor:cursor.execute('SELECT 1');assert cursor.fetchone()==(1,)
        self.remote(self.config.vm('web'),web.LOCAL_HEALTH,{'certificate':self.config.web_certificate, 'frontend': frontend, 'browser': browser})
        for command in self.config.monitoring_checks:
            self.config.vm('monitoring').ssh.run(command,timeout=30)

    def _host_guard(self):
        private_directory(self.state)
        write_file(self.marker, 'maintenance\n')
        for unit in ('pool_manager','cleanup'):
            directory=Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
            write_file(directory/'heist-maintenance.conf', '[Unit]\nConditionPathExists=!'+str(self.marker)+'\n', mode=0o644)
        directory=Path('/etc/systemd/system/backend.service.d');directory.mkdir(exist_ok=True)
        write_file(directory/'heist-maintenance.conf', '[Service]\nEnvironment='+json.dumps('HEIST_MAINTENANCE_FILE='+str(self.marker))+'\n', mode=0o644)
        cron=Path('/etc/cron.d/pool_size_prediction')
        if cron.exists():
            write_file(cron, prediction_cron(cron.read_text(), self.installation, self.marker), mode=0o644)
        self.command(['systemctl','daemon-reload'])

    def quiesce(self, transaction):
        if 'host_services' not in transaction.data:
            services={}
            units=self.units
            if transaction.plan.schema == 3:
                from . import vpn
                transaction.save(vpn_identity=vpn.inspect())
                units=(*units,vpn.UNIT)
            for unit in units:
                services[unit]={name:subprocess.run(['systemctl',verb,'--quiet',unit],capture_output=True).returncode==0
                    for name,verb in [('active','is-active'),('enabled','is-enabled')]}
                services[unit]['installed']=subprocess.run(['systemctl','show','--property=LoadState','--value',unit],capture_output=True,text=True).stdout.strip()!='not-found'
            if self.browser_runtime_active():
                program = 'import json;from pathlib import Path;values=[json.loads(line.split("=",1)[1]) for line in Path("/etc/heist/web.env").read_text().splitlines() if line.startswith("DB_USER=")];assert len(values)==1;print(json.dumps(values[0]))'
                previous_role = json.loads(self.remote(self.config.vm('web'),program))
                from .browser_role import validate
                validate(previous_role,'a'*64)
                transaction.save(previous_browser_role=previous_role)
            elif transaction.plan.schema == 3:
                transaction.save(legacy_browser_role=self.legacy_browser_role())
            web_services=json.loads(self.remote(self.config.vm('web'),web.CAPTURE_SERVICES))
            web_runtime=json.loads(self.remote(self.config.vm('web'),web.CAPTURE_RUNTIME, {'root': self.config.web_root}))
            transaction.save(host_services=services, web_services=web_services, web_runtime=web_runtime,
                generated=getattr(self, 'generated', {}), generated_modes=getattr(self,'generated_modes',{}),
                legacy_shims=getattr(self, 'legacy_shims', {}))
        self._host_guard()
        self.remote(self.config.vm('web'),web.INSTALL_GUARD,{'program':web.FIREWALL})
        self.remote(self.config.vm('web'),web.QUIESCE)
        self.command(['systemctl','stop',*[name for name,state in transaction.data['host_services'].items() if state.get('installed',True)]],timeout=180)
        deadline=time.monotonic()+120
        while any(self._prediction_processes()):
            if time.monotonic()>deadline:raise RuntimeError('Prediction worker did not finish')
            time.sleep(1)
        self.assert_idle(allow_ready=True)
        with closing(self.database.connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM challenges WHERE lifecycle_state='READY'")
                ready=[row[0] for row in cursor.fetchall()]
        if ready:
            prefix = 'heist.platform.challenges' if (self.installation/'heist/platform/challenges/teardown.py').exists() else ('heist.backend' if (self.installation/'heist/backend/teardown_challenge.py').exists() else 'backend')
            module = prefix + ('.teardown' if prefix == 'heist.platform.challenges' else '.teardown_challenge')
            script=f'from {module} import teardown_challenge\nimport json,sys\nfor identifier in json.load(sys.stdin):teardown_challenge(identifier)\n'
            subprocess.run([str(self.installation/'.venv/bin/python'),'-c',script],cwd=self.installation,
                input=json.dumps(ready).encode(),check=True,timeout=self.config.timeout)
        self.assert_idle(allow_ready=False)
        transaction.save(protected_hashes=self.protected_hashes(transaction.plan.protected_tables))

    def _prediction_processes(self):
        for process in Path('/proc').glob('[0-9]*'):
            try:
                arguments=(process/'cmdline').read_bytes().split(bytes([0]))
                scripts = {str(self.installation/name).encode() for name in ('backend/pool_size_prediction.py', 'heist/backend/pool_size_prediction.py', 'heist/platform/pools/prediction.py')}
                module = any(name in arguments for name in (b'heist.platform.pools.prediction', b'heist.backend.pool_size_prediction', b'backend.pool_size_prediction')) and b'-m' in arguments
                if scripts.intersection(arguments) or module:
                    yield process.name
            except OSError:
                continue

    def checkpoint_vm(self,transaction,vm,directory):
        expected=getattr(self,'readonly_template_backups',{}).get(str(vm.vmid))
        if expected:
            if vm.role!='template-'+str(vm.vmid):
                raise RuntimeError('Read-only export is restricted to checkpointed template identities')
            from datetime import datetime,timezone
            from heist.maintenance.template_archive import create
            stamp=datetime.now(timezone.utc).strftime('%Y_%m_%d-%H_%M_%S')
            path=directory/('vzdump-qemu-'+str(vm.vmid)+'-'+stamp+'.vma.zst')
            exports=dict(transaction.data.get('readonly_template_exports',{}))
            exports[str(vm.vmid)]={'state':'EXPORTING','file':path.name,'uuid':expected}
            transaction.save(readonly_template_exports=exports)
            receipt=create(vm.vmid,expected,path)
            exports[str(vm.vmid)]={**receipt,'state':'EXPORTED_UNVERIFIED'}
            transaction.save(readonly_template_exports=exports)
        else:
            self.tasks.run(transaction,'backup-'+vm.role,'/nodes/'+self.node+'/vzdump',
                {'vmid':vm.vmid,'mode':'stop','compress':'zstd','dumpdir':str(directory),'remove':0})
        files=list(directory.glob('vzdump-qemu-'+str(vm.vmid)+'-*.vma.zst'))
        if len(files)!=1:raise RuntimeError('No unique completed VM archive: '+vm.role)
        self._verify_archive(transaction,files[0])
        if expected:
            exports[str(vm.vmid)]['state']='ARCHIVE_VERIFIED'
            transaction.save(readonly_template_exports=exports)
        return files[0]

    def checkpoint(self, transaction):
        directory=private_directory(Path(self.config.backup_directory)/transaction.path.name)
        transaction.save(backup_directory=str(directory))
        from .identifiers import preserve
        transaction.save(id_watermarks=preserve(self.database,self.state/'id-watermarks.json'))
        templates=self.template_catalogue()
        transaction.save(template_catalogue=templates)
        from .image_checkpoint import create
        library=self.environment.get('HEIST_ARTIFACT_LIBRARY','/var/lib/vz/import')
        transaction.save(image_checkpoint=create(library,directory/'image-library'))
        if transaction.plan.ui_bundle:
            from heist.ui_assets import inspect_bundle, digest
            bundle = transaction.plan.ui_bundle
            data = Path(bundle['path']).read_bytes()
            if digest(data) != bundle['sha256']:
                raise RuntimeError('Frontend bundle changed after planning')
            inspect_bundle(data, transaction.plan.target)
            write_file(directory/'frontend.tar.gz', data)
            transaction.save(ui_bundle_checkpoint=str(directory/'frontend.tar.gz'))
        if transaction.plan.runtime_bundle:
            from heist.runtime_bundle import digest,inspect_bundle
            bundle=transaction.plan.runtime_bundle
            data=Path(bundle['path']).read_bytes()
            if digest(data)!=bundle['sha256']:raise RuntimeError('Browser runtime changed after planning')
            inspect_bundle(data,transaction.plan.target)
            write_file(directory/'web-runtime.tar.gz',data)
            transaction.save(runtime_bundle_checkpoint=str(directory/'web-runtime.tar.gz'))
        manager=Backups(PostgreSQL(self.database,self.config.vm('database').ssh),directory/'database')
        dump=manager.create('release')
        transaction.save(database_backup=str(dump))
        for role in ('web','monitoring','database'):
            vm=self.config.vm(role)
            if self.is_running(vm):self.command(['qm','shutdown',vm.vmid,'--timeout','180'],timeout=210)
            if self.is_running(vm):raise RuntimeError('VM did not shut down cleanly: '+role)
        snapshots={}
        template_vms=[SimpleNamespace(role='template-'+identifier,vmid=int(identifier))
                      for identifier,item in templates.items() if not item.get('absent')]
        for vm in (*self.config.vms,*template_vms):
            archive=self.checkpoint_vm(transaction,vm,directory)
            if vm.role.startswith('template-'):
                from .template_checkpoint import identity
                if identity(self.template_configuration(vm))!=templates[str(vm.vmid)]:
                    raise RuntimeError('Template identity changed during checkpoint')
            with archive.open('rb') as stream:
                os.fsync(stream.fileno())
            snapshots[vm.role]={'path':str(archive),'sha256':sha256(archive),'bytes':archive.stat().st_size}
            transaction.save(snapshots=snapshots)
        git(self.installation,'update-ref','refs/heist/releases/'+transaction.plan.target,transaction.plan.target)
        git(self.installation,'bundle','create',str(directory/'source.bundle'),'--all')
        from .internal_runtime import capture
        runtime=capture(self.state/'internal-runtime')
        transaction.save(internal_runtime=runtime)
        files=self.host_configuration_paths(runtime)
        transaction.save(absent_host_files=[str(path) for path in files if not path.exists()])
        hashes={str(path):sha256(path) for path in files if path.is_file()}
        with tarfile.open(directory/'host-configuration.tar.gz','w:gz',dereference=True) as archive:
            for path in files:
                if path.is_file():archive.add(path,arcname=str(path).lstrip('/'),recursive=False)
        for name in ('source.bundle', 'host-configuration.tar.gz'):
            with (directory/name).open('rb') as stream:
                os.fsync(stream.fileno())
        fsync_directory(directory)
        transaction.save(preserved_files=hashes)
        transaction.save(host_configuration_sha256=sha256(directory/'host-configuration.tar.gz'))
        write_json(directory/'checkpoint.json',transaction.data)

    def host_configuration_paths(self,runtime=None):
        paths = [Path(self.config.backend_env), self.installation/'setup/.env',
                 self.installation/'config/installer.env', Path(self.config.api_certificate)]
        key = self.environment.get('BACKEND_CERTIFICATE_KEY_FILE')
        if key:
            paths.append(Path(key))
        paths.extend((Path('/etc/systemd/system/backend.service.d/heist-runtime.conf'),
                      Path('/etc/systemd/system/heist-expiry.service'),
                      Path('/etc/systemd/system/heist-expiry.timer'),self.state/'wazuh-api-leaf.pem'))
        paths.extend((Path('/etc/openvpn/server.conf'), Path('/etc/openvpn/crl.pem')))
        from .internal_runtime import paths as runtime_paths
        paths.extend(runtime_paths(self.state/'internal-runtime',runtime))
        return paths

    def _verify_archive(self,transaction,path):
        with (Path(transaction.data['backup_directory'])/'archive-verify.log').open('ab') as log:
            producer=subprocess.Popen(['zstd','-q','-d','-c',str(path)],stdout=subprocess.PIPE,stderr=log)
            try:
                result=subprocess.run(['vma','verify','-'],stdin=producer.stdout,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
                producer.stdout.close()
                if producer.wait(timeout=30)!=0 or result.returncode!=0:raise RuntimeError('VM archive integrity verification failed')
            finally:
                if producer.poll() is None:producer.kill();producer.wait()

    def _checkout(self,transaction,commit):
        current=revision(self.installation,'HEAD')
        if current==transaction.plan.source:
            known=transaction.data.get('generated',{})
        elif current==transaction.plan.target:
            known=transaction.data.get('expected_target_generated',{})
        else:
            raise RuntimeError('Cannot switch an unrecognized installed source revision')
        dirty=git(self.installation,'diff','--name-only','HEAD').decode().splitlines()
        for name in dirty:
            path=self.installation/name
            if name not in known or path.is_symlink() or not path.is_file() or path.read_bytes().hex()!=known[name]:
                raise RuntimeError('Tracked source changed after checkpoint: '+name)
        # This also covers returning from an older customized source after a
        # failed deliberate rollback. Validate every byte before clearing any file.
        for name in dirty:
            git(self.installation,'restore','--source=HEAD','--staged','--worktree','--',name)
        tracked = set(git(self.installation, 'ls-files', '-z').decode().split('\0'))
        # Exact legacy wrappers are private checkpoint data, not maintained commands.
        for name, hexadecimal in transaction.data.get('legacy_shims', {}).items():
            path = self.installation/name
            if name not in tracked and path.exists():
                if not module_for(path, self.installation) or path.read_bytes().hex() != hexadecimal:
                    raise RuntimeError('Legacy wrapper changed after checkpoint: ' + name)
                path.unlink()
        # Compatibility with transactions begun by the first release runner.
        replaced = dict(transaction.data.get('replaced_shims', {}))
        tracked = set(git(self.installation, 'ls-files', '-z').decode().split('\0'))
        for name in ('bin/api', 'bin/pool_manager', 'bin/cleanup'):
            path = self.installation/name
            if path.exists() and name not in tracked and git(self.installation, 'ls-tree', commit, '--', name):
                if not self._old_shim(path):
                    raise RuntimeError('Unknown untracked service shim: ' + name)
                replaced[name] = path.read_bytes().hex()
                path.unlink()
        if replaced:
            transaction.save(replaced_shims=replaced)
        self.command(['git','-C',self.installation,'checkout','--detach',commit])

    def deploy(self,transaction):
        self._checkout(transaction,transaction.plan.target)
        self._host_guard()
        self.start_vms()
        plan=transaction.plan
        if plan.schema == 3:
            from .browser_deployment import deploy
            deploy(self, transaction)
            from .vpn import configure
            configure(transaction)
            return
        before={name:hashlib.sha256(blob(self.installation,plan.source,'webserver/html/'+name)).hexdigest() for name in plan.web_before}
        after={name:hashlib.sha256(blob(self.installation,plan.target,'webserver/html/'+name)).hexdigest() for name in plan.web_after}
        directory=Path(transaction.data['backup_directory'])
        archive_path=directory/'web-source.tar.gz'
        with tarfile.open(archive_path,'w:gz') as archive:
            data=json.dumps({'root':self.config.web_root,'before':before,'after':after}).encode()
            member=tarfile.TarInfo('deployment.json');member.size=len(data);member.mode=0o600;archive.addfile(member,io.BytesIO(data))
            for name in plan.web_after:
                data=blob(self.installation,plan.target,'webserver/html/'+name)
                member=tarfile.TarInfo('files/'+name);member.size=len(data);member.mode=0o644;archive.addfile(member,io.BytesIO(data))
        with archive_path.open('rb') as stream:
            self.config.vm('web').ssh.run(['python3','-c',web.DEPLOY],stdin=stream,timeout=600)
        if plan.ui_bundle:
            payload = Path(transaction.data['ui_bundle_checkpoint']).read_bytes()
            if ui_assets.digest(payload) != plan.ui_bundle['sha256']:
                raise RuntimeError('Checkpointed frontend bundle checksum differs')
            ui_assets.inspect_bundle(payload, plan.target)
            program = UI_AGENT
            program += '\nmain(' + repr(['install', '--bundle', '-', '--commit', plan.target, '--web-root', self.config.web_root]) + ')\n'
            self.config.vm('web').ssh.run(['python3', '-c', program], input=payload, timeout=600)
        self.command(['systemctl','start','backend'])

    def migrate(self,transaction):
        # Never retry a migration after an ambiguous failure. Recovery owns that decision.
        if transaction.plan.schema == 3:
            from .browser_deployment import credentials
            secret = credentials(transaction)
            legacy=transaction.data.get('legacy_browser_role')
            if legacy is not None:
                from .browser_configuration import legacy_database_role
                if legacy_database_role(self.installation,self.environment,transaction.data['preserved_files'])!=legacy:
                    raise RuntimeError('Legacy PHP database-role settings changed during maintenance')
            migrate(self.database,transaction.plan,web_role=secret['role'],web_password=secret['password'],previous_web_role=transaction.data.get('previous_browser_role'),legacy_web_role=legacy)
            environment = {**os.environ, 'HEIST_BACKEND_ENV': str(self.config.backend_env), 'HEIST_MAINTENANCE_FILE': str(self.marker)}
            subprocess.run([str(self.installation/'.venv/bin/python'), '-m', 'heist.platform.cleanup'],
                           cwd=self.installation, env=environment, check=True, capture_output=True, timeout=300)
        else:
            migrate(self.database,transaction.plan)

    def verify_web_runtime(self, transaction):
        if self.browser_runtime_active():
            from .browser_deployment import verify_guest
            verify_guest(self, revision(self.installation, 'HEAD'))
            return
        hashes = transaction.data.get('resume_web_runtime', transaction.data.get('web_runtime'))
        if hashes:
            self.remote(self.config.vm('web'), web.VERIFY_RUNTIME, {'hashes': hashes})

    def verify_source(self, transaction, *, target):
        expected = transaction.plan.target if target else transaction.plan.source
        if revision(self.installation, 'HEAD') != expected:
            raise RuntimeError('Installed commit differs from the transaction')
        allowed = transaction.data.get('expected_target_generated', {}) if target else transaction.data.get('generated', {})
        modes=transaction.data.get('expected_target_generated_modes',{}) if target else transaction.data.get('generated_modes',{})
        for name,data in allowed.items():
            path=self.installation/name
            if not path.is_file() or path.is_symlink() or path.read_bytes().hex()!=data:
                raise RuntimeError('Checkpointed source differs: '+name)
            if name in modes and path.stat().st_mode & 0o7777 != modes[name]:
                raise RuntimeError('Checkpointed source mode differs: '+name)
        for name in git(self.installation, 'diff', '--name-only', 'HEAD').decode().splitlines():
            path = self.installation/name
            if name not in allowed or not path.is_file() or path.read_bytes().hex() != allowed[name]:
                raise RuntimeError('Installed tracked source differs: ' + name)

    def verify(self,transaction,*,target):
        self.verify_source(transaction, target=target)
        legacy_role=transaction.data.get('legacy_browser_role')
        if legacy_role:
            retired=bool(target and transaction.data['kind']!='rollback')
            with closing(self.database.connect()) as connection,connection.cursor() as cursor:
                cursor.execute('SELECT rolcanlogin FROM pg_roles WHERE rolname=%s',(legacy_role,))
                if cursor.fetchone()!=(not retired,):
                    raise RuntimeError('Legacy PHP login policy differs from the recovered/deployed state')
                if retired:
                    cursor.execute('SELECT count(*) FROM pg_stat_activity WHERE usename=%s',(legacy_role,))
                    if cursor.fetchone()[0]:raise RuntimeError('Legacy PHP database sessions remain active')
        if transaction.data.get('vpn_identity'):
            from . import vpn
            vpn.verify_identity(transaction.data['vpn_identity'])
            if target and transaction.data['kind']!='rollback':vpn.ready()
        self.verify_web_runtime(transaction)
        if target and transaction.plan.ui_bundle and transaction.data['kind'] != 'rollback' and transaction.plan.schema != 3:
            program = UI_AGENT + '\nverify_installation(' + repr(self.config.web_root) + ', ' + repr(transaction.plan.target) + ')\n'
            self.config.vm('web').ssh.run(['python3', '-c', program], timeout=60)
        expected_files=dict(transaction.data.get('resume_preserved_files',transaction.data.get('preserved_files',{})))
        if target and transaction.data['kind']!='rollback':expected_files.update(transaction.data.get('target_configuration_hashes',{}))
        for name,digest in expected_files.items():
            if sha256(name)!=digest:raise RuntimeError('Preserved deployment configuration changed')
        legacy=not target or transaction.data['kind']=='rollback'
        self.wait(lambda:self._health(legacy=legacy,local_web=True, frontend=bool(target and transaction.plan.ui_bundle and transaction.data['kind'] != 'rollback')),'platform health')
        expected=transaction.data.get('expected_target_hashes',transaction.data.get('protected_hashes'))
        if expected is not None and self.protected_hashes(transaction.plan.protected_tables)!=expected:
            raise RuntimeError('Protected student/grade data changed')

    def restore(self,transaction,*,checkpoint=None):
        checkpoint=checkpoint or transaction
        self.tasks.settle(transaction)
        snapshots=checkpoint.data['snapshots']
        template_catalogue=checkpoint.data.get('template_catalogue',{})
        template_vms=[SimpleNamespace(role='template-'+identifier,vmid=int(identifier))
                      for identifier,item in template_catalogue.items() if not item.get('absent')]
        expected={vm.role for vm in (*self.config.vms,*template_vms)}
        if set(snapshots)!=expected:raise RuntimeError('Checkpoint is incomplete')
        # Validate every archive before stopping/replacing any infrastructure VM.
        for item in snapshots.values():
            path=Path(item['path'])
            if path.stat().st_size!=item['bytes'] or sha256(path)!=item['sha256']:raise RuntimeError('Recovery archive checksum differs')
        if template_vms:
            from .template_checkpoint import require_same_vm
            present={item['vmid'] for item in self.request('GET','/nodes/'+self.node+'/qemu',None)}
            for vm in template_vms:
                if vm.vmid in present:
                    if self.is_running(vm):raise RuntimeError('Refusing to overwrite a running template VM')
                    require_same_vm(self.template_configuration(vm),template_catalogue[str(vm.vmid)])
        retained={key:item for key,item in transaction.data.get('template_catalogue',{}).items()
                  if not item.get('absent') and template_catalogue.get(key,{}).get('absent',key not in template_catalogue)}
        if retained:
            from .template_checkpoint import require_same_vm
            for identifier,item in retained.items():
                vm=SimpleNamespace(vmid=int(identifier))
                if self.is_running(vm):raise RuntimeError('Newer template VM must remain stopped during rollback')
                require_same_vm(self.template_configuration(vm),item)
            transaction.save(retained_newer_templates=retained)
        if checkpoint.data.get('image_checkpoint'):
            from .image_checkpoint import inspect
            inspect(checkpoint.data['image_checkpoint'],self.environment.get('HEIST_ARTIFACT_LIBRARY','/var/lib/vz/import'))
        from .host_configuration import inspect_checkpoint, restore_files, validate_created_files, remove_created_files
        configuration = None
        if checkpoint.data.get('preserved_files'):
            configuration = inspect_checkpoint(
                Path(checkpoint.data['backup_directory'])/'host-configuration.tar.gz',
                checkpoint.data['preserved_files'], self.host_configuration_paths(checkpoint.data.get('internal_runtime')),
                archive_sha256=checkpoint.data.get('host_configuration_sha256'))
        created={}
        if checkpoint.data.get('absent_host_files'):
            known={**transaction.data.get('preserved_files',{}),**transaction.data.get('target_configuration_hashes',{})}
            created=validate_created_files(checkpoint.data['absent_host_files'],known,self.host_configuration_paths(checkpoint.data.get('internal_runtime')))
        if 'internal_runtime' in checkpoint.data:
            from .internal_runtime import validate_current, paths as runtime_paths
            validate_current(self.state/'internal-runtime')
            runtime_paths(self.state/'internal-runtime',checkpoint.data['internal_runtime'])
        self._host_guard()
        stop=[unit for unit in self.units if unit in ('backend','cleanup','pool_manager') or Path('/etc/systemd/system',unit).exists()]
        self.command(['systemctl','stop',*stop],timeout=180)
        if checkpoint.data.get('vpn_identity'):
            from .vpn import UNIT
            self.command(['systemctl','stop',UNIT],timeout=60)
        for unit in ('heist-expiry.timer','heist-expiry.service'):
            if not checkpoint.data['host_services'].get(unit,{}).get('installed',False) and Path('/etc/systemd/system',unit).exists():
                self.command(['systemctl','disable','--now',unit],timeout=60)
        for vm in self.config.vms:
            if self.is_running(vm):self.command(['qm','shutdown',vm.vmid,'--timeout','180'],timeout=210)
            if self.is_running(vm):raise RuntimeError('Refusing to overwrite a live VM')
        for vm in (*self.config.vms,*template_vms):
            self.tasks.run(transaction,'restore-'+checkpoint.path.name+'-'+vm.role,'/nodes/'+self.node+'/qemu',
                {'archive':snapshots[vm.role]['path'],'vmid':vm.vmid,'force':1})
        if checkpoint.data.get('image_checkpoint'):
            from .image_checkpoint import restore
            receipt=restore(checkpoint.data['image_checkpoint'],
                self.environment.get('HEIST_ARTIFACT_LIBRARY','/var/lib/vz/import'),
                self.state/'image-recovery'/transaction.path.name)
            transaction.save(image_recovery=receipt)
        self._checkout(transaction,checkpoint.plan.source)
        remove_created_files(created)
        if configuration is not None:
            if checkpoint.data.get('internal_runtime'):
                from .internal_runtime import paths as runtime_paths
                private_directory(runtime_paths(self.state/'internal-runtime',checkpoint.data['internal_runtime'])[0].parent)
            restore_files(configuration)
            from dotenv import dotenv_values
            self.environment = dotenv_values(self.config.backend_env)
            self.database = DatabaseSettings.from_mapping(self.environment)
        if 'internal_runtime' in checkpoint.data:
            from .internal_runtime import select
            select(self.state/'internal-runtime',checkpoint.data['internal_runtime'])
        self._host_guard()
        for name,hexadecimal in {**checkpoint.data.get('replaced_shims', {}), **checkpoint.data.get('legacy_shims', {})}.items():
            path=self.installation/name;path.write_bytes(bytes.fromhex(hexadecimal));path.chmod(0o755)
        for name,hexadecimal in checkpoint.data.get('generated',{}).items():
            path=self.installation/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(bytes.fromhex(hexadecimal))
            if name in checkpoint.data.get('generated_modes',{}):path.chmod(checkpoint.data['generated_modes'][name])
        transaction.save(expected_target_hashes=checkpoint.data['protected_hashes'],
            resume_preserved_files=checkpoint.data.get('preserved_files', {}),
            expected_target_generated=checkpoint.data.get('generated', {}),
            expected_target_generated_modes=checkpoint.data.get('generated_modes',{}),
            resume_web_runtime=checkpoint.data.get('web_runtime'),
            resume_host_services=checkpoint.data['host_services'],resume_web_services=checkpoint.data['web_services'])
        self.start_vms()
        # Restored web checkpoints intentionally retain their maintenance gate.
        if transaction.data.get('id_watermarks'):
            from .identifiers import preserve, reconcile
            # The live host history survives every VM restore, including an
            # older checkpoint followed by recovery of the newer safety copy.
            history = preserve(self.database,self.state/'id-watermarks.json')
            for name,value in transaction.data['id_watermarks'].items():
                history[name] = max(history.get(name,0),value)
            reconcile(self.database,history)
        self.remote(self.config.vm('web'),web.INSTALL_GUARD,{'program':web.FIREWALL})
        self.command(['systemctl','start','backend'])
        self.remote(self.config.vm('web'),web.FINISH,{'services':{'apache2':{'active':True,'enabled':False},'cron':{'active':False,'enabled':False}},'open':False})

    def abort_before_deploy(self,transaction):
        if 'host_services' not in transaction.data:return
        self.tasks.settle(transaction)
        self.start_vms()
        self.command(['systemctl','start','backend'])
        self.remote(self.config.vm('web'),web.FINISH,{'services':{'apache2':{'active':True,'enabled':False},'cron':{'active':False,'enabled':False}},'open':False})

    def finish(self,transaction):
        if 'host_services' not in transaction.data:return
        self.verify_source(transaction, target=bool(transaction.data.get('committed')))
        services=transaction.data.get('resume_host_services',transaction.data.get('target_host_services',transaction.data['host_services']))
        web_services=transaction.data.get('resume_web_services',transaction.data.get('target_web_services',transaction.data['web_services']))
        self.start_vms()
        self.verify_web_runtime(transaction)
        self.marker.unlink(missing_ok=True)
        fsync_directory(self.state)
        if not transaction.data.get('writers_may_have_resumed'):
            self.assert_idle(allow_ready=False)
            self.command(['systemctl','start','backend','cleanup'],timeout=180)
            transaction.save(writers_may_have_resumed=True)
        for unit,state in services.items():
            if not state.get('installed',True):continue
            self.command(['systemctl','enable' if state['enabled'] else 'disable',unit])
            if state['active']:self.command(['systemctl','start',unit],timeout=180)
        self.remote(self.config.vm('web'),web.FINISH,{'services':web_services,'open':False})
        self.wait(lambda:self._health(legacy=True,local_web=True),'post-start health')
        self.remote(self.config.vm('web'),web.FINISH,{'services':web_services,'open':True})
