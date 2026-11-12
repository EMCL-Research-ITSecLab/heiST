"""Delivery evidence must include failures/recovery and cannot be silently renewed."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from heist.monitoring.health import DELIVERY_CONTRACTS, delivery_checks

NOW = datetime(2026, 11, 11, 23, tzinfo=timezone.utc)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installed = self.root/'installed';self.installed.write_text(json.dumps({'commit':'a'*40}))
        self.boot = self.root/'boot';self.boot.write_text('fixture-boot')

    def proof(self, role='host'):
        return {'schema':1,'role':role,'source_commit':'a'*40,'probe_commit':'b'*40,
                'host_boot_id':'fixture-boot','collector_sha256':'c'*64,'run_id':'d'*32,
                'checked_at':NOW.isoformat(),'steps':dict.fromkeys(DELIVERY_CONTRACTS[role][1],True)}

    def save(self, value, role='host'):
        path = self.root/(role+'.json');path.write_text(json.dumps(value));path.chmod(0o600)
        return path

    def checks(self, now=NOW):
        value={'checks':[{'id':role+'.end_to_end','state':'unknown'} for role in DELIVERY_CONTRACTS]}
        result=delivery_checks(value,directory=self.root,installed=self.installed,boot=self.boot,collector='c'*64,now=now)
        return {c['id'].split('.')[0]:c for c in result['checks']}

    def test_each_role_requires_its_own_current_complete_proof(self):
        self.assertTrue(all(c['state']=='unknown' for c in self.checks().values()))
        for role in DELIVERY_CONTRACTS:
            self.save(self.proof(role),role);self.assertEqual(self.checks()[role]['state'],'ok')
        self.assertTrue(all(c['state']=='ok' for c in self.checks().values()))

    def test_positive_delivery_without_failure_and_recovery_is_unverified(self):
        proof=self.proof();del proof['steps']['interruption_detected'];self.save(proof)
        self.assertEqual(self.checks()['host']['state'],'unknown')

    def test_failed_step_is_reported_as_failed(self):
        proof=self.proof();proof['steps']['recovery']=False;self.save(proof)
        self.assertEqual(self.checks()['host']['state'],'failed')

    def test_stale_proof_is_not_refreshed_by_collector(self):
        self.save(self.proof())
        self.assertEqual(self.checks(NOW+timedelta(hours=24,seconds=1))['host']['state'],'unknown')
        self.assertEqual(json.loads((self.root/'host.json').read_text())['checked_at'],NOW.isoformat())

    def test_identity_time_and_boolean_contracts_are_enforced(self):
        cases=[('source_commit','e'*40),('host_boot_id','other-boot'),('collector_sha256','e'*64),
               ('run_id','bad'),('role','archive'),('schema',2),('probe_commit','bad'),
               ('checked_at',(NOW+timedelta(minutes=1)).isoformat()),('checked_at','2026-11-11T23:00:00')]
        for field,value in cases:
            with self.subTest(field=field,value=value):
                proof=self.proof();proof[field]=value;self.save(proof)
                self.assertEqual(self.checks()['host']['state'],'unknown')
        proof=self.proof();proof['steps']['recovery']=1;self.save(proof)
        self.assertEqual(self.checks()['host']['state'],'unknown')

    def test_private_regular_bounded_evidence_only(self):
        path=self.save(self.proof());path.chmod(0o644)
        self.assertEqual(self.checks()['host']['state'],'unknown')
        path.unlink();target=self.root/'other';target.write_text(json.dumps(self.proof()));target.chmod(0o600)
        path.symlink_to(target);self.assertEqual(self.checks()['host']['state'],'unknown')
        path.unlink();path.write_text('x'*8193);path.chmod(0o600)
        self.assertEqual(self.checks()['host']['state'],'unknown')

    def test_private_details_are_not_projected_to_public_receipt(self):
        proof=self.proof();proof['private_detail']='student-command-secret';self.save(proof)
        result=self.checks();self.assertNotIn('student-command-secret',json.dumps(result))
        self.assertEqual(result['host']['state'],'ok')
