"""Run the strict suite with a disposable, network-isolated PostgreSQL fixture."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'postgres@sha256:f9a7b9ebf6f56201f949db745e47bc423c0f0f8294bafe991cc10bf74b029657'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--native-worker', action='store_true', help='Also exercise a temporary local systemd worker with inert VM commands')
    parser.add_argument('--wheelhouse', type=Path, help='Reviewed offline runtime wheels for the native worker test')
    args = parser.parse_args()
    report = args.report
    if args.native_worker and (not args.wheelhouse or not args.wheelhouse.is_dir()):
        parser.error('--native-worker requires --wheelhouse')
    if os.geteuid() != 0 or not report.is_absolute() or report.exists():
        parser.error('Run with host test privileges and a new absolute report path')
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = 'heist-check-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='heist-pg-') as temporary:
        socket = Path(temporary)/'socket';socket.mkdir(mode=0o777);socket.chmod(0o777)
        try:
            subprocess.run(['docker','run','--pull','never','--rm','--detach','--name',name,'--network','none',
                '--memory','1536m','--cpus','2','--tmpfs','/var/lib/postgresql/data:rw,nosuid,size=1g',
                '-v',str(socket)+':/var/run/postgresql','-e','POSTGRES_HOST_AUTH_METHOD=trust',IMAGE,
                '-c','listen_addresses=','-c','unix_socket_permissions=0777'],check=True,capture_output=True)
            for _ in range(60):
                if subprocess.run(['docker','exec',name,'pg_isready','-U','postgres','-h','/var/run/postgresql'],capture_output=True).returncode == 0:break
                time.sleep(1)
            else:raise RuntimeError('Disposable PostgreSQL did not start')
            # Only the fixture's administrator uses trust; application roles
            # must exercise real password verification and denial through SCRAM.
            subprocess.run(['docker','exec','-u','postgres',name,'sh','-c',
                "printf 'local all postgres trust\\nlocal all all scram-sha-256\\n' > /var/lib/postgresql/data/pg_hba.conf"],check=True,capture_output=True)
            subprocess.run(['docker','exec','-u','postgres',name,'psql','-h','/var/run/postgresql','-d','postgres','-c','SELECT pg_reload_conf();'],check=True,capture_output=True)
            time.sleep(1)
            env = dict(os.environ,GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=str(ROOT),
                       TEST_DATABASE_URL='postgresql://postgres@/postgres?host='+str(socket),HEIST_PRIVILEGED_TESTS='1')
            with report.with_suffix('.log').open('xb') as log:
                os.fchmod(log.fileno(),0o600)
                result = subprocess.run([os.sys.executable,'tools/check.py','--fail-on-skip','--report',str(report)],
                    cwd=ROOT,env=env,stdout=log,stderr=log,timeout=600)
            value = json.loads(report.read_text())
            print(json.dumps({key:value[key] for key in ('commit','dirty','counts','returncode')}))
            if result.returncode == 0 and args.native_worker:
                env.update(HEIST_TEST_WHEELHOUSE=str(args.wheelhouse.resolve()),HEIST_NATIVE_EVIDENCE_FILE=str(report.with_suffix('.native.json')))
                with report.with_suffix('.native.log').open('xb') as log:
                    os.fchmod(log.fileno(),0o600)
                    result=subprocess.run([os.sys.executable,'-m','unittest','tests.native.administrator_worker','-q'],cwd=ROOT,env=env,stdout=log,stderr=log,timeout=180)
                print(json.dumps({'native_worker_returncode':result.returncode,'evidence':str(report.with_suffix('.native.json'))}))
            return result.returncode
        finally:
            subprocess.run(['docker','rm','--force',name],capture_output=True)


if __name__ == '__main__':
    raise SystemExit(main())
