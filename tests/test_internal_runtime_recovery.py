"""Rollbacks restore the exact selected root runtime or the legacy no-runtime state."""
import json
from pathlib import Path
import tempfile
import unittest

from heist.rollout.internal_runtime import capture,select


class InternalRuntimeRecoveryTests(unittest.TestCase):
    def test_older_and_newer_selections_recover_without_replacing_immutable_runtime_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for commit in ('a'*40,'b'*40):
                version=root/'versions'/commit;version.mkdir(parents=True)
                (version/'metadata.json').write_text(json.dumps({'source_commit':commit}))
                (version/'gunicorn.whl').write_bytes(commit.encode())
            current=root/'current';current.symlink_to('versions/'+'a'*40,target_is_directory=True)
            older=capture(root)
            current.unlink();current.symlink_to('versions/'+'b'*40,target_is_directory=True)
            newer=capture(root)
            select(root,older);self.assertEqual(current.resolve().name,'a'*40)
            select(root,newer);self.assertEqual(current.resolve().name,'b'*40)
            select(root,None);self.assertIsNone(capture(root))
            self.assertTrue((root/'versions'/('a'*40)/'gunicorn.whl').exists())

    def test_corrupt_or_escaping_selection_is_refused_before_switching_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);version=root/'versions'/('a'*40);version.mkdir(parents=True)
            (version/'metadata.json').write_text(json.dumps({'source_commit':'a'*40}))
            wheel=version/'gunicorn.whl';wheel.write_bytes(b'original')
            current=root/'current';current.symlink_to('versions/'+'a'*40,target_is_directory=True)
            saved=capture(root);wheel.write_bytes(b'corrupt')
            with self.assertRaises(RuntimeError):select(root,saved)
            self.assertEqual(current.resolve(),version)
            current.unlink();current.symlink_to('/outside')
            with self.assertRaises(RuntimeError):capture(root)

    def test_runtime_parent_symlinks_are_refused_without_reading_external_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);outside=root/'outside';outside.mkdir()
            runtime=root/'runtime';runtime.mkdir()
            (runtime/'versions').symlink_to(outside,target_is_directory=True)
            (runtime/'current').symlink_to('versions/'+'a'*40)
            with self.assertRaisesRegex(RuntimeError,'Symlink'):capture(runtime)
            with self.assertRaisesRegex(RuntimeError,'Symlink'):select(runtime,None)
            self.assertEqual(list(outside.iterdir()),[])
