"""Unsafe scopes and damaged/stale backups are rejected before any command."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.monitoring import probes
from tools.monitoring.restore_probe import verify


class ProbeTests(unittest.TestCase):
    def test_packet_archive_and_web_reject_invalid_run_identity_before_commands(self):
        for probe in (probes.packet_probe, probes.archive_probe, probes.web_probe):
            with self.subTest(probe=probe.__name__), patch('subprocess.run') as run:
                with self.assertRaises(ValueError):probe({'run_id':'invalid'})
                run.assert_not_called()

    def test_grafana_query_does_not_accept_arbitrary_sql_as_a_canary(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(ValueError):probes.monitoring_probe({'query_name':"';SELECT secret"})
            run.assert_not_called()

    def test_bad_or_stale_source_never_starts_restore_container(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run') as run:
            root=Path(directory);body=b'PGDMPfixture';(root/'database.backup').write_bytes(body)
            metadata={'bytes':len(body),'sha256':'0'*64,'created_at':datetime.now(timezone.utc).isoformat()}
            (root/'source-metadata.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'checksum'):verify(root)
            metadata['sha256']=hashlib.sha256(body).hexdigest()
            metadata['created_at']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
            (root/'source-metadata.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'stale'):verify(root)
            run.assert_not_called()
