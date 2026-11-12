"""Explicit operator delivery canaries. Never imported by the API or collector.

Programs run on the configured Proxmox host using its existing pinned SSH and
read-only monitoring credentials. Only synthetic packets/accounts are created.
"""

def packet_probe(parameters):
    """Exercise one temporary ingress mirror against the real DMZ pipeline."""
    import hashlib, json, re, socket, struct, subprocess, time
    from pathlib import Path
    from dotenv import dotenv_values
    from heist.monitoring.pipeline import HTTPS
    nonce = parameters['run_id']
    if not re.fullmatch('[a-f0-9]{32}', nonce):raise ValueError('Invalid run identity')
    settings = dict(dotenv_values(parameters['environment']))
    settings.update(dotenv_values(settings['HEIST_MONITORING_ENVIRONMENT_FILE']))
    config = Path('/etc/suricata/suricata-dmz.yaml').read_text()
    names = set(re.findall(r'^\s*-?\s*interface:\s*([A-Za-z0-9_.-]+)\s*$', config, re.M))
    if names != {'dmz_monitoring'}:raise ValueError('Unexpected sensor interface')
    left, right = 'hce'+nonce[:8], 'hci'+nonce[:8]
    for name in (left, right):
        if Path('/sys/class/net', name).exists():raise ValueError('Canary interface already exists')
    query_name = nonce+'.heist-canary.invalid'
    def frame(label):
        question = b''.join(bytes([len(part)])+part.encode() for part in (label+'.'+query_name).split('.'))+b'\0'+struct.pack('!HH',1,1)
        dns = struct.pack('!HHHHHH',12345,0x0100,1,0,0,0)+question
        udp = struct.pack('!HHHH',54321,53,len(dns)+8,0)+dns
        header = struct.pack('!BBHHHBBH4s4s',0x45,0,len(udp)+20,1,0,64,17,0,socket.inet_aton('192.0.2.1'),socket.inet_aton('192.0.2.2'))
        words=struct.unpack('!10H',header);total=sum(words)
        while total>>16:total=(total&65535)+(total>>16)
        header=header[:10]+struct.pack('!H',(~total)&65535)+header[12:]
        return bytes.fromhex('0200000000020200000000010800')+header+udp
    def command(*args):subprocess.run(args,check=True,capture_output=True,timeout=15)
    client=HTTPS(settings,'CLICKHOUSE',8443)
    def sink(label):
        sql="SELECT count() AS received FROM suricata.dmz_eve_logs WHERE timestamp > now()-INTERVAL 10 MINUTE AND position(dns_json,'"+label+'.'+query_name+"')>0 FORMAT JSONEachRow"
        return int(client.get('/',params={'query':sql,'readonly':2,'max_execution_time':3})['received'])
    def send(label):
        with socket.socket(socket.AF_PACKET,socket.SOCK_RAW) as output:
            output.bind((left,0));output.send(frame(label))
    def wait_sink(label):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if sink(label)>0:return True
            time.sleep(2)
        return False
    def eve(label):
        with Path('/var/log/suricata/eve_dmz.json').open('rb') as stream:
            stream.seek(0,2);stream.seek(max(0,stream.tell()-4*1024**2))
            return (label+'.'+query_name).encode() in stream.read(4*1024**2)
    steps=dict.fromkeys(('source','sensor','sink','interruption_detected','recovery','cleanup'),False)
    try:
        command('ip','link','add',left,'type','veth','peer','name',right)
        command('ip','link','set',left,'up');command('ip','link','set',right,'up')
        command('tc','qdisc','add','dev',right,'clsact')
        def mirror():command('tc','filter','add','dev',right,'ingress','protocol','all','pref','1','matchall','action','mirred','egress','mirror','dev','dmz_monitoring')
        mirror();send('before');steps['source']=True
        steps['sink']=wait_sink('before');steps['sensor']=eve('before')
        if not steps['sink'] or not steps['sensor']:raise RuntimeError('Synthetic DNS canary was not delivered')
        # Interrupt only our temporary mirror, never an active guest or sensor.
        command('tc','filter','del','dev',right,'ingress','pref','1')
        send('blocked');time.sleep(3)
        steps['interruption_detected']=not eve('blocked') and sink('blocked')==0
        mirror();send('recovered');steps['recovery']=wait_sink('recovered') and eve('recovered')
        if not all(v for k,v in steps.items() if k!='cleanup'):raise RuntimeError('Canary interruption/recovery failed')
    finally:
        client.close()
        if Path('/sys/class/net',left).exists():command('ip','link','del',left)
        steps['cleanup']=not any(Path('/sys/class/net',n).exists() for n in (left,right))
    return {'steps':steps,'query_name':query_name,'scope':'temporary DMZ mirror only; VPN and guest NIC coverage excluded'}


