"""Run monitoring component acceptance on the verified offline disposable pilot.

Does not install/upgrade the application or change its Git history. The optional
canary injects four synthetic UDP frames through a temporary veth tc mirror; it
does not certify challenge-NIC mirror coverage or a full-platform upgrade.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from heist.runtime_bundle import inspect_bundle
from tools.local.nested_pilot import ssh_args
from tools.local.recover_pilot_access import validate
from tools.local.verify_pilot_offline import verify

GUARD = r'''
import os,socket,json
from pathlib import Path
if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='heist-pilot' or not Path('/root/pilot-cloud-init-ready').is_file():
    raise RuntimeError('Require the disposable pilot')
proof=json.loads(Path('/root/pilot-offline-verified.json').read_text())
if proof.get('passed') is not True or proof.get('production_accepted') is not False or proof.get('boot_id')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
    raise RuntimeError('Require isolation evidence for this boot')
'''

STAGE = GUARD + r'''
import hashlib,io,re,sys,tarfile
from pathlib import PurePosixPath
commit,expected=sys.argv[1:]
if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Invalid source identity')
body=sys.stdin.buffer.read(128*1024**2+1)
if len(body)>128*1024**2 or hashlib.sha256(body).hexdigest()!=expected:raise ValueError('Runtime checksum differs')
root=Path('/opt/heist-monitoring-rehearsal')/commit
if root.is_symlink() or root.parent.is_symlink():raise ValueError('Unexpected fixture symlink')
root.mkdir(mode=0o700,parents=True,exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as archive:
    seen=set();total=0
    for member in archive:
        path=PurePosixPath(member.name);total+=member.size
        if path.is_absolute() or '..' in path.parts or not member.isfile() or member.name in seen or total>128*1024**2:
            raise ValueError('Unsafe runtime member')
        seen.add(member.name)
        if not member.name.startswith('source/heist/') or not member.name.endswith('.py'):continue
        target=root/member.name
        if any(p.is_symlink() for p in target.parents) or target.is_symlink():raise ValueError('Unexpected fixture source symlink')
        with archive.extractfile(member) as stream:data=stream.read()
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if target.exists() and target.read_bytes()!=data:raise ValueError('Previously staged fixture source changed')
        target.write_bytes(data);target.chmod(0o600)
print(json.dumps({'source':str(root/'source'),'commit':commit,'runtime_sha256':expected}))
'''

# This runs on the monitoring VM through the pilot's existing pinned SSH. The
# ClickHouse certificate is read locally and pinned without exporting any key.
QUERY = r'''
import base64,hashlib,http.client,json,re,ssl,sys,urllib.parse,xml.etree.ElementTree as ET
from pathlib import Path
p=json.loads(sys.stdin.buffer.read(65537))
if not re.fullmatch('[a-f0-9]{32}',p['nonce']):raise ValueError('Invalid canary identity')
effective=Path('/var/lib/clickhouse/preprocessed_configs/config.xml')
tree=ET.parse(effective if effective.exists() else '/etc/clickhouse-server/config.xml')
certificate=tree.findtext('.//openSSL/server/certificateFile')
if not certificate:raise ValueError('Effective ClickHouse server certificate was not confirmed')
pem=Path(certificate).read_text()
leaf=re.search(r'-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----',pem)[0]
fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(leaf)).digest()
context=ssl.create_default_context(cafile=certificate)
# Exact local-file leaf pin replaces hostname matching; chain/expiry checks stay on.
context.check_hostname=False
client=http.client.HTTPSConnection('127.0.0.1',8443,context=context,timeout=5)
try:
    client.connect()
    if hashlib.sha256(client.sock.getpeercert(binary_form=True)).digest()!=fingerprint:raise ValueError('ClickHouse certificate differs')
    query="SELECT count() AS received FROM suricata.dmz_eve_logs WHERE alert_signature='heiST monitoring canary:"+p['nonce']+"' FORMAT JSONEachRow"
    params=urllib.parse.urlencode({'query':query,'readonly':2,'max_execution_time':3,'max_result_rows':1,'max_result_bytes':1024})
    auth=base64.b64encode((p['user']+':'+p['password']).encode()).decode()
    client.request('GET','/?'+params,headers={'Authorization':'Basic '+auth})
    response=client.getresponse();body=response.read(8193)
    if response.status!=200 or len(body)>8192:raise RuntimeError('Canary query was not confirmed')
    value=json.loads(body)
    if not str(value.get('received','')).isdigit():raise ValueError('Invalid canary result')
    print(json.dumps({'received':int(value['received']),'tls_leaf_verified':True}))
finally:client.close()
'''

RUN = GUARD + r'''
import hashlib,re,signal,struct,subprocess,sys,time,tomllib,uuid
from datetime import datetime,timezone
settings=json.loads(sys.stdin.buffer.read(65537))
source=Path(settings['source'])
if not re.fullmatch(r'/opt/heist-monitoring-rehearsal/[a-f0-9]{40}/source',str(source)):raise ValueError('Invalid source path')
sys.path.insert(0,str(source))
from heist.monitoring import health
from heist.remote import SSH
monitor=SSH('10.0.0.103','ubuntu')
def remote(program,payload=None,timeout=30):
    args=['sudo','-n','python3','-'] if payload is None else ['sudo','-n','python3','-c',program]
    try:return monitor.run(args,input=program.encode() if payload is None else json.dumps(payload).encode(),timeout=timeout).stdout
    except subprocess.CalledProcessError as error:
        (case/'query-error.log').write_bytes(error.stderr);(case/'query-error.log').chmod(0o600)
        raise RuntimeError('Fixture canary query failed; inspect the private sensor case evidence') from None
def snapshot():
    return json.loads(monitor.run(['sudo','-n','python3','-','--role','monitoring'],input=Path(health.__file__).read_bytes(),timeout=25).stdout)
def state(value,identifier):
    return next(c['state'] for c in value['checks'] if c['id']==identifier)
def exporter(action):
    if action not in ('start','stop'):raise ValueError('Invalid exporter action')
    monitor.run(['sudo','-n','systemctl',action,'node_exporter.service'],timeout=20)
report={'scope':'monitoring components on a legacy fixture; not application upgrade/rollback acceptance',
        'commit':source.parent.name,'production_changed':False,'host':health.local_snapshot('host'),'monitoring_before':snapshot()}
if not re.fullmatch('[a-f0-9]{32}',settings['evidence_id']):raise ValueError('Invalid evidence identity')
progress=source.parent/'component-runs'/settings['evidence_id']/'result.json';progress.parent.mkdir(mode=0o700,parents=True)
def save_report(phase):
    report['phase']=phase;progress.write_text(json.dumps(report));progress.chmod(0o600)
save_report('baseline_collected')
if settings['faults']:
    if state(report['monitoring_before'],'monitoring.service.node_exporter.service')!='ok' or state(report['monitoring_before'],'monitoring.prometheus.targets')!='ok':raise RuntimeError('Fixture exporter and scraping must be healthy before fault injection')
    try:
        exporter('stop')
        down=snapshot()
        if state(down,'monitoring.service.node_exporter.service')!='failed':raise RuntimeError('Exporter outage was not detected')
        deadline=time.monotonic()+60
        while state(down,'monitoring.prometheus.targets')!='failed' and time.monotonic()<deadline:
            time.sleep(3);down=snapshot()
        if state(down,'monitoring.prometheus.targets')!='failed':raise RuntimeError('Scrape outage was not detected')
        report['exporter_outage']=down
        save_report('exporter_outage_observed')
    finally:
        exporter('start')
    deadline=time.monotonic()+75
    while True:
        recovered=snapshot()
        if state(recovered,'monitoring.service.node_exporter.service')=='ok' and state(recovered,'monitoring.prometheus.targets')=='ok':break
        if time.monotonic()>deadline:raise RuntimeError('Exporter/scrape recovery was not confirmed')
        time.sleep(3)
    report['exporter_recovered']=recovered
    save_report('exporter_recovery_observed')
if settings['canary']:
    nonce=uuid.uuid4().hex;case=source.parent/'canary-cases'/nonce;case.mkdir(mode=0o700,parents=True)
    original=Path('/etc/suricata/suricata-dmz.yaml').read_bytes()
    vpn=Path('/etc/suricata/suricata-ctf.yaml').read_text()
    groups=set(re.findall(r'^\s*cluster-id:\s*(\d+)\s*(?:#.*)?$',vpn,re.M))
    if groups!={'99'}:raise RuntimeError('Require the standard reviewed fixture VPN fanout profile')
    body=original.decode()
    if set(re.findall(r'^\s*cluster-id:\s*(\d+)\s*(?:#.*)?$',body,re.M)) not in ({'99'},{'100'}):raise RuntimeError('Unexpected DMZ fanout profile')
    body=re.sub(r'(^\s*cluster-id:\s*)99(\s*(?:#.*)?$)',r'\g<1>100\2',body,flags=re.M)
    config=case/'suricata.yaml';config.write_text(body);config.chmod(0o600)
    rule=case/'canary.rules';rule.write_text('alert udp 192.0.2.1 any -> 192.0.2.2 55555 (msg:"heiST monitoring canary:'+nonce+'"; content:"'+nonce+'"; sid:9900001; rev:1;)\n');rule.chmod(0o600)
    links=json.loads(subprocess.check_output(['ip','-j','-d','link','show','dev','dmz_monitoring']))
    if len(links)!=1 or links[0].get('linkinfo',{}).get('info_kind') not in ('dummy','ifb'):raise RuntimeError('Require the fixture IFB/dummy mirror device')
    was_active=subprocess.run(['systemctl','is-active','--quiet','suricata-dmz.service']).returncode==0
    (case/'original-state.json').write_text(json.dumps({'was_active':was_active,'configuration_sha256':hashlib.sha256(original).hexdigest()}))
    process=None;veth=None
    started=None
    def candidate_ready():
        try:
            with Path('/var/log/suricata/eve_dmz.json').open('rb') as events:
                events.seek(0,2);events.seek(max(0,events.tell()-512*1024));lines=events.read().splitlines()
        except FileNotFoundError:return False
        for line in reversed(lines):
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('event_type')=='stats':
                at=datetime.fromisoformat(event['timestamp'])
                return at.tzinfo is not None and at>=started
        return False
    def interrupted(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGHUP,interrupted)
    try:
        subprocess.run(['systemctl','stop','suricata-dmz.service'],check=True,capture_output=True,timeout=30)
        with (case/'sensor.log').open('wb') as log:
            # A service stop emits final stats. They must not mark the new
            # candidate ready before it has opened its packet sockets.
            started=datetime.now(timezone.utc)
            process=subprocess.Popen(['/usr/bin/suricata','-c',str(config),'-i','dmz_monitoring','--pidfile',str(case/'sensor.pid'),'-s',str(rule)],stdout=log,stderr=log)
            deadline=time.monotonic()+60
            while not candidate_ready():
                if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Candidate DMZ sensor did not become ready')
                time.sleep(2)
            payload=nonce.encode();port=49152+(int(nonce[:4],16)%10000)
            candidate='hm'+nonce[:6]+'a';peer='hm'+nonce[:6]+'b'
            subprocess.run(['ip','link','add',candidate,'type','veth','peer','name',peer],check=True,capture_output=True)
            veth=candidate  # Cleanup owns the interface only after successful creation.
            for name,mac in [(veth,'02:00:00:00:00:01'),(peer,'02:00:00:00:00:02')]:
                subprocess.run(['ip','link','set','dev',name,'address',mac,'up'],check=True,capture_output=True)
            subprocess.run(['tc','qdisc','add','dev',peer,'clsact'],check=True,capture_output=True)
            # Mirror before dropping the original; no IP address or route is added.
            subprocess.run(['tc','filter','add','dev',peer,'ingress','protocol','ip','matchall','action','mirred','egress','mirror','dev','dmz_monitoring','action','drop'],check=True,capture_output=True)
            def checksum(data):
                if len(data)%2:data+=b'\0'
                total=sum(struct.unpack('!'+str(len(data)//2)+'H',data));total=(total&65535)+(total>>16);total=(total&65535)+(total>>16)
                return (~total)&65535
            ip=struct.pack('!BBHHHBBH4s4s',0x45,0,28+len(payload),1,0,64,17,0,socket.inet_aton('192.0.2.1'),socket.inet_aton('192.0.2.2'))
            ip=ip[:10]+struct.pack('!H',checksum(ip))+ip[12:]
            frame=bytes.fromhex('0200000000020200000000010800')+ip+struct.pack('!HHHH',port,55555,8+len(payload),0)+payload
            with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)) as sender:
                sender.bind((veth,0))
                for _ in range(4):sender.send(frame)
            deadline=time.monotonic()+30;seen=False
            while time.monotonic()<deadline:
                with Path('/var/log/suricata/eve_dmz.json').open('rb') as events:
                    events.seek(0,2);events.seek(max(0,events.tell()-2*1024**2));lines=events.read().splitlines()
                for line in lines:
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('event_type')=='alert' and event.get('alert',{}).get('signature')=='heiST monitoring canary:'+nonce:seen=True
                if seen:break
                time.sleep(1)
            if not seen:raise RuntimeError('Synthetic mirror-device alert was not observed')
            report['canary']={'nonce':nonce,'frames_sent':4,'eve_alert_seen':True,'clickhouse_rows':None,
                'injection_point':'temporary veth ingress tc mirror into DMZ virtual device','guest_nic_mirroring_verified':False}
            save_report('canary_eve_observed')
            vector_command=subprocess.check_output(['systemctl','show','vector-dmz.service','--property=ExecStart','--value'],text=True)
            match=re.search(r'(?:--config|-c)\s+(/[A-Za-z0-9_./-]+)',vector_command)
            if not match:raise RuntimeError('Fixture Vector configuration path was not confirmed')
            credentials=tomllib.loads(Path(match[1]).read_text())['sinks']['clickhouse']['auth']
            deadline=time.monotonic()+90
            while True:
                result=json.loads(remote(settings['query'],{'nonce':nonce,'user':credentials['user'],'password':credentials['password']},timeout=15))
                if result['received']>0:break
                if time.monotonic()>deadline:raise RuntimeError('Synthetic alert did not reach ClickHouse')
                time.sleep(3)
            report['canary']={'nonce':nonce,'frames_sent':4,'eve_alert_seen':seen,'clickhouse_rows':result['received'],'tls_leaf_verified':result['tls_leaf_verified'],
                'injection_point':'temporary veth ingress tc mirror into DMZ virtual device','guest_nic_mirroring_verified':False,'original_configuration_changed':False}
            save_report('canary_delivered')
    finally:
        if veth is not None:subprocess.run(['ip','link','delete',veth],capture_output=True,timeout=10)
        if process is not None:
            process.terminate()
            try:process.wait(timeout=30)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if was_active:subprocess.run(['systemctl','start','suricata-dmz.service'],check=True,capture_output=True,timeout=30)
        if Path('/etc/suricata/suricata-dmz.yaml').read_bytes()!=original:raise RuntimeError('Original sensor configuration changed')
report['monitoring_after']=snapshot()
save_report('complete')
print(json.dumps(report))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--runtime-bundle', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--faults', action='store_true', help='Stop/recover only the fixture monitoring node exporter')
    parser.add_argument('--canary', action='store_true', help='Run a temporary DMZ sensor and four synthetic frames')
    args = parser.parse_args(argv)
    work = validate(args.work)
    output = args.output.resolve()
    if work not in output.parents or output.exists():
        raise ValueError('Use a new private evidence directory inside this disposable workspace')
    runtime = args.runtime_bundle.read_bytes()
    inspect_bundle(runtime, args.commit)
    verify(work)
    output.mkdir(mode=0o700, parents=True)
    command = shlex.join(['python3','-c',STAGE,args.commit,hashlib.sha256(runtime).hexdigest()])
    staged = subprocess.run(ssh_args(work)+[command],input=runtime,capture_output=True,check=True,timeout=60)
    receipt = json.loads(staged.stdout)
    (output/'stage.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (output/'stage.json').chmod(0o600)
    settings = {'source':receipt['source'],'faults':args.faults,'canary':args.canary,'query':QUERY,'evidence_id':uuid.uuid4().hex}
    command = shlex.join(['/root/heiST/.venv/bin/python','-c',RUN])
    with (output/'private-stderr.log').open('wb') as errors:
        import os
        os.fchmod(errors.fileno(),0o600)
        result = subprocess.run(ssh_args(work)+[command],input=json.dumps(settings).encode(),stdout=subprocess.PIPE,stderr=errors,timeout=360)
    if result.returncode:
        path=Path(receipt['source']).parent/'component-runs'/settings['evidence_id']/'result.json'
        program='import sys;from pathlib import Path;sys.stdout.buffer.write(Path('+repr(str(path))+').read_bytes()[:262145])'
        fetched=subprocess.run(ssh_args(work)+[shlex.join(['python3','-c',program])],capture_output=True,timeout=20)
        partial=json.loads(fetched.stdout) if fetched.returncode==0 and len(fetched.stdout)<=262144 else {}
        (output/'result.json').write_text(json.dumps({**partial,'passed':False,'commit':args.commit,'returncode':result.returncode,'production_changed':False})+'\n')
        (output/'result.json').chmod(0o600)
        raise RuntimeError('Fixture monitoring rehearsal failed; inspect its private evidence directory')
    value = json.loads(result.stdout)
    (output/'result.json').write_text(json.dumps({'passed':True,**value},indent=2)+'\n')
    (output/'result.json').chmod(0o600)
    print(json.dumps({'passed':True,'commit':args.commit,'output':str(output),'canary':value.get('canary'),
                      'application_upgrade_rollback_verified':False,'production_changed':False}))


if __name__ == '__main__':
    main()
