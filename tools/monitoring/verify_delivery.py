"""Run scoped live delivery/recovery probes using an existing pinned SSH profile.

No production service is stopped. The database probe uses a private copy of an
existing verified backup and a network-isolated local container. Evidence expires
rather than being renewed by the health collector. Training capture is untouched.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from heist.monitoring.health import DELIVERY_CONTRACTS
from tools.monitoring import probes
from tools.monitoring.restore_probe import verify as restore


def collector_source(exec_start):
    """Resolve the two supported collector commands; reject unknown launchers."""
    import re
    import shlex
    match = re.search(r'argv\[\]=(.*?) ;', exec_start)
    if match is None:
        raise ValueError('Collector command could not be verified')
    arguments = shlex.split(match[1])
    if arguments[1:3] == ['-m', 'heist.monitoring.health']:
        return '/root/heiST/heist/monitoring/health.py'
    if len(arguments) > 1 and re.fullmatch(r'/usr/local/lib/heist/platform-health-[a-f0-9]{7,40}\.py', arguments[1]):
        return arguments[1]
    raise ValueError('Unsupported collector command; inspect the deployed service')


class Target:
    def __init__(self, args):
        self.args = args
        home = Path(pwd.getpwnam(args.local_user).pw_dir) if args.local_user else Path.home()
        known_hosts = args.known_hosts or home/'.ssh/known_hosts'
        self.command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'ForwardAgent=no', '-o', 'UserKnownHostsFile='+str(known_hosts), '-o', 'ConnectTimeout=10', args.host]
        if args.local_user:
            if os.geteuid() != 0 or pwd.getpwnam(args.local_user).pw_uid == 0:
                raise ValueError('A local transport account requires root and a nonroot account')
            self.command = ['runuser', '-u', args.local_user, '--', *self.command]
        self.prefix = ("from pathlib import Path\nimport hashlib,json,os,socket,sys\n"
                       "assert os.geteuid()==0 and socket.gethostname().split('.')[0]=="+repr(args.node)+"\n"
                       "sys.path.insert(0,'/root/heiST')\n"
                       "assert json.loads(Path('/var/lib/heist/installed.json').read_text())['commit']=="+repr(args.commit)+"\n"
                       "assert not Path('/var/lib/heist/active.json').exists()\n")

    def run(self, program, payload, output):
        result = subprocess.run([*self.command, shlex.join([self.args.python, '-c', self.prefix+program])],
                                input=json.dumps(payload).encode(), capture_output=True, timeout=360)
        if result.returncode:
            path = output/'private-error.log'
            path.write_bytes(result.stdout+result.stderr)
            path.chmod(0o600)
            raise RuntimeError('Probe failed; inspect private '+str(path))
        return json.loads(result.stdout)

    def binding(self, output):
        program = inspect.getsource(collector_source)+"""
import subprocess
p=json.load(sys.stdin)
source=p['collector'] or collector_source(subprocess.check_output(['systemctl','show','heist-monitoring.service','--property=ExecStart','--value'],text=True))
path=Path(source);assert path.is_absolute() and not path.is_symlink() and path.stat().st_uid==0
print(json.dumps({'source_commit':json.loads(Path('/var/lib/heist/installed.json').read_text())['commit'],
'host_boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
'collector_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
"""
        return self.run(program, {'collector': self.args.collector}, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Existing pinned SSH config profile')
    parser.add_argument('--node', required=True, help='Expected remote hostname')
    parser.add_argument('--local-user', help='Use this existing local account for SSH only')
    parser.add_argument('--known-hosts', type=Path, help='Pinned host file; defaults to the transport account known_hosts')
    parser.add_argument('--commit', required=True, help='Expected installed application commit')
    parser.add_argument('--collector', help='Optional staged collector source; defaults to the active systemd command')
    parser.add_argument('--python', default='/root/heiST/.venv/bin/python')
    parser.add_argument('--environment', default='/root/heiST/backend/.env')
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private evidence directory')
    parser.add_argument('--publish', action='store_true', help='Publish only a complete five-path result to the collector')
    args = parser.parse_args()
    if (re.fullmatch('[a-f0-9]{40}', args.commit) is None or not args.output.is_absolute()
            or args.output.exists() or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,120}',args.host) is None):
        parser.error('Use a full installed commit and new absolute evidence directory')
    args.output.mkdir(mode=0o700, parents=True)
    target = Target(args)
    binding = target.binding(args.output)
    probe_commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']).strip():
        parser.error('Commit the complete probe source before execution')
    reports = {}
    for role in ('host', 'web', 'database', 'monitoring', 'archive'):
        nonce = uuid.uuid4().hex
        parameters = {'run_id': nonce, 'environment': args.environment, 'deployment': args.deployment}
        if role == 'database':
            directory = args.output/'database-restore'
            directory.mkdir(mode=0o700)
            program = """import base64
p=Path('/var/backups/heist/database/latest.backup').resolve()
assert p.is_relative_to('/var/backups/heist/database') and p.is_file()
metadata=json.loads(p.with_name('metadata.json').read_text())
assert 5<=p.stat().st_size==metadata['bytes']<=64*1024**2
body=p.read_bytes();assert body[:5]==b'PGDMP' and hashlib.sha256(body).hexdigest()==metadata['sha256']
print(json.dumps({'metadata':metadata,'body':base64.b64encode(body).decode()}))
"""
            backup = target.run(program, {}, args.output)
            path = directory/'database.backup'
            path.write_bytes(base64.b64decode(backup['body']));path.chmod(0o600)
            path = directory/'source-metadata.json'
            path.write_text(json.dumps(backup['metadata']));path.chmod(0o600)
            result = restore(directory)
        else:
            function = {'host': probes.packet_probe, 'web': probes.web_probe,
                        'monitoring': probes.monitoring_probe, 'archive': probes.archive_probe}[role]
            if role == 'monitoring':
                parameters['query_name'] = reports['host']['query_name']
            result = target.run(inspect.getsource(function)+'\nprint(json.dumps('+function.__name__+'(json.load(sys.stdin))))', parameters, args.output)
        if set(result['steps']) != set(DELIVERY_CONTRACTS[role][1]) or not all(v is True for v in result['steps'].values()):
            raise RuntimeError(role+' delivery verification incomplete')
        result.update(schema=1, role=role, run_id=nonce, probe_commit=probe_commit,
                      checked_at=datetime.now(timezone.utc).isoformat(), **binding)
        reports[role] = result
        path = args.output/(role+'.json')
        path.write_text(json.dumps(result, indent=2)+'\n')
        path.chmod(0o600)
        print(role+': delivery and scoped recovery passed', flush=True)
    if binding != target.binding(args.output):
        raise RuntimeError('Installation/boot/collector changed during probes; evidence not published')
    if args.publish:
        program = """p=json.load(sys.stdin)
from heist.files import private_directory,write_json
root=private_directory('/var/lib/heist/monitoring/end-to-end')
assert set(p)=={'host','web','database','monitoring','archive'}
for role,proof in p.items():
 assert proof['role']==role and proof['source_commit']==COMMIT
 write_json(root/(role+'.json'),proof)
print(json.dumps({'published':5}))
""".replace('COMMIT', repr(args.commit))
        target.run(program, reports, args.output)
    print(json.dumps({'five_paths_passed': True, 'published': args.publish,
                      'exhaustive_packet_and_guest_coverage': False, 'training_capture_changed': False}))


if __name__ == '__main__':
    main()
