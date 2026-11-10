"""Kernel regression for the VPN/DMZ AF_PACKET configuration, without traffic."""
import json
import os
import shutil
import subprocess
import sys
import unittest

PROBE = r'''
import errno,json,socket,struct,subprocess
# sysfs can retain its original mount's network namespace. Query netlink instead.
links=json.loads(subprocess.check_output(['ip','-j','link','show']))
if {link['ifname'] for link in links}!={'lo'}:
    raise RuntimeError('Require a fresh isolated network namespace')
for interface in ('probe_vpn','probe_dmz'):
    subprocess.run(['ip','link','add',interface,'type','dummy'],check=True)
    subprocess.run(['ip','link','set',interface,'up'],check=True)
with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)) as vpn:
    vpn.bind(('probe_vpn',0))
    vpn.setsockopt(263,18,struct.pack('I',99))
    with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)) as dmz:
        dmz.bind(('probe_dmz',0))
        try:
            dmz.setsockopt(263,18,struct.pack('I',99))
        except OSError as error:
            if error.errno!=errno.EINVAL:raise
        else:
            raise RuntimeError('Expected cross-interface fanout collision was not reproduced')
        dmz.setsockopt(263,18,struct.pack('I',100))
print(json.dumps({'isolated_namespace':True,'shared_group_rejected':True,'distinct_group_accepted':True,'frames_captured':0}))
'''


@unittest.skipUnless(os.geteuid()==0 and os.environ.get('HEIST_PRIVILEGED_TESTS')=='1'
                     and shutil.which('unshare') and shutil.which('ip'),
                     'Explicit HEIST_PRIVILEGED_TESTS=1, root, ip and unshare required')
class SuricataFanoutTests(unittest.TestCase):
    def test_shared_fanout_fails_and_distinct_fanout_succeeds_on_real_kernel(self):
        result=subprocess.run(['unshare','--net',sys.executable,'-c',PROBE],capture_output=True,text=True,check=True,timeout=10)
        self.assertEqual(json.loads(result.stdout),{'isolated_namespace':True,'shared_group_rejected':True,
                         'distinct_group_accepted':True,'frames_captured':0})
