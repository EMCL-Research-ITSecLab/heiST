"""Foreground rollout supervisor suitable for nohup; never retries an update."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback
import uuid

from heist.files import maintenance_lock, private_directory, sha256, write_file, write_json
from .config import Deployment
from .manifest import Plan, git, revision


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(config_path, plan_path, repository):
    config=Deployment.load(config_path)
    plan=Plan.from_dict(json.loads(plan_path.read_text()))
    if sha256(config_path)!=plan.config_sha256:
        raise ValueError('Deployment configuration changed after planning')
    if revision(repository,'HEAD')!=plan.target:
        raise ValueError('Run the launcher from the exact target release checkout')
    if git(repository,'status','--porcelain','--untracked-files=no').strip():
        raise ValueError('The release runner has modified tracked source')
    if repository.resolve().is_relative_to(Path(config.installation).resolve()):
        raise ValueError('Use a separate release runner, outside the installed checkout')
    return config,plan


def supervise(command, run_directory, *, cwd, details):
    """Save complete timestamped output and the real exit code, including failures."""
    state={**details,'started_at':now(),'state':'STARTING','exit_code':None,
           'pid':os.getpid(),'log':str(run_directory/'rollout.log')}
    write_json(run_directory/'status.json',state)
    child=None
    previous={}
    try:
        with (run_directory/'rollout.log').open('x',encoding='utf-8') as log:
            os.chmod(run_directory/'rollout.log',0o600)
            def record(line):
                line=f'{now()} {line.rstrip()}\n'
                log.write(line);log.flush()
                print(line,end='',flush=True)
            record('Starting reviewed rollout; no automatic retry is enabled.')
            child=subprocess.Popen(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONUNBUFFERED':'1'},start_new_session=True)
            def forward(signum,_frame):
                state.update(stop_requested_at=now(),signal=signum)
                write_json(run_directory/'status.json',state)
                if child.poll() is None:child.send_signal(signum)
            for signum in (signal.SIGTERM,signal.SIGINT):
                previous[signum]=signal.signal(signum,forward)
            state.update(state='RUNNING',child_pid=child.pid)
            write_json(run_directory/'status.json',state)
            assert child.stdout is not None
            for line in child.stdout:record(line)
            code=child.wait()
            state.update(state='SUCCEEDED' if code==0 else 'FAILED',exit_code=code,finished_at=now())
            record(f'Rollout exited with code {code}. Inspect status.json and transaction failure reports before any retry.')
    except BaseException:
        state.update(state='FAILED',exit_code=1,finished_at=now())
        with (run_directory/'launcher-error.log').open('a',encoding='utf-8') as log:
            traceback.print_exc(file=log)
        os.chmod(run_directory/'launcher-error.log',0o600)
        if child is not None and child.poll() is None:
            child.terminate();child.wait()
        raise
    finally:
        if child is not None and child.stdout is not None:child.stdout.close()
        for signum,handler in previous.items():signal.signal(signum,handler)
        write_json(run_directory/'status.json',state)
    return 0 if code==0 else (code if code>0 else 128-code)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--logs',type=Path,required=True)
    parser.add_argument('--action',choices=('apply','resume'),default='apply')
    parser.add_argument('--check-only',action='store_true',help='Validate runner/config/plan only; do not enter maintenance')
    args=parser.parse_args(argv)
    os.umask(0o077)
    root=private_directory(args.logs.resolve())
    repository=Path(__file__).resolve().parents[2]
    try:
        with maintenance_lock(root):
            run=private_directory(root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]))
            write_json(root/'latest.json',{'run':str(run),'status':str(run/'status.json'),'log':str(run/'rollout.log')})
            print(f'Run directory: {run}',flush=True)
            try:
                config,plan=validate(args.config.resolve(),args.plan.resolve(),repository)
            except Exception as error:
                write_file(run/'launcher-error.log',traceback.format_exc())
                write_json(run/'status.json',{'state':'PREFLIGHT_FAILED','exit_code':1,'finished_at':now(),'error':str(error),
                    'error_log':str(run/'launcher-error.log')})
                raise
            details={'target':plan.target,'baseline':plan.source,'action':args.action,
                     'config_sha256':sha256(args.config),'plan_sha256':sha256(args.plan),
                     'challenge_template_backups':config.backup_challenge_templates,
                     'state_directory':config.state_directory}
            write_json(run/'request.json',details)
            if args.check_only:
                write_json(run/'status.json',{**details,'state':'VALIDATED','exit_code':0,'finished_at':now(),
                    'note':'Runner/config/plan validated; platform admission, health and backup storage still require rollout preflight.'})
                print('Runner/config/plan validated. No deployment or maintenance started.',flush=True)
                return 0
            command=[sys.executable,'-u','-m','heist','upgrade',args.action,'--config',str(args.config.resolve())]
            if args.action=='apply':command+=['--plan',str(args.plan.resolve())]
            result=supervise(command,run,cwd=repository,details=details)
            from .cli import status
            try:write_json(run/'platform-status.json',status(Path(config.state_directory)))
            except Exception as error:write_json(run/'status-read-error.json',{'error':type(error).__name__})
            return result
    except (Exception,KeyboardInterrupt) as error:
        print(f'Launcher stopped: {error}. Inspect {root}/latest.json and the private run logs.',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':raise SystemExit(main())
