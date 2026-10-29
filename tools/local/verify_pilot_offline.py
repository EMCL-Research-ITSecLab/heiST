#!/usr/bin/env python3
"""Bind sampled guest egress denials to a running QEMU restrict=on pilot boot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from nested_pilot import PORTS, qmp, ssh_args


def validate_command(arguments, work):
    expected = 'user,id=mgmt,restrict=on'
    for protocol, local, remote in [('tcp', PORTS['ssh'], 22), ('tcp', PORTS['web'], 443),
                                    ('tcp', PORTS['proxmox'], 8006), ('udp', PORTS['vpn'], 1194)]:
        expected += f',hostfwd={protocol}:127.0.0.1:{local}-:{remote}'
    networks = [arguments[index + 1] for index, arg in enumerate(arguments[:-1]) if arg == '-netdev']
    if networks != [expected] or any(arg in arguments for arg in ('-nic', '-net', '-readconfig')):
        raise RuntimeError('The actual QEMU process is not the restricted single-network pilot')
    if not any(arg.startswith('file=' + str(work / 'disk.qcow2') + ',') for arg in arguments):
        raise RuntimeError('QEMU is not using this pilot workspace disk')
    return hashlib.sha256('\0'.join(arguments).encode()).hexdigest()


def verify(work):
    if (work / 'network-mode').read_text().strip() != 'offline-pilot':
        raise RuntimeError('Shut down and restart the pilot without --online first')
    if qmp(work, 'query-status')['status'] != 'running':
        raise RuntimeError('Pilot must be running')
    pid = int((work / 'qemu.pid').read_text())
    arguments = (Path('/proc') / str(pid) / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    command_hash = validate_command(arguments, work)
    script = '''
import json,os,socket,uuid
from pathlib import Path
if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='heist-pilot' or not Path('/root/pilot-cloud-init-ready').is_file():
    raise RuntimeError('Run only inside the disposable pilot')
checks=[]
for name,host,port in [('external_ipv4','1.1.1.1',443),('host_ssh','10.0.2.2',22),('external_ipv6','2606:4700:4700::1111',443)]:
    try:
        with socket.create_connection((host,port),timeout=3):pass
        denied=False
    except OSError:denied=True
    checks.append({'name':name,'denied':denied})
result={'passed':all(c['denied'] for c in checks),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'host_verified_qemu_restrict':True,'host_command_sha256':COMMAND_HASH,'sampled_tcp_denials':checks,
        'production_accepted':False,'exhaustive_dns_and_protocol_isolation':'NOT_CERTIFIED'}
p=Path('/root/pilot-offline-verified.json')
if p.exists():
    old=json.loads(p.read_text())
    if old.get('boot_id')!=result['boot_id']:
        backup=p.with_name('pilot-offline-verified.before-'+str(uuid.UUID(old['boot_id']))+'.json')
        if not backup.exists():backup.write_bytes(p.read_bytes());backup.chmod(0o600)
temporary=p.with_suffix('.tmp')
with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as stream:
    json.dump(result,stream,indent=2);stream.write('\\n')
os.replace(temporary,p)
print(json.dumps(result))
raise SystemExit(0 if result['passed'] else 1)
'''.replace('COMMAND_HASH', repr(command_hash))
    completed = subprocess.run(ssh_args(work) + ['/usr/bin/python3 -'], input=script, text=True,
                               capture_output=True, check=True)
    result = json.loads(completed.stdout)
    target = work / 'offline-probes.json'
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    if os.geteuid() == 0:
        owner = work.stat()
        os.chown(target, owner.st_uid, owner.st_gid)
    print('PASS: actual QEMU restrict=on profile and sampled TCP denials bound to current boot')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    verify(args.work.resolve())
