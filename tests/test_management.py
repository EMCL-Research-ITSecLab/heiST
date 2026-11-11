"""Operator read models must preserve uncertainty and hide private recovery data."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from heist.platform.management import host_capacity, maintenance, transaction_history


class ManagementTests(unittest.TestCase):
    def test_unreadable_or_truncated_transaction_history_does_not_imply_empty_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            alias=root/'alias';alias.symlink_to(root,target_is_directory=True)
            self.assertTrue(transaction_history(alias)['unavailable'])
            directory=root/'transactions';directory.mkdir()
            broken=directory/'broken';broken.mkdir();(broken/'transaction.json').write_text('{')
            self.assertTrue(transaction_history(directory)['truncated'])
            for i in range(501):(directory/('irrelevant.'+str(i))).touch()
            self.assertTrue(transaction_history(directory)['truncated'])

    def test_capacity_rejects_missing_malformed_and_impossible_measurements(self):
        value={'memory':{'total':100,'used':50},'rootfs':{'total':500,'used':10},'cpuinfo':{'cpus':8},'cpu':.5}
        def run(*args,**kwargs):
            self.assertEqual(kwargs['timeout'],3)
            self.assertNotIn('shell',kwargs)
            return SimpleNamespace(stdout=json.dumps(value))
        self.assertEqual(host_capacity(run=run)['cpu_percent'],50)
        for changed in ({'memory':{'total':100,'used':101}},{'cpu':float('nan')},{'cpuinfo':{'cpus':True}},{'rootfs':{}}):
            with self.subTest(changed=changed):
                with patch.dict(value,changed):self.assertEqual(host_capacity(run=run),{'status':'unavailable'})
        self.assertEqual(host_capacity(run=lambda *a,**k:SimpleNamespace(stdout='x'*65537)),{'status':'unavailable'})

    def test_maintenance_exposes_only_validated_metadata_and_complete_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);transaction=root/'transactions/test-1';transaction.mkdir(parents=True)
            (transaction/'transaction.json').write_text(json.dumps({'plan':{'version':'0.4.0-rc.5','password':'never expose'},'phase':'RECOVERY_REQUIRED','checkpoint_ready':True,'committed':False,'private':'secret'}))
            config=root/'deployment.json';config.write_text('{}')
            settings={'HEIST_STATE_DIRECTORY':temporary,'HEIST_DEPLOYMENT_CONFIG':str(config),'HEIST_MAINTENANCE_FILE':str(root/'maintenance')}
            receipt={'baseline_source':'b'*40,'source_commit':'a'*40}
            with patch('heist.platform.operations.release_status',return_value={'commit':'a'*40}), \
                 patch('heist.rollout.config.Deployment.load',return_value=SimpleNamespace(acceptance_receipt='/private/evidence.json',acceptance_sha256='c'*64)), \
                 patch('heist.rollout.admission.read_evidence',return_value=receipt), \
                 patch('heist.rollout.admission.require',return_value=receipt) as verify:
                result=maintenance(settings)
                self.assertEqual(result['acceptance']['status'],'verified receipt')
                self.assertTrue(result['acceptance']['installed_match'])
                self.assertNotIn('secret',json.dumps(result));self.assertNotIn('password',json.dumps(result))
                self.assertEqual(verify.call_args.args[1].source,'b'*40)
                verify.side_effect=RuntimeError('Incomplete acceptance checks')
                self.assertEqual(maintenance(settings)['acceptance']['status'],'unavailable')
                verify.reset_mock();config.unlink();config.symlink_to(transaction/'transaction.json')
                self.assertEqual(maintenance(settings)['acceptance']['status'],'unavailable')
                verify.assert_not_called()
