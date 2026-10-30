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

from heist.config import DatabaseSettings
from heist.files import private_directory, sha256, write_json
from heist.maintenance.database import Backups, PostgreSQL
from .health import probe
from .manifest import blob, build_plan, git, revision
from .migrations import migrate
from . import web
from .tasks import Tasks


class PVE:
    units = ('pool_manager','cleanup','backend')

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
        if os.geteuid()!=0 or not Path('/etc/pve/local').is_dir():
            raise RuntimeError('Rollouts require root on the declared Proxmox host')
        if sys.version_info<(3,12):raise RuntimeError('Rollout runner requires Python 3.12 or newer')
        if self.config_sha256!=plan.config_sha256:raise RuntimeError('Deployment configuration differs from the reviewed plan')
        if not self.command(['pveversion']).decode().startswith('pve-manager/9.'):
            raise RuntimeError('Release protocol v1 supports Proxmox VE 9 only')
        if str(self.installation.resolve())!=plan.installation or revision(self.installation,'HEAD')!=plan.source:
            raise RuntimeError('Installed source changed after planning')
        if not plan.rollback:
            if build_plan(self.installation,plan.target,plan.manifest_path,self.config_sha256)!=plan:
                raise RuntimeError('Release/configuration changed after planning')
        if self.database.host!=self.config.vm('database').host:
            raise RuntimeError('The configured database is not the checkpointed database VM')
        # Only known generated installer shims/metadata may differ from Git.
        dirty=git(self.installation,'diff','--name-only','HEAD').decode().splitlines()
        generated={}
        for name in dirty:
            path=self.installation/name
            if name.startswith('heist.egg-info/'):
                generated[name]=path.read_bytes().hex()
                continue
            if name in ('bin/install','bin/api','bin/cleanup','bin/pool_manager') and self._old_shim(path):
                generated[name]=path.read_bytes().hex()
                continue
            raise RuntimeError('Tracked installation source is locally modified: '+name)
        self.generated=generated
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
        if shutil.disk_usage(backup).free<capacity+16*1024**3:
            raise RuntimeError('Backup volume needs all infrastructure virtual capacities plus 16 GiB free')
        if self.marker.exists():raise RuntimeError('An existing maintenance transaction must be resumed first')
        self.config.vm('web').ssh.run(['sh', '-c',
            'command -v iptables ip6tables iptables-restore ip6tables-restore composer apache2ctl python3 >/dev/null'])
        # Prove the asynchronous API transport before entering maintenance.
        self.request('GET', '/nodes/' + self.node + '/qemu', None)
        self.assert_idle(allow_ready=True)
        self._health(legacy=True,local_web=False)

    def _old_shim(self,path):
        if not path.is_file():return False
        text=path.read_text()
        module={'install':'setup.install','api':'backend.api','cleanup':'backend.cleanup','pool_manager':'backend.pool_manager'}.get(path.name)
        if module is None:return False
        # Match the exact old installer-generated body, never a local custom script.
        expected=f'''#!/usr/bin/env bash
set -e

cd "{self.installation}" || {{
  echo "Failed to cd to {self.installation}" >&2
  exit 1
}}

exec "{self.installation}/.venv/bin/python" -m {module} "$@"
'''
        return text==expected

    def _health(self, *, legacy, local_web):
        endpoint=self.config.api_url.rstrip('/')+'/health/ready'
        status=probe(endpoint,self.config.api_certificate,
            headers={'Authentication-Token':self.environment['BACKEND_AUTHENTICATION_TOKEN']},
            statuses=(200,404) if legacy else (200,), ready_json=True)
        if status==404 and not legacy:raise RuntimeError('New backend has no readiness endpoint')
        with closing(self.database.connect()) as connection:
            with connection.cursor() as cursor:cursor.execute('SELECT 1');assert cursor.fetchone()==(1,)
        self.remote(self.config.vm('web'),web.LOCAL_HEALTH,{'certificate':self.config.web_certificate})
        for command in self.config.monitoring_checks:
            self.config.vm('monitoring').ssh.run(command,timeout=30)

    def _host_guard(self):
        private_directory(self.state)
        self.marker.touch(mode=0o600,exist_ok=True)
        for unit in ('pool_manager','cleanup'):
            directory=Path('/etc/systemd/system')/(unit+'.service.d');directory.mkdir(exist_ok=True)
            (directory/'heist-maintenance.conf').write_text('[Unit]\nConditionPathExists=!'+str(self.marker)+'\n')
        directory=Path('/etc/systemd/system/backend.service.d');directory.mkdir(exist_ok=True)
        (directory/'heist-maintenance.conf').write_text('[Service]\nEnvironment='+json.dumps('HEIST_MAINTENANCE_FILE='+str(self.marker))+'\n')
        cron=Path('/etc/cron.d/pool_size_prediction')
        if cron.exists():
            lines=cron.read_text().splitlines()
            guarded=[]
            for line in lines:
                if line.strip() and not line.lstrip().startswith('#') and str(self.installation/'backend/pool_size_prediction.py') in line and 'HEIST_MAINTENANCE_GUARD' not in line:
                    fields=line.split(None,6)
                    if len(fields)!=7:raise RuntimeError('Unknown prediction cron format')
                    line=' '.join(fields[:6])+' test ! -e '+shlex.quote(str(self.marker))+' && '+fields[6]+' # HEIST_MAINTENANCE_GUARD'
                guarded.append(line)
            cron.write_text('\n'.join(guarded)+'\n')
        self.command(['systemctl','daemon-reload'])

    def quiesce(self, transaction):
        if 'host_services' not in transaction.data:
            services={}
            for unit in self.units:
                services[unit]={name:subprocess.run(['systemctl',verb,'--quiet',unit],capture_output=True).returncode==0
                    for name,verb in [('active','is-active'),('enabled','is-enabled')]}
            web_services=json.loads(self.remote(self.config.vm('web'),web.CAPTURE_SERVICES))
            transaction.save(host_services=services,web_services=web_services,generated=getattr(self,'generated',{}))
        self._host_guard()
        self.remote(self.config.vm('web'),web.INSTALL_GUARD,{'program':web.FIREWALL})
        self.remote(self.config.vm('web'),web.QUIESCE)
        self.command(['systemctl','stop',*self.units],timeout=180)
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
            script='from backend.teardown_challenge import teardown_challenge\nimport json,sys\nfor identifier in json.load(sys.stdin):teardown_challenge(identifier)\n'
            subprocess.run([str(self.installation/'.venv/bin/python'),'-c',script],cwd=self.installation,
                input=json.dumps(ready).encode(),check=True,timeout=self.config.timeout)
        self.assert_idle(allow_ready=False)
        transaction.save(protected_hashes=self.protected_hashes(transaction.plan.protected_tables))

    def _prediction_processes(self):
        for process in Path('/proc').glob('[0-9]*'):
            try:
                arguments=(process/'cmdline').read_bytes().split(bytes([0]))
                if str(self.installation/'backend/pool_size_prediction.py').encode() in arguments:
                    yield process.name
            except OSError:
                continue

    def checkpoint(self, transaction):
        directory=private_directory(Path(self.config.backup_directory)/transaction.path.name)
        transaction.save(backup_directory=str(directory))
        manager=Backups(PostgreSQL(self.database,self.config.vm('database').ssh),directory/'database')
        dump=manager.create('release')
        transaction.save(database_backup=str(dump))
        for role in ('web','monitoring','database'):
            vm=self.config.vm(role)
            if self.is_running(vm):self.command(['qm','shutdown',vm.vmid,'--timeout','180'],timeout=210)
            if self.is_running(vm):raise RuntimeError('VM did not shut down cleanly: '+role)
        snapshots={}
        for vm in self.config.vms:
            self.tasks.run(transaction,'backup-'+vm.role,'/nodes/'+self.node+'/vzdump',
                {'vmid':vm.vmid,'mode':'stop','compress':'zstd','dumpdir':str(directory),'remove':0})
            files=list(directory.glob('vzdump-qemu-'+str(vm.vmid)+'-*.vma.zst'))
            if len(files)!=1:raise RuntimeError('No unique completed VM archive: '+vm.role)
            self._verify_archive(transaction,files[0])
            snapshots[vm.role]={'path':str(files[0]),'sha256':sha256(files[0]),'bytes':files[0].stat().st_size}
            transaction.save(snapshots=snapshots)
        git(self.installation,'update-ref','refs/heist/releases/'+transaction.plan.target,transaction.plan.target)
        git(self.installation,'bundle','create',str(directory/'source.bundle'),'--all')
        files=[Path(self.config.backend_env),self.installation/'setup/.env',Path(self.config.api_certificate)]
        key=self.environment.get('BACKEND_CERTIFICATE_KEY_FILE')
        if key:files.append(Path(key))
        hashes={str(path):sha256(path) for path in files if path.is_file()}
        with tarfile.open(directory/'host-configuration.tar.gz','w:gz') as archive:
            for path in files:
                if path.is_file():archive.add(path,arcname=str(path).lstrip('/'),recursive=False)
        transaction.save(preserved_files=hashes)
        write_json(directory/'checkpoint.json',transaction.data)

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
        for name in transaction.data.get('generated',{}):
            if git(self.installation,'ls-tree','HEAD','--',name):git(self.installation,'restore','--source=HEAD','--',name)
        # Previously generated service shims were untracked. Preserve exact known
        # shims before installing their explicitly versioned replacements.
        replaced={}
        tracked=set(git(self.installation,'ls-files','-z').decode().split('\0'))
        for name in ('bin/api','bin/pool_manager','bin/cleanup'):
            path=self.installation/name
            if path.exists() and name not in tracked and git(self.installation,'ls-tree',commit,'--',name):
                if not self._old_shim(path):raise RuntimeError('Unknown untracked service shim: '+name)
                replaced[name]=path.read_bytes().hex();path.unlink()
        if replaced:transaction.save(replaced_shims=replaced)
        self.command(['git','-C',self.installation,'checkout','--detach',commit])

    def deploy(self,transaction):
        self._checkout(transaction,transaction.plan.target)
        self.start_vms()
        plan=transaction.plan
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
        self.command(['systemctl','start','backend'])

    def migrate(self,transaction):
        # Never retry a migration after an ambiguous failure. Recovery owns that decision.
        migrate(self.database,transaction.plan)

    def verify(self,transaction,*,target):
        for name,digest in transaction.data.get('preserved_files',{}).items():
            if sha256(name)!=digest:raise RuntimeError('Preserved deployment configuration changed')
        legacy=not target or transaction.data['kind']=='rollback'
        self.wait(lambda:self._health(legacy=legacy,local_web=True),'platform health')
        expected=transaction.data.get('expected_target_hashes',transaction.data.get('protected_hashes'))
        if expected is not None and self.protected_hashes(transaction.plan.protected_tables)!=expected:
            raise RuntimeError('Protected student/grade data changed')

    def restore(self,transaction,*,checkpoint=None):
        checkpoint=checkpoint or transaction
        self.tasks.settle(transaction)
        snapshots=checkpoint.data['snapshots']
        if set(snapshots)!={vm.role for vm in self.config.vms}:raise RuntimeError('Checkpoint is incomplete')
        # Validate every archive before stopping/replacing any infrastructure VM.
        for item in snapshots.values():
            path=Path(item['path'])
            if path.stat().st_size!=item['bytes'] or sha256(path)!=item['sha256']:raise RuntimeError('Recovery archive checksum differs')
        self._host_guard()
        self.command(['systemctl','stop',*self.units],timeout=180)
        for vm in self.config.vms:
            if self.is_running(vm):self.command(['qm','shutdown',vm.vmid,'--timeout','180'],timeout=210)
            if self.is_running(vm):raise RuntimeError('Refusing to overwrite a live VM')
        for vm in self.config.vms:
            self.tasks.run(transaction,'restore-'+checkpoint.path.name+'-'+vm.role,'/nodes/'+self.node+'/qemu',
                {'archive':snapshots[vm.role]['path'],'vmid':vm.vmid,'force':1})
        self._checkout(transaction,checkpoint.plan.source)
        for name,hexadecimal in checkpoint.data.get('replaced_shims',{}).items():
            path=self.installation/name;path.write_bytes(bytes.fromhex(hexadecimal));path.chmod(0o755)
        for name,hexadecimal in checkpoint.data.get('generated',{}).items():
            path=self.installation/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(bytes.fromhex(hexadecimal))
        transaction.save(expected_target_hashes=checkpoint.data['protected_hashes'],
            resume_host_services=checkpoint.data['host_services'],resume_web_services=checkpoint.data['web_services'])
        self.start_vms()
        # Restored web checkpoints intentionally retain their maintenance gate.
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
        services=transaction.data.get('resume_host_services',transaction.data['host_services'])
        web_services=transaction.data.get('resume_web_services',transaction.data['web_services'])
        self.start_vms()
        self.marker.unlink(missing_ok=True)
        if not transaction.data.get('writers_may_have_resumed'):
            self.assert_idle(allow_ready=False)
            self.command(['systemctl','start','backend','cleanup'],timeout=180)
            transaction.save(writers_may_have_resumed=True)
        for unit,state in services.items():
            self.command(['systemctl','enable' if state['enabled'] else 'disable',unit])
            if state['active']:self.command(['systemctl','start',unit],timeout=180)
        self.remote(self.config.vm('web'),web.FINISH,{'services':web_services,'open':False})
        self.wait(lambda:self._health(legacy=True,local_web=True),'post-start health')
        self.remote(self.config.vm('web'),web.FINISH,{'services':web_services,'open':True})
