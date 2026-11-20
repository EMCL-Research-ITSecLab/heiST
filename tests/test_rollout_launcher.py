"""The nohup supervisor retains failures without retrying or bypassing admission."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict, replace
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from heist.files import maintenance_lock, private_directory, sha256
from heist.rollout.config import Deployment
from heist.rollout.launcher import main, supervise, validate
from heist.rollout.manifest import Plan


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'deployment.json'
        example=Path(__file__).resolve().parents[1]/'config/deployment.example.json'
        self.config.write_bytes(example.read_bytes())
        self.plan=Plan(3,'/fixture','a'*40,'b'*40,'0.4.0-rc.5','manifest','sha',sha256(self.config),(),(),())
        self.plan_path=self.root/'plan.json'
        self.plan_path.write_text(json.dumps(self.plan.to_dict()))

    def test_real_failed_child_output_and_exit_status_are_retained_once(self):
        run=private_directory(self.root/'logs')
        with redirect_stdout(io.StringIO()):
            code=supervise([sys.executable,'-c',"import sys; print('checkpoint step',flush=True); print('failure detail',file=sys.stderr); sys.exit(7)"],run,cwd=self.root,details={'target':'b'*40})
        self.assertEqual(code,7)
        state=json.loads((run/'status.json').read_text())
        self.assertEqual((state['state'],state['exit_code']),('FAILED',7))
        log=(run/'rollout.log').read_text()
        self.assertEqual(log.count('checkpoint step'),1)
        self.assertIn('failure detail',log)
        for name in ('status.json','rollout.log'):self.assertEqual((run/name).stat().st_mode&0o777,0o600)

    def test_success_and_child_start_failure_have_durable_status(self):
        run=private_directory(self.root/'success')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(supervise([sys.executable,'-c',"print('complete')"],run,cwd=self.root,details={}),0)
        self.assertEqual(json.loads((run/'status.json').read_text())['state'],'SUCCEEDED')
        run=private_directory(self.root/'failed-start')
        with redirect_stdout(io.StringIO()),self.assertRaises(FileNotFoundError):
            supervise(['/nonexistent/heist-test-runner'],run,cwd=self.root,details={})
        self.assertEqual(json.loads((run/'status.json').read_text())['exit_code'],1)
        self.assertIn('FileNotFoundError',(run/'launcher-error.log').read_text())

    def test_changed_config_dirty_runner_and_in_place_runner_are_refused(self):
        with patch('heist.rollout.launcher.revision',return_value='b'*40),patch('heist.rollout.launcher.git',return_value=b''):
            validate(self.config,self.plan_path,self.root/'runner')
            with self.assertRaisesRegex(ValueError,'separate release runner'):
                validate(self.config,self.plan_path,Path('/root/heiST/runner'))
            with patch('heist.rollout.launcher.git',return_value=b'M source.py'):
                with self.assertRaisesRegex(ValueError,'modified tracked'):validate(self.config,self.plan_path,self.root/'runner')
            self.config.write_text(self.config.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'configuration changed'):validate(self.config,self.plan_path,self.root/'runner')

    def test_check_only_records_policy_without_constructing_any_host_adapter(self):
        logs=self.root/'logs'
        config=replace(Deployment.load(self.config),backup_challenge_templates=False)
        body=asdict(config);body['schema']=1
        self.config.write_text(json.dumps(body))
        self.plan=replace(self.plan,config_sha256=sha256(self.config))
        self.plan_path.write_text(json.dumps(self.plan.to_dict()))
        with patch('heist.rollout.launcher.revision',return_value='b'*40),patch('heist.rollout.launcher.git',return_value=b''),patch('heist.rollout.launcher.subprocess.Popen') as child,redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--config',str(self.config),'--plan',str(self.plan_path),'--logs',str(logs),'--check-only']),0)
        child.assert_not_called()
        latest=json.loads((logs/'latest.json').read_text())
        state=json.loads(Path(latest['status']).read_text())
        self.assertEqual(state['state'],'VALIDATED')
        self.assertFalse(state['challenge_template_backups'])

    def test_failure_and_existing_launcher_lock_never_start_a_child(self):
        logs=private_directory(self.root/'logs')
        arguments=['--config',str(self.config),'--plan',str(self.plan_path),'--logs',str(logs)]
        with patch('heist.rollout.launcher.subprocess.Popen') as child,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            with maintenance_lock(logs):self.assertEqual(main(arguments),1)
            self.config.write_text('{}')
            self.assertEqual(main(arguments),1)
        child.assert_not_called()
        latest=json.loads((logs/'latest.json').read_text())
        self.assertEqual(json.loads(Path(latest['status']).read_text())['state'],'PREFLIGHT_FAILED')
        self.assertTrue((Path(latest['run'])/'launcher-error.log').is_file())
