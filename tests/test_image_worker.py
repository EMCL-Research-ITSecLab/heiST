"""Disk parsing never borrows a login account or a shared privileged group."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from heist.artifacts.conversion_account import account


class ImageWorkerTests(unittest.TestCase):
    def setUp(self):
        self.user=SimpleNamespace(pw_name='heist-image',pw_uid=990,pw_gid=990,
                                 pw_dir='/nonexistent',pw_shell='/usr/sbin/nologin')
        self.group=SimpleNamespace(gr_name='heist-image',gr_gid=990,gr_mem=[])

    def check(self,users=None,groups=None):
        with patch('heist.artifacts.conversion_account.pwd.getpwnam',return_value=self.user), \
                patch('heist.artifacts.conversion_account.grp.getgrgid',return_value=self.group), \
                patch('heist.artifacts.conversion_account.pwd.getpwall',return_value=users or [self.user]), \
                patch('heist.artifacts.conversion_account.grp.getgrall',return_value=groups or [self.group]):
            return account()

    def test_only_a_dedicated_system_identity_is_accepted(self):
        self.assertIs(self.check(),self.user)
        self.user.pw_shell='/bin/bash'
        with self.assertRaisesRegex(RuntimeError,'dedicated'):self.check()

    def test_shared_primary_and_privileged_supplementary_groups_are_refused(self):
        with self.assertRaisesRegex(RuntimeError,'dedicated'):
            self.check(users=[self.user,SimpleNamespace(pw_name='other',pw_gid=990)])
        with self.assertRaisesRegex(RuntimeError,'dedicated'):
            self.check(groups=[self.group,SimpleNamespace(gr_gid=27,gr_mem=['heist-image'])])

    def test_normalization_does_not_create_accounts_and_provisioning_requires_root(self):
        with patch('heist.artifacts.conversion_account.pwd.getpwnam',side_effect=KeyError), \
                patch('heist.artifacts.conversion_account.os.geteuid',return_value=1000), \
                patch('heist.artifacts.conversion_account.subprocess.run') as run:
            with self.assertRaisesRegex(RuntimeError,'requires'):account()
            with self.assertRaisesRegex(RuntimeError,'Only root'):account(create=True)
            run.assert_not_called()

    def test_provisioning_creates_no_home_or_login_and_revalidates_the_result(self):
        with patch('heist.artifacts.conversion_account.pwd.getpwnam',side_effect=[KeyError,self.user]), \
                patch('heist.artifacts.conversion_account.os.geteuid',return_value=0), \
                patch('heist.artifacts.conversion_account.grp.getgrgid',return_value=self.group), \
                patch('heist.artifacts.conversion_account.pwd.getpwall',return_value=[self.user]), \
                patch('heist.artifacts.conversion_account.grp.getgrall',return_value=[self.group]), \
                patch('heist.artifacts.conversion_account.subprocess.run') as run:
            self.assertIs(account(create=True),self.user)
            args=run.call_args.args[0]
            self.assertIn('--system',args)
            self.assertIn('--no-create-home',args)
            self.assertIn('/usr/sbin/nologin',args)
