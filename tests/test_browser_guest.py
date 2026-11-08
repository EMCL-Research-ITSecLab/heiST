"""Web guest admission and media preservation before privileged activation."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heist.rollout.browser_guest import install_guest, migrate_media, read_bundle, account, retire_legacy_root


class BrowserGuestTests(unittest.TestCase):
    def test_legacy_secrets_leave_the_serving_root_and_remain_private_on_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'html';source.mkdir()
            (source/'.env').write_bytes(b'private legacy configuration')
            (root/'.env').write_bytes(b'private legacy parent environment')
            retired=root/'retired'
            with patch('heist.rollout.browser_guest.RETIRED',retired):
                target=Path(retire_legacy_root(source))
                self.assertFalse(source.exists())
                self.assertEqual((target/'.env').read_bytes(),b'private legacy configuration')
                self.assertFalse((root/'.env').exists())
                self.assertEqual((retired/'environment').read_bytes(),b'private legacy parent environment')
                self.assertEqual(retired.stat().st_mode & 0o777,0o700)
                self.assertEqual(retire_legacy_root(source),str(target))
                retired.chmod(0o755)
                with self.assertRaisesRegex(RuntimeError,'private'):
                    retire_legacy_root(source)

    def test_retirement_refuses_symlinks_and_existing_destinations_without_losing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'html';source.mkdir();(source/'.env').write_text('keep')
            retired=root/'retired';retired.mkdir(mode=0o700);(retired/'root').mkdir()
            with patch('heist.rollout.browser_guest.RETIRED',retired):
                with self.assertRaisesRegex(RuntimeError,'Refusing'):
                    retire_legacy_root(source)
                self.assertEqual((source/'.env').read_text(),'keep')
                link=root/'link';link.symlink_to(source,target_is_directory=True)
                with self.assertRaisesRegex(RuntimeError,'Unsafe'):
                    retire_legacy_root(link)

    def test_oversized_and_symlinked_artifacts_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'bundle';path.write_bytes(b'reviewed')
            self.assertEqual(read_bundle(path,8),b'reviewed')
            with self.assertRaisesRegex(RuntimeError,'bounded'):read_bundle(path,7)
            link=root/'link';link.symlink_to(path)
            with self.assertRaisesRegex(RuntimeError,'symlinks'):read_bundle(link,8)
            with self.assertRaisesRegex(RuntimeError,'regular'):read_bundle(root,8)

    def test_shared_primary_group_cannot_access_browser_private_data(self):
        user=SimpleNamespace(pw_name='heist-web',pw_uid=200,pw_gid=200,
                             pw_dir='/var/lib/heist-web',pw_shell='/usr/sbin/nologin')
        other=SimpleNamespace(pw_name='other',pw_gid=200)
        group=SimpleNamespace(gr_name='heist-web',gr_mem=[])
        with patch('heist.rollout.browser_guest.pwd.getpwnam',return_value=user),\
             patch('heist.rollout.browser_guest.grp.getgrgid',return_value=group),\
             patch('heist.rollout.browser_guest.pwd.getpwall',return_value=[user,other]):
            with self.assertRaisesRegex(RuntimeError,'unexpected'):account()

    def test_no_deployment_mutation_without_root_and_persistent_maintenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker=Path(temporary)/'maintenance'
            with patch('heist.rollout.browser_guest.MAINTENANCE',marker),patch('heist.rollout.browser_guest.account') as account:
                with self.assertRaisesRegex(RuntimeError,'maintenance'):install_guest({})
                account.assert_not_called()

    def test_legacy_media_is_copied_byte_for_byte_and_repeated_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);legacy=root/'legacy';data=root/'data';data.mkdir()
            avatars=legacy/'uploads/avatars';avatars.mkdir(parents=True)
            (avatars/'student.png').write_bytes(b'opaque legacy image')
            user=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
            receipt=migrate_media(legacy,data,user)
            self.assertEqual(migrate_media(legacy,data,user),receipt)
            target=data/'media/avatars/student.png'
            self.assertEqual(target.read_bytes(),b'opaque legacy image')
            self.assertEqual((avatars/'student.png').read_bytes(),target.read_bytes())
            target.write_bytes(b'newer user image')
            with self.assertRaisesRegex(RuntimeError,'conflict'):migrate_media(legacy,data,user)
            self.assertEqual(target.read_bytes(),b'newer user image')

    def test_untrusted_media_symlinks_never_follow_service_owned_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);legacy=root/'legacy';data=root/'data';data.mkdir();legacy.mkdir()
            private=root/'private';private.mkdir()
            (legacy/'uploads').symlink_to(private,target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError,'symlink'):
                migrate_media(legacy,data,SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid()))
            self.assertEqual(list(private.iterdir()),[])
