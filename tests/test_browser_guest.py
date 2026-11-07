"""Web guest admission and media preservation before privileged activation."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heist.rollout.browser_guest import install_guest, migrate_media, read_bundle, account


class BrowserGuestTests(unittest.TestCase):
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