def web_probe(parameters):
    """Verify real TLS, session revocation, authorization and the SQL-backed API."""
    import json, re, secrets
    import requests
    from heist.environment import load_backend_env
    from heist.infrastructure.database import get_db_connection
    from heist.infrastructure.tls import TLSIdentityAdapter
    from heist.security.passwords import hash_password
    from heist.rollout.config import Deployment
    if not re.fullmatch('[a-f0-9]{32}',parameters['run_id']):raise ValueError('Invalid run identity')
    load_backend_env()
    config=Deployment.load(parameters['deployment'])
    origin='https://'+config.vm('web').host
    name='e2e_'+parameters['run_id'][:16];password=secrets.token_urlsafe(36)
    identifier=None;session=requests.Session();session.trust_env=False
    session.mount(origin+'/',TLSIdentityAdapter(config.web_hostname));session.headers.update(Origin='https://'+config.web_hostname,Host=config.web_hostname)
    steps=dict.fromkeys(('login','backend_query','access_denied','session_revoked','recovery','cleanup'),False)
    def request(method,path,**kwargs):
        response=session.request(method,origin+'/api/'+path,timeout=(5,30),allow_redirects=False,**kwargs)
        return response.status_code,response.json()
    def login():
        status,value=request('GET','session');assert status==200
        session.headers['X-CSRF-Token']=value['data']['csrf_token']
        status,value=request('POST','login',json={'username':name,'password':password});assert status==200 and value.get('success')
        session.headers['X-CSRF-Token']=value['csrf_token']
    db=get_db_connection()
    try:
        with db.cursor() as c:
            c.execute('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)',(name,name+'@example.invalid',hash_password(password),'','127.0.0.1'));identifier=c.fetchone()[0]
        login();steps['login']=True
        status,value=request('GET','profile?type=basic');steps['backend_query']=status==200 and value.get('success') is True
        status,_=request('GET','admin/operations');steps['access_denied']=status==403
        old=session.cookies.get('__Host-heist_session')
        status,value=request('POST','logout',json={});assert status==200
        session.cookies.set('__Host-heist_session',old,domain=config.vm('web').host,path='/',secure=True)
        status,_=request('GET','profile');steps['session_revoked']=status==401
        session.cookies.clear();login();status,value=request('GET','profile?type=basic')
        steps['recovery']=status==200 and value.get('success') is True
    finally:
        if identifier is not None:
            # Delete only the exact synthetic account, with its own password.
            session.cookies.clear();login()
            status,value=request('DELETE','profile',json={'password':password});assert status==200 and value.get('success')
            with db.cursor() as c:
                c.execute('SELECT 1 FROM users WHERE id=%s AND username=%s',(identifier,name));steps['cleanup']=c.fetchone() is None
        db.close();session.close()
    if not all(steps.values()):raise RuntimeError('Web delivery/recovery probe failed')
    return {'steps':steps,'scope':'synthetic account; login/session recovery, not a web-server outage'}


def monitoring_probe(parameters):
    """Read the host canary through Grafana, then reject bad reader credentials."""
    import re,secrets
    from dotenv import dotenv_values
    from heist.monitoring.pipeline import HTTPS
    name=parameters['query_name']
    if not re.fullmatch(r'[a-f0-9]{32}\.heist-canary\.invalid',name):raise ValueError('Invalid canary name')
    settings=dict(dotenv_values(parameters['environment']));settings.update(dotenv_values(settings['HEIST_MONITORING_ENVIRONMENT_FILE']))
    client=HTTPS(settings,'GRAFANA',3000)
    try:
        sources=client.get('/api/datasources')
        ds=[v for v in sources if v['name']=='ClickHouse' and v['type']=='grafana-clickhouse-datasource']
        if len(ds)!=1:raise RuntimeError('Expected ClickHouse datasource missing')
        sql="SELECT count() AS received FROM suricata.dmz_eve_logs WHERE timestamp>now()-INTERVAL 24 HOUR AND position(dns_json,'"+name+"')>0"
        body={'queries':[{'refId':'A','datasource':{'type':ds[0]['type'],'uid':ds[0]['uid']},'format':1,'rawQuery':True,'rawSql':sql}],'from':'now-24h','to':'now'}
        def query():
            response=client.session.post(client.origin+'/api/ds/query',json=body,verify=client.certificate,timeout=(5,15),allow_redirects=False)
            try:
                if response.status_code!=200:raise RuntimeError('Grafana datasource query failed: HTTP '+str(response.status_code))
                value=response.json()['results']['A']
                if value.get('error'):raise RuntimeError('Grafana datasource returned a query error')
                values=[v for frame in value['frames'] for column in frame['data']['values'] for v in column if type(v) in (int,float)]
                return any(v>=2 for v in values)
            finally:response.close()
        steps={'canary_query':query(),'tls_verified':True,'authentication_denied':False,'recovery':False}
        auth=client.session.auth;client.session.auth=(settings['GRAFANA_USER'],secrets.token_urlsafe(32))
        response=client.session.get(client.origin+'/api/datasources',verify=client.certificate,timeout=(5,10),allow_redirects=False)
        try:steps['authentication_denied']=response.status_code==401
        finally:response.close();client.session.auth=auth
        steps['recovery']=query()
        if not all(steps.values()):raise RuntimeError('Grafana authentication/canary recovery failed')
        return {'steps':steps,'scope':'Grafana ClickHouse panel path and reader authentication; not all dashboard queries'}
    finally:client.close()


