"""Verify the actual observer unit over pinned SSH between two isolated VMs.

Uses synthetic service receipts to test transport/systemd/credentials/journaling.
It does not certify the legacy fixture's missing application services as healthy.
The dedicated observer key stays on its VM and is removed after the rehearsal.
"""
import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import shlex
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.local.nested_pilot import ssh_args
from tools.local.recover_pilot_access import validate
from tools.local.verify_pilot_offline import verify
from tools.local.rehearse_monitoring import GUARD

SETUP = r'''
import base64,json,os,re,subprocess,sys
from pathlib import Path
p=json.loads(sys.stdin.buffer.read(2*1024**2))
identity=p['identity']
if not re.fullmatch('[a-f0-9]{12}',identity):raise ValueError('Invalid observer fixture identity')
base=Path('/opt/heist-watchdog-rehearsal')/identity;base.parent.mkdir(mode=0o755,exist_ok=True);base.parent.chmod(0o755);base.mkdir(mode=0o755);base.chmod(0o755)
private=base/'credentials';private.mkdir(mode=0o700)
key=private/'identity'
subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','observer-fixture-'+identity,'-f',str(key)],check=True,capture_output=True)
(private/'known_hosts').write_text('10.0.0.1 '+p['host_key']+'\n');(private/'known_hosts').chmod(0o600)
(private/'config').write_text(json.dumps({'schema':1,'host':'10.0.0.1','user':'root','status_file':p['source_file']}));(private/'config').chmod(0o600)
artifact=base/'watchdog.pyz';artifact.write_bytes(base64.b64decode(p['artifact'],validate=True));artifact.chmod(0o644)
name='heist-watchdog-rehearsal-'+identity
unit=p['unit'].replace('User=heist-archive','User=ubuntu').replace('Group=heist-archive','Group=ubuntu')
unit=unit.replace('/etc/heist/archive/keys/proxmox-logs.key',str(key)).replace('/etc/heist/archive/known_hosts',str(private/'known_hosts'))
unit=unit.replace('/etc/heist/watchdog.json',str(private/'config')).replace('/usr/local/lib/heist/watchdog.pyz',str(artifact))
unit=unit.replace('StateDirectory=heist-watchdog\n','StateDirectory='+name+'\n')
unit=unit.replace('/var/lib/heist-watchdog','/var/lib/'+name)
path=Path('/run/systemd/system')/(name+'.service');path.write_text(unit);path.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
print(json.dumps({'public_key':key.with_suffix('.pub').read_text().strip(),'unit':name+'.service','service_uid':subprocess.check_output(['id','-u','ubuntu'],text=True).strip(),'artifact_sha256':__import__('hashlib').sha256(artifact.read_bytes()).hexdigest()}))
'''

CONTROL = r'''
import json,re,subprocess,sys
from pathlib import Path
p=json.loads(sys.stdin.buffer.read(65537));identity=p['identity']
if not re.fullmatch('[a-f0-9]{12}',identity):raise ValueError('Invalid observer fixture identity')
name='heist-watchdog-rehearsal-'+identity;unit=name+'.service'
base=Path('/opt/heist-watchdog-rehearsal')/identity
if p['action']=='run':
    subprocess.run(['systemctl','reset-failed',unit],capture_output=True)
    result=subprocess.run(['systemctl','start',unit],capture_output=True,timeout=30)
    props=subprocess.check_output(['systemctl','show',unit,'--property=ActiveState,Result,ExecMainStatus,User,InvocationID'],text=True)
    values=dict(line.split('=',1) for line in props.splitlines() if '=' in line)
    status=json.loads((Path('/var/lib')/name/'status.json').read_text())
    journal=subprocess.check_output(['journalctl','-u',unit,'--no-pager','-n','50','-o','json'],text=True)
    messages=[]
    for line in journal.splitlines():
        entry=json.loads(line)
        try:body=json.loads(entry.get('MESSAGE',''))
        except (ValueError,TypeError):continue
        if isinstance(body,dict) and body.get('schema')==1:messages.append({'uid':entry.get('_UID'),'data':body})
    print(json.dumps({'returncode':result.returncode,'properties':values,'receipt':status,'journal':messages[-1:]}))
elif p['action']=='pin':
    value=(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2] if p['wrong'] else p['host_key'].split()[:2])
    (base/'credentials/known_hosts').write_text('10.0.0.1 '+' '.join(value)+'\n')
    print('{}')
elif p['action']=='cleanup':
    subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=30)
    subprocess.run(['systemctl','reset-failed',unit],capture_output=True)
    (Path('/run/systemd/system')/unit).unlink(missing_ok=True)
    for path in (base/'credentials').glob('*'):path.unlink()
    subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True)
    print(json.dumps({'private_key_removed':not (base/'credentials/identity').exists(),'unit_removed':True}))
else:raise ValueError('Invalid observer fixture action')
'''

