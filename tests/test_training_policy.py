"""Training eligibility must reject opt-outs and ambiguous shared captures."""
from datetime import datetime, timezone
import copy
import unittest

from heist.monitoring.training import eligibility

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def fixture():
    return ({'schema':1,'purpose':'training','scope':'isolated-instance','participants_complete':True,
             'closed':True,'sha256':'a'*64,'started_at':'2026-11-11T11:00:00Z','ended_at':'2026-11-11T11:01:00Z',
             'participants':[{'user_id':1,'preference_revision':1},{'user_id':2,'preference_revision':1}]},
            {i:{'opted_out':False,'revision':1,'updated_at':'2026-11-11T10:00:00Z'} for i in (1,2)})


class TrainingPolicyTests(unittest.TestCase):
    def test_command_does_not_connect_or_copy_when_training_is_disabled(self):
        from contextlib import redirect_stdout
        import io,json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from heist.monitoring.training import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest,preferences=fixture()
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'private.env').write_text('DB_PASSWORD=fixture-private\n')
            output=io.StringIO()
            with patch('heist.config.DatabaseSettings.connect') as connect,redirect_stdout(output):
                self.assertEqual(main(['--manifest',str(root/'manifest.json'),'--environment',str(root/'private.env')]),1)
            connect.assert_not_called()
            self.assertEqual(json.loads(output.getvalue()),{'eligible_for_training':False,'reason':'training_disabled','data_copied':False})
            self.assertNotIn('fixture-private',output.getvalue())

    def test_feature_is_disabled_until_capture_pipeline_acceptance(self):
        manifest,preferences=fixture()
        self.assertEqual(eligibility(manifest,preferences,now=NOW),(False,'training_disabled'))

    def test_all_known_participants_must_be_eligible(self):
        manifest,preferences=fixture()
        self.assertEqual(eligibility(manifest,preferences,enabled=True,now=NOW),(True,'eligible'))
        preferences[2]['opted_out']=True
        self.assertEqual(eligibility(manifest,preferences,enabled=True,now=NOW),(False,'opted_out'))

    def test_rejoining_does_not_make_old_captures_eligible(self):
        manifest,preferences=fixture()
        preferences[2].update(revision=3,updated_at='2026-11-11T11:30:00Z')
        self.assertEqual(eligibility(manifest,preferences,enabled=True,now=NOW),(False,'preference_changed'))

    def test_shared_unknown_deleted_or_open_capture_is_rejected(self):
        for case in ('shared','missing','unknown','open','duplicate','future'):
            manifest,preferences=fixture()
            if case=='shared':manifest['scope']='shared-platform'
            if case=='missing':preferences.pop(2)
            if case=='unknown':manifest['participants_complete']=False
            if case=='open':manifest['closed']=False
            if case=='duplicate':manifest['participants'].append(copy.copy(manifest['participants'][0]))
            if case=='future':manifest['ended_at']='2027-11-11T11:00:00Z'
            with self.subTest(case=case):self.assertFalse(eligibility(manifest,preferences,enabled=True,now=NOW)[0])
