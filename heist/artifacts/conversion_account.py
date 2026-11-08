"""Provision and validate the dedicated account used for disk conversion."""
import grp
import os
import pwd
import subprocess


def account(*, create=False):
    name='heist-image'
    try:
        user=pwd.getpwnam(name)
    except KeyError:
        if not create:raise RuntimeError('Disk conversion requires the heist-image system account') from None
        if os.geteuid()!=0:raise RuntimeError('Only root may provision the disk conversion account')
        subprocess.run(['useradd','--system','--user-group','--no-create-home',
                        '--home-dir','/nonexistent','--shell','/usr/sbin/nologin',name],
                       check=True,capture_output=True,timeout=30)
        user=pwd.getpwnam(name)
    group=grp.getgrgid(user.pw_gid)
    if (user.pw_uid<100 or user.pw_gid<100 or user.pw_dir!='/nonexistent'
            or user.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin')
            or group.gr_name!=name or group.gr_mem
            or any(other.pw_name!=name and other.pw_gid==user.pw_gid for other in pwd.getpwall())
            or any(other.gr_gid!=user.pw_gid and name in other.gr_mem for other in grp.getgrall())):
        raise RuntimeError('Disk conversion requires a dedicated unprivileged system account and group')
    return user
