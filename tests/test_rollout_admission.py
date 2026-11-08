"""Production admission needs private passing receipts for this exact release."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from heist.files import sha256
from heist.rollout.config import Deployment
from heist.rollout.admission import CHECKS,configuration_fingerprint,require


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.root.chmod(0o700)
        self.config=Deployment.load(Path(__file__).resolve().parents[1]/'config/deployment.example.json')
        self.plan=SimpleNamespace(source='a'*40,target='b'*40,rollback=False)
        self.evidence={}
        for name in CHECKS:
            item={'passed':True,'source_commit':'b'*40,'baseline_source':'a'*40,'check':name}
            if name=='strict_tests':
                item={'commit':'b'*40,'dirty':False,'returncode':0,'strict_skips':True,
                      'counts':{'tests':4,'failures':0,'errors':0,'skipped':0,'expected_failures':0}}
            path=self.root/(name+'.json');self.write(path,item)
            self.evidence[name]={'file':path.name,'sha256':sha256(path)}
        self.report={'schema':1,'kind':'production-clone-upgrade','source_commit':'b'*40,
            'baseline_source':'a'*40,'configuration_sha256':configuration_fingerprint(self.config),
            'evidence':self.evidence,'vm_uuids':{k:str(uuid.uuid4()) for k in ('web','database','monitoring')}}

    def write(self,path,value):
        path.write_text(json.dumps(value));path.chmod(0o600)

    def admitted(self):
        path=self.root/'acceptance.json';self.write(path,self.report)
        return replace(self.config,acceptance_receipt=str(path),acceptance_sha256=sha256(path))

    def test_no_receipt_fails_before_maintenance_and_a_complete_bound_receipt_passes(self):
        with self.assertRaisesRegex(RuntimeError,'no maintenance was entered'):
            require(self.config,self.plan)
        accepted=self.admitted()
        self.assertEqual(configuration_fingerprint(accepted),configuration_fingerprint(self.config))
        self.assertEqual(require(accepted,self.plan)['vm_uuids'],self.report['vm_uuids'])

    def test_rollback_requires_the_same_tested_pair_in_reverse_order(self):
        config=self.admitted()
        self.assertEqual(require(config,SimpleNamespace(source='b'*40,target='a'*40,rollback=True)),self.report)
        with self.assertRaisesRegex(RuntimeError,'does not bind'):
            require(config,SimpleNamespace(source='c'*40,target='a'*40,rollback=True))

    def test_source_target_and_deployment_changes_invalidate_admission(self):
        config=self.admitted()
        for plan in (SimpleNamespace(source='c'*40,target='b'*40,rollback=False),
                     SimpleNamespace(source='a'*40,target='c'*40,rollback=False)):
            with self.assertRaisesRegex(RuntimeError,'does not bind'):require(config,plan)
        with self.assertRaisesRegex(RuntimeError,'does not bind'):
            require(replace(config,web_hostname='other.example.edu'),self.plan)

    def test_missing_failed_or_tampered_evidence_is_not_a_release_pass(self):
        path=self.root/'precommit_recovery.json'
        value=json.loads(path.read_text());value['passed']=False;self.write(path,value)
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            require(self.admitted(),self.plan)
        self.evidence['precommit_recovery']['sha256']=sha256(path)
        with self.assertRaisesRegex(RuntimeError,'has not passed'):
            require(self.admitted(),self.plan)
        self.report['evidence']={}
        with self.assertRaisesRegex(RuntimeError,'Complete'):
            require(self.admitted(),self.plan)

    def test_skipped_dirty_or_wrong_source_tests_never_admit(self):
        path=self.root/'strict_tests.json';original=json.loads(path.read_text())
        for changes in ({'dirty':True},{'commit':'c'*40},{'counts':{**original['counts'],'skipped':1}}):
            self.write(path,{**original,**changes});self.evidence['strict_tests']['sha256']=sha256(path)
            with self.assertRaisesRegex(RuntimeError,'strict tests'):
                require(self.admitted(),self.plan)

    def test_symlinks_public_permissions_and_evidence_traversal_are_refused(self):
        config=self.admitted();path=Path(config.acceptance_receipt);path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError,'private'):require(config,self.plan)
        config=self.admitted();target=self.root/'original.json';path.rename(target);path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError,'regular'):require(config,self.plan)
        path.unlink();self.evidence['reboot']['file']='../elsewhere.json'
        with self.assertRaisesRegex(RuntimeError,'sibling'):require(self.admitted(),self.plan)