def archive_probe(parameters):
    """Corrupt only a dedicated synthetic destination, then verify real recovery."""
    import gzip,hashlib,json,os,re,shlex,subprocess
    from pathlib import Path
    from dotenv import dotenv_values
    nonce=parameters['run_id']
    if not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError('Invalid run identity')
    source=Path('/var/lib/heist/monitoring-canaries')/nonce/'archive';source.mkdir(mode=0o700,parents=True)
    raw=('heiST synthetic archive canary '+nonce+'\n').encode()
    body=gzip.compress(raw,mtime=0);path=source/'canary.log.gz';path.write_bytes(body);path.chmod(0o600)
    settings=dict(dotenv_values(parameters['environment']));host=settings['HEIST_ARCHIVE_STATUS_HOST']
    program=r'''
from pathlib import Path
import gzip,hashlib,json,os,pwd,subprocess,sys
p=json.load(sys.stdin)
assert os.geteuid()==0 and subprocess.run(['mountpoint','-q','/var/lib/heist-archive']).returncode==0
nonce=p['run_id'];source_id='e2e-'+nonce[:12];unit='heist-log-archive@'+source_id+'.service'
original=json.loads(Path('/etc/heist/archive/proxmox-logs.json').read_text())
config={**original,'source':source_id,'remote_directory':p['source'],'destination':'/var/lib/heist-archive/files/'+source_id,'recursive':False,'remove_remote':False}
config.pop('public_status',None)
configuration=Path('/etc/heist/archive')/(source_id+'.json')
key=Path('/etc/heist/archive/keys')/(source_id+'.key')
assert not configuration.exists() and not key.exists()
owner=pwd.getpwnam('heist-archive');destination=Path(config['destination']);assert not destination.exists()
destination.mkdir(mode=0o700);os.chown(destination,owner.pw_uid,owner.pw_gid)
target=destination/'canary.log.gz';target.write_bytes(b'synthetic corrupted copy');target.chmod(0o600);os.chown(target,owner.pw_uid,owner.pw_gid)
configuration.write_text(json.dumps(config));os.chown(configuration,0,owner.pw_gid);configuration.chmod(0o640);key.symlink_to('/etc/heist/archive/keys/proxmox-logs.key')
try:
    failed=subprocess.run(['systemctl','start',unit],capture_output=True,timeout=120)
    invocation=subprocess.check_output(['systemctl','show',unit,'--property=InvocationID','--value'],text=True).strip()
    journal=subprocess.check_output(['journalctl','_SYSTEMD_INVOCATION_ID='+invocation,'--no-pager','-o','cat'],text=True)
    rejected=failed.returncode!=0 and target.read_bytes()==b'synthetic corrupted copy' and 'An existing local archive differs; remote copy retained' in journal
    assert rejected,'Collector accepted a corrupted existing copy'
    target.unlink();subprocess.run(['systemctl','reset-failed',unit],check=True,capture_output=True)
    subprocess.run(['systemctl','start',unit],check=True,capture_output=True,timeout=120)
    body=target.read_bytes()
    result={'corruption_rejected':rejected,'checksum':hashlib.sha256(body).hexdigest()==p['sha256'],
            'decompression':hashlib.sha256(gzip.decompress(body)).hexdigest()==p['raw_sha256'],'recovery':True}
    assert all(result.values())
    print(json.dumps(result))
finally:
    configuration.unlink(missing_ok=True);key.unlink(missing_ok=True)
    subprocess.run(['systemctl','reset-failed',unit],capture_output=True,timeout=15)
'''
    payload={'source':str(source),'run_id':nonce,'sha256':hashlib.sha256(body).hexdigest(),'raw_sha256':hashlib.sha256(raw).hexdigest()}
    cmd=['ssh','-i','/root/.ssh/id_rsa','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','ubuntu@'+host,shlex.join(['sudo','-n','python3','-c',program])]
    result=subprocess.run(cmd,input=json.dumps(payload).encode(),capture_output=True,timeout=280)
    if result.returncode:
        diagnostic=source/'archive-error.log';diagnostic.write_bytes(result.stdout+result.stderr);diagnostic.chmod(0o600)
        raise RuntimeError('Dedicated archive canary failed; private diagnostics: '+str(diagnostic))
    steps=json.loads(result.stdout);steps.update(source_closed=True,source_retained=path.read_bytes()==body)
    return {'steps':steps,'scope':'dedicated synthetic archive source/destination; normal archive jobs unchanged'}
