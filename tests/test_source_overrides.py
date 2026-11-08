"""Only explicitly reviewed, regular tracked code may survive a source switch."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from heist.rollout.source_overrides import capture, validate


class SourceOverrideTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        (self.root/'backend').mkdir()
        self.path=self.root/'backend/launch.py';self.path.write_text('original source\n')
        self.path.chmod(0o750)
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        self.path.write_text('reviewed production fix\n')
        self.expected={'backend/launch.py':hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def test_reviewed_bytes_and_executable_mode_are_captured_without_changing_source(self):
        values,modes=capture(self.root,self.expected)
        self.assertEqual(values,{'backend/launch.py':self.path.read_bytes().hex()})
        self.assertEqual(modes,{'backend/launch.py':0o750})

    def test_drift_untracked_symlinks_and_writable_code_are_refused(self):
        self.path.write_text('changed after review')
        with self.assertRaisesRegex(RuntimeError,'changed'):capture(self.root,self.expected)
        self.path.write_text('reviewed production fix\n');self.path.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError,'permissions'):capture(self.root,self.expected)
        self.path.chmod(0o750);self.path.unlink();self.path.symlink_to(self.root/'outside')
        with self.assertRaisesRegex(RuntimeError,'regular'):capture(self.root,self.expected)
        (self.root/'backend/untracked.py').write_text('not reviewed')
        with self.assertRaisesRegex(RuntimeError,'tracked'):
            capture(self.root,{'backend/untracked.py':hashlib.sha256(b'not reviewed').hexdigest()})

    def test_configuration_cannot_authorize_secrets_git_metadata_or_escaping_paths(self):
        for name in ('../backend/a.py','backend/../a.py','/backend/a.py','backend/.env','.git/config','config/private.key','setup/secret.json','backend//a.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):validate({name:'a'*64})
        with self.assertRaises(ValueError):validate({'backend/a.py':'not a hash'})


class CustomizedCheckoutTests(unittest.TestCase):
    def test_failed_rollback_can_return_from_reviewed_legacy_source_to_newer_source(self):
        from types import SimpleNamespace
        from heist.rollout.pve import PVE
        from heist.rollout.controller import Transaction
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'backend').mkdir();path=root/'backend/launch.py';path.write_text('old source')
            git('add','.');git('commit','-qm','old');old=git('rev-parse','HEAD')
            git('rm','backend/launch.py');(root/'heist').mkdir();(root/'heist/app.py').write_text('new source')
            git('add','.');git('commit','-qm','new');new=git('rev-parse','HEAD')
            plan=SimpleNamespace(source=new,target=old)
            transaction=SimpleNamespace(data={'generated':{},'expected_target_generated':{}},plan=plan)
            adapter=PVE.__new__(PVE);adapter.installation=root
            adapter.command=lambda args:subprocess.check_output(list(map(str,args)))
            adapter._checkout(transaction,old)
            reviewed=b'actual reviewed production fix';path.write_bytes(reviewed)
            transaction.data['expected_target_generated']={'backend/launch.py':reviewed.hex()}
            adapter._checkout(transaction,new)
            self.assertEqual(git('rev-parse','HEAD'),new)
            self.assertEqual(git('status','--porcelain'),'')
            self.assertFalse(path.exists())

    def test_unreviewed_edit_is_preserved_before_any_checkout_or_restore(self):
        from types import SimpleNamespace
        from heist.rollout.pve import PVE
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'backend').mkdir();path=root/'backend/launch.py';path.write_text('original')
            git('add','.');git('commit','-qm','baseline');source=git('rev-parse','HEAD')
            path.write_text('unreviewed edit')
            adapter=PVE.__new__(PVE);adapter.installation=root
            transaction=SimpleNamespace(plan=SimpleNamespace(source=source,target='f'*40),data={'generated':{'backend/launch.py':b'reviewed edit'.hex()}})
            with self.assertRaisesRegex(RuntimeError,'changed after checkpoint'):
                adapter._checkout(transaction,'f'*40)
            self.assertEqual(path.read_text(),'unreviewed edit')
            self.assertEqual(git('rev-parse','HEAD'),source)