RUN = GUARD + r'''
import base64,hashlib,re,sys,uuid
from datetime import datetime,timedelta,timezone
p=json.loads(sys.stdin.buffer.read(2*1024**2));source=Path(p['source'])
if not re.fullmatch(r'/opt/heist-monitoring-rehearsal/[a-f0-9]{40}/source',str(source)):raise ValueError('Invalid staged source')
sys.path.insert(0,str(source))
from heist.monitoring.health import check,publish
from heist.monitoring.watchdog import REQUIRED
from heist.remote import SSH
addresses=json.loads(__import__('subprocess').check_output(['ip','-j','addr','show']))
if not any(a.get('local')=='10.0.0.1' for link in addresses for a in link.get('addr_info',[])):raise RuntimeError('Require the isolated fixture backend address')
identity=uuid.uuid4().hex[:12];case=source.parent/'observer-cases'/identity;case.mkdir(mode=0o700,parents=True)
source_file=case/'synthetic-source.json'
host_key=' '.join(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2])
monitor=SSH('10.0.0.103','ubuntu')
def call(program,payload):
    value=monitor.run(['sudo','-n','python3','-c',program],input=json.dumps(payload).encode(),timeout=45)
    return json.loads(value.stdout)
def control(action,**values):return call(p['control'],{'identity':identity,'action':action,'host_key':host_key,**values})
keys=Path('/root/.ssh/authorized_keys');original=keys.read_bytes();entry=None;setup=False
report={'scope':'real SSH/systemd observer with synthetic service receipts','production_changed':False,'synthetic_source':True,'cases':[]}
try:
    setup=True
    value=call(p['setup'],{'identity':identity,'artifact':p['artifact'],'unit':p['unit'],'host_key':host_key,'source_file':str(source_file)})
    if value['artifact_sha256']!=p['artifact_sha256']:raise RuntimeError('Observer artifact changed during staging')
    if not value['service_uid'].isdigit() or int(value['service_uid'])==0:raise RuntimeError('Require a nonroot observer account')
    pub=value['public_key'].split()
    if len(pub)<2 or pub[0]!='ssh-ed25519' or not re.fullmatch('[A-Za-z0-9+/=]{40,100}',pub[1]):raise ValueError('Invalid observer public key')
    command='/usr/bin/head -c 65537 -- '+str(source_file)
    entry=('command="'+command+'",restrict '+pub[0]+' '+pub[1]+' observer-fixture-'+identity+'\n').encode()
    with keys.open('ab') as stream:stream.write((b'' if original.endswith(b'\n') else b'\n')+entry)
    invocations=[]
    for label,failed,stale,wrong in [('healthy',False,False,False),('failed_service',True,False,False),
                                    ('recovered_service',False,False,False),('stale_source',False,True,False),
                                    ('recovered_source',False,False,False),('wrong_host_pin',False,False,True),
                                    ('recovered_pin',False,False,False)]:
        at=datetime.now(timezone.utc)-(timedelta(minutes=5) if stale else timedelta())
        checks=[check(name,'Synthetic service','failed' if failed and index==0 else 'ok','Synthetic transport fixture') for index,name in enumerate(REQUIRED)]
        publish(source_file,{'schema':1,'checked_at':at.isoformat(),'checks':checks})
        control('pin',wrong=wrong)
        outcome=control('run');expected=1 if failed or stale or wrong else 0
        props=outcome['properties'];status=outcome['receipt']['status']
        if (int(props['ExecMainStatus'])!=expected or props['User']!='ubuntu' or status!=('failed' if expected else 'ok')
                or not outcome['journal'] or outcome['journal'][0]['uid']!=value['service_uid']):
            raise RuntimeError('Observer service, credentials, exit code or journal did not match '+label)
        if props['InvocationID'] in invocations:raise RuntimeError('Observer invocation was reused')
        invocations.append(props['InvocationID']);report['cases'].append({'case':label,**outcome})
finally:
    if entry is not None:
        current=keys.read_bytes()
        if current==(original+(b'' if original.endswith(b'\n') else b'\n')+entry):keys.write_bytes(original)
        else:keys.write_bytes(b''.join(line for line in current.splitlines(keepends=True) if line!=entry))
    if setup:report['cleanup']=control('cleanup')
report['passed']=True
(case/'result.json').write_text(json.dumps(report));(case/'result.json').chmod(0o600)
print(json.dumps(report))
'''


