"""Off-host detection survives a failed UI, source timeout or stale receipt."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import shlex
import tempfile
import unittest
from unittest.mock import Mock

from heist.monitoring.health import sanitize
from heist.monitoring.watchdog import REQUIRED, evaluate, observe
from tools.build.watchdog import build

NOW = datetime(2026,11,10,12,tzinfo=timezone.utc)


def source(**changes):
    value={'schema':1,'checked_at':NOW.isoformat(),'checks':[
        {'id':name,'label':'Service','state':'ok','summary':'private detail'} for name in REQUIRED]}
    value.update(changes)
    return json.dumps(value).encode()


class WatchdogTests(unittest.TestCase):
    def test_source_service_failure_stale_heartbeat_and_recovery_are_observed(self):
        value,critical=evaluate(source(),now=NOW)
        self.assertFalse(critical)
        self.assertEqual(sanitize(value,now=NOW)['status'],'ok')
        failed=json.loads(source());failed['checks'][0]['state']='failed'
        self.assertTrue(evaluate(json.dumps(failed).encode(),now=NOW)[1])
        self.assertTrue(evaluate(source(),now=NOW+timedelta(seconds=181))[1])
        self.assertFalse(evaluate(source(checked_at=(NOW+timedelta(minutes=4)).isoformat()),now=NOW+timedelta(minutes=4))[1])
        self.assertNotIn('private detail',json.dumps(value))

    def test_unknown_coverage_is_degraded_but_not_a_false_service_failure(self):
        value=json.loads(source());value['checks'].append({'id':'host.end_to_end','label':'Coverage','state':'unknown','summary':'Not verified'})
        receipt,critical=evaluate(json.dumps(value).encode(),now=NOW)
        self.assertFalse(critical)
        self.assertEqual(sanitize(receipt,now=NOW)['status'],'unknown')
        value['checks'].pop(0)
        self.assertTrue(evaluate(json.dumps(value).encode(),now=NOW)[1])

    def test_unreachable_source_and_invalid_inventory_fail_without_exposing_ssh_errors(self):
        config={'schema':1,'host':'host.example.invalid','user':'root','status_file':'/var/lib/heist/monitoring/status.json'}
        run=Mock(side_effect=subprocess.TimeoutExpired('ssh private',12))
        value,critical=observe(config,'/run/credentials/heist-watchdog.service',run=run,now=NOW)
        self.assertTrue(critical)
        self.assertNotIn('private',json.dumps(value))
        self.assertIn('StrictHostKeyChecking=yes',run.call_args.args[0])
        self.assertIn('IdentityAgent=none',run.call_args.args[0])
        self.assertNotIn('shell',run.call_args.kwargs)
        for body in (b'x'*65537,b'null',b'{}',source(checked_at='2026-11-10T12:00:00')):
            self.assertTrue(evaluate(body,now=NOW)[1])

    def test_unreachable_infrastructure_role_is_critical_even_with_a_fresh_host_receipt(self):
        value=json.loads(source())
        value['checks']=[c for c in value['checks'] if not c['id'].startswith('web.')]
        value['checks'].append({'id':'web.connection','label':'Web connection','state':'unknown','summary':'Unavailable'})
        receipt,critical=evaluate(json.dumps(value).encode(),now=NOW)
        self.assertTrue(critical)
        self.assertEqual(sanitize(receipt,now=NOW)['status'],'failed')

    def test_standalone_archive_host_artifact_needs_no_app_or_third_party_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact=Path(directory)/'watchdog.pyz'
            build(artifact)
            result=subprocess.run([sys.executable,'-I','-S',str(artifact),'--help'],capture_output=True,text=True,timeout=5,check=True)
            self.assertIn('--config',result.stdout)
            self.assertIn('--output',result.stdout)
            receipt=Path(directory)/'source.json'
            receipt.write_bytes(source(checked_at=datetime.now(timezone.utc).isoformat()))
            ssh=Path(directory)/'ssh'
            ssh.write_text('#!/bin/sh\nexec /bin/cat '+shlex.quote(str(receipt))+'\n');ssh.chmod(0o700)
            config=Path(directory)/'config.json'
            config.write_text(json.dumps({'schema':1,'host':'host.example.invalid','user':'root','status_file':'/var/lib/heist/monitoring/status.json'}))
            output=Path(directory)/'output.json'
            command=[sys.executable,'-I','-S',str(artifact),'--config',str(config),'--output',str(output)]
            env={**os.environ,'PATH':directory+os.pathsep+os.defpath,'CREDENTIALS_DIRECTORY':directory}
            for failed in (False,True,False):
                value=json.loads(source(checked_at=datetime.now(timezone.utc).isoformat()))
                if failed:value['checks'][0]['state']='failed'
                receipt.write_text(json.dumps(value))
                result=subprocess.run(command,env=env,capture_output=True,timeout=5)
                self.assertEqual(result.returncode,int(failed),result.stderr)
                self.assertEqual(json.loads(output.read_text())['status'],'failed' if failed else 'ok')
            with self.assertRaises(ValueError):build(artifact)
