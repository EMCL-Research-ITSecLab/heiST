import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.verification import verify_evidence


class VerificationTests(unittest.TestCase):
    def receipt(self, root):
        (root/'output.log').write_text('passed\n')
        (root/'results.json').write_text(json.dumps({'counts': {'tests': 1, 'skipped': 0}}))
        value = {'schema': 1, 'suite': 'python', 'commit': 'a'*40, 'dirty': False, 'source_unchanged': True,
                 'returncode': 0, 'strict': True, 'log_sha256': hashlib.sha256((root/'output.log').read_bytes()).hexdigest(),
                 'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
        (root/'evidence.json').write_text(json.dumps(value))
        return value

    def test_correct_source_clean_strict_evidence_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.receipt(root)
            self.assertEqual(verify_evidence(root, 'a'*40, require_strict=True)['returncode'], 0)

    def test_other_revision_dirty_or_failing_receipts_are_rejected(self):
        for change in ({'commit': 'b'*40}, {'dirty': True}, {'returncode': 1}, {'source_unchanged': False}, {'strict': False}):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = self.receipt(root)
                value.update(change)
                (root/'evidence.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    verify_evidence(root, 'a'*40, require_strict=True)

    def test_tampering_with_result_counts_or_log_is_detected(self):
        for name in ('output.log', 'results.json'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.receipt(root)
                (root/name).write_text('tampered')
                with self.assertRaises(ValueError):
                    verify_evidence(root, 'a'*40, require_strict=True)
