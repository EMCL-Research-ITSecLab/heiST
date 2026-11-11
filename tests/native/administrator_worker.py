"""Real local systemd/SQL/lease recovery; hypervisor commands are inert fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from tests import test_platform_administration as fixture
from heist.platform.jobs.administrator import AdministratorQueue
from heist.rollout import administrator_deployment

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL') and os.geteuid()==0,'Explicit disposable PostgreSQL and local systemd root access required')
class NativeAdministratorWorkerTests(unittest.TestCase):
    setUpClass=classmethod(fixture.PlatformAdministrationTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.PlatformAdministrationTests.tearDownClass.__func__)
    remove_database=classmethod(fixture.PlatformAdministrationTests.remove_database.__func__)
    sql=fixture.PlatformAdministrationTests.sql
    release=fixture.PlatformAdministrationTests.release

    def test_real_unit_executes_once_and_recovers_interrupted_work_without_replay(self):
        fixture.PlatformAdministrationTests.setUp(self)
        temporary=Path(self.temporary.name)
        disk=self.sql("INSERT INTO disk_files(user_id,display_name,proxmox_filename) VALUES(%s,'native-fixture','native-fixture.ova') RETURNING id",(self.user_id,))[0][0]
        template=self.sql("INSERT INTO machine_templates(challenge_template_id,name,disk_file_id,cores,ram_gb) VALUES(%s,'native-target',%s,1,1) RETURNING id",(self.template,disk))[0][0]
        machine=self.sql('INSERT INTO machines(machine_template_id,challenge_id) VALUES(%s,%s) RETURNING id',(template,self.instance))[0][0]
        state=temporary/'fake-hypervisor.json';state.write_text(json.dumps({'id':machine,'state':'running','hang':False,'calls':[]}))
        binary=temporary/'bin';binary.mkdir();fake=binary/'qm'
        program='''#!/usr/bin/python3
import json,sys,time
from pathlib import Path
p=Path(STATE_PATH);v=json.loads(p.read_text());args=sys.argv[1:]
if len(args)<2 or args[1]!=str(v['id']) or args[0] not in ('status','start','shutdown','reboot'):raise SystemExit(2)
if args[0]=='status':print('status: '+v['state']);raise SystemExit(0)
v['calls'].append(args[0]);p.write_text(json.dumps(v))
if v['hang']:time.sleep(120)
v['state']='stopped' if args[0]=='shutdown' else 'running';p.write_text(json.dumps(v))
'''.replace('STATE_PATH',repr(str(state)))
        fake.write_text(program);fake.chmod(0o700)
        wheels=list(Path(os.environ['HEIST_TEST_WHEELHOUSE']).glob('gunicorn-*.whl'))
        self.assertEqual(len(wheels),1,'Provide the reviewed offline Gunicorn wheel')
        runtime=temporary/'state/internal-runtime/current';runtime.mkdir(parents=True)
        shutil.copy2(wheels[0],runtime/'gunicorn.whl')
        commit=subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
        hashes={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT/'heist').rglob('*.py')}
        receipt={'schema':1,'source_commit':commit,'source_files':hashes,'wheel_sha256':hashlib.sha256(wheels[0].read_bytes()).hexdigest()}
        (runtime/'metadata.json').write_text(json.dumps(receipt))
        cleanup=temporary/'cleanup';cleanup.write_text('complete\n')
        environment={'DB_HOST':self.settings.get('host','localhost'),'DB_NAME':self.settings['dbname'],
            'DB_USER':self.settings.get('user','postgres'),'DB_PORT':str(self.settings.get('port',5432)),
            'HEIST_OPERATION_DIRECTORY':str(self.journal.directory),'HEIST_CLEANUP_FILE':str(cleanup),
            'HEIST_MAINTENANCE_FILE':str(temporary/'maintenance'),'HEIST_ARTIFACT_INTAKE':str(temporary/'intake'),
            'HEIST_ARTIFACT_LIBRARY':str(temporary/'images'),'HEIST_NORMALIZED_IMAGES':str(temporary/'normalized'),
            'HEIST_TEMPLATE_LOCK_DIRECTORY':str(temporary/'template-locks')}
        if self.settings.get('password'):environment['DB_PASSWORD']=self.settings['password']
        envfile=temporary/'backend.env';envfile.write_text(''.join(key+'='+json.dumps(value)+'\n' for key,value in environment.items()));envfile.chmod(0o600)
        adapter=SimpleNamespace(installation=ROOT,config=SimpleNamespace(backend_env=envfile),state=temporary/'state')
        with patch('heist.rollout.administrator_deployment.blob',side_effect=lambda repo,target,path:(ROOT/path).read_bytes()):
            unitbody=administrator_deployment.files(adapter,commit)[administrator_deployment.PATH][0].decode()
        # Same unit and runtime guard; fixture uses cached Python and Unix-socket
        # database instead of infrastructure boot dependencies or real qm.
        unitbody=unitbody.replace(str(ROOT/'.venv/bin/python'),sys.executable)
        unitbody=unitbody.replace('--verify-runtime','--verify-runtime --once').replace('TimeoutStopSec=90','TimeoutStopSec=2')
        unitbody=unitbody.replace('After=network-online.target backend.service pve-cluster.service','After=').replace('Wants=network-online.target','')
        unitbody=unitbody.replace('[Service]\n','[Service]\nEnvironment='+json.dumps('PATH='+str(binary)+':/usr/bin:/bin')+'\n')
        name='heist-admin-native-'+uuid.uuid4().hex[:12]+'.service';unit=Path('/run/systemd/system')/name
        queue=AdministratorQueue(self.service)
        def enqueue(action):
            preview=self.service.preview(self.admin,self.instance,action,machine)
            return queue.enqueue(self.admin,self.instance,action,preview['fingerprint'],machine,request_id=uuid.uuid4().hex)
        def command(*args):return subprocess.run(list(args),capture_output=True,text=True,check=True,timeout=15)
        def wait(predicate,label):
            deadline=time.monotonic()+30
            while not predicate():
                if time.monotonic()>deadline:raise AssertionError('Native worker did not confirm '+label)
                time.sleep(.2)
        try:
            unit.write_text(unitbody);unit.chmod(0o600);command('systemctl','daemon-reload')
            first=enqueue('shutdown');command('systemctl','start',name)
            wait(lambda:self.sql('SELECT state FROM administrator_requests WHERE id=%s',(first['job_id'],))==[('SUCCEEDED',)],'completed request')
            wait(lambda:subprocess.run(['systemctl','is-active','--quiet',name]).returncode!=0,'oneshot process exit')
            self.assertEqual(json.loads(state.read_text())['state'],'stopped')
            self.service.status.return_value='stopped';v=json.loads(state.read_text());v['hang']=True;state.write_text(json.dumps(v))
            second=enqueue('start');command('systemctl','start',name)
            wait(lambda:json.loads(state.read_text())['calls']==['shutdown','start'],'in-flight fixture command')
            extra={**os.environ,'HEIST_BACKEND_ENV':str(envfile),'HEIST_INTERNAL_RUNTIME':str(runtime),'PATH':str(binary)+':/usr/bin:/bin'}
            duplicate=subprocess.run([sys.executable,'-m','heist.platform.jobs.administrator','--once','--verify-runtime'],cwd=ROOT,env=extra,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(duplicate.returncode,0,'A second worker acquired the singleton lease')
            command('systemctl','stop',name);command('systemctl','start',name)
            wait(lambda:self.sql('SELECT state FROM administrator_requests WHERE id=%s',(second['job_id'],))==[('NEEDS_REVIEW',)],'interrupted request reconciliation')
            self.assertEqual(json.loads(state.read_text())['calls'],['shutdown','start'])
            queue.resolve(self.admin,second['job_id'],'Verified inert fixture VM state and assignment after interrupted execution',second['job_id'])
            journal=command('journalctl','-u',name,'-n','100','-o','json').stdout
            identities=set()
            for line in journal.splitlines():
                entry=json.loads(line)
                try:body=json.loads(entry.get('MESSAGE',''))
                except (ValueError,TypeError):continue
                if isinstance(body,dict) and body.get('event')=='worker_started':
                    self.assertEqual(entry.get('_UID'),'0');identities.add(entry.get('_SYSTEMD_INVOCATION_ID'))
            self.assertGreaterEqual(len(identities),3)
            self.assertNotIn(None,identities)
            output=os.environ.get('HEIST_NATIVE_EVIDENCE_FILE')
            if output:
                Path(output).write_text(json.dumps({'passed':True,'scope':'real local systemd and PostgreSQL; inert hypervisor fixture',
                    'source_commit':commit,'runtime_source_files_verified':len(hashes),'singleton_verified':True,
                    'interruption_not_replayed':True,'journal_invocations':len(identities),'production_changed':False})+'\n')
        finally:
            subprocess.run(['systemctl','stop',name],capture_output=True,timeout=10)
            unit.unlink(missing_ok=True)
            subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=15)
            subprocess.run(['systemctl','reset-failed',name],capture_output=True,timeout=10)