def verify_artifact(path,commit):
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Declare the full source commit')
    body=Path(path).read_bytes()
    if len(body)>1024**2:raise ValueError('Oversized observer artifact')
    names={'heist/__init__.py','heist/monitoring/__init__.py','heist/remote.py','heist/monitoring/health.py','heist/monitoring/watchdog.py','__main__.py'}
    with ZipFile(io.BytesIO(body)) as archive:
        files=[item.filename for item in archive.infolist() if not item.is_dir()]
        directories={item.filename for item in archive.infolist() if item.is_dir()}
        if set(files)!=names or len(files)!=len(names) or directories-{'heist/','heist/monitoring/'}:raise ValueError('Unexpected observer artifact files')
        for name in names:
            expected=(b'' if name.endswith('__init__.py') else b'from heist.monitoring.watchdog import main\nraise SystemExit(main())\n' if name=='__main__.py'
                      else subprocess.check_output(['git','-C',str(ROOT),'show',commit+':'+name]))
            if archive.read(name)!=expected:raise ValueError('Observer source differs: '+name)
    return body


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    work=validate(args.work);output=args.output.resolve()
    if work not in output.parents or output.exists():raise ValueError('Use a new evidence directory inside the fixture')
    body=verify_artifact(args.artifact,args.commit)
    unit=subprocess.check_output(['git','-C',str(ROOT),'show',args.commit+':deploy/monitoring/systemd/heist-watchdog.service']).decode()
    verify(work);output.mkdir(mode=0o700,parents=True)
    settings={'source':'/opt/heist-monitoring-rehearsal/'+args.commit+'/source','artifact':base64.b64encode(body).decode(),
              'artifact_sha256':hashlib.sha256(body).hexdigest(),'unit':unit,'setup':SETUP,'control':CONTROL}
    command=shlex.join(['/root/heiST/.venv/bin/python','-c',RUN])
    with (output/'private-stderr.log').open('wb') as errors:
        __import__('os').fchmod(errors.fileno(),0o600)
        result=subprocess.run(ssh_args(work)+[command],input=json.dumps(settings).encode(),stdout=subprocess.PIPE,stderr=errors,timeout=240)
    value=json.loads(result.stdout) if result.returncode==0 else {'passed':False,'returncode':result.returncode}
    value.update(commit=args.commit,artifact_sha256=settings['artifact_sha256'],application_upgrade_rollback_verified=False)
    (output/'result.json').write_text(json.dumps(value,indent=2)+'\n');(output/'result.json').chmod(0o600)
    if result.returncode:raise RuntimeError('Native observer rehearsal failed; inspect its private evidence')
    print(json.dumps({'passed':True,'commit':args.commit,'cases':[c['case'] for c in value['cases']],
                      'nonroot_journal_verified':True,'synthetic_source':True,'application_upgrade_rollback_verified':False,'output':str(output)}))


if __name__=='__main__':main()
