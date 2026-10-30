#!/usr/bin/env python3
"""Verify public web maintenance gating across a real disposable web-VM reboot."""
import argparse
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from heist.files import sha256
from heist.rollout import web
from heist.rollout.config import Deployment
from heist.rollout.pve import PVE
from tools.local.rehearse_recovery import require_fixture


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    require_fixture()
    config = Deployment.load(args.config)
    operations = PVE(config, sha256(args.config))
    operations.assert_idle(allow_ready=False)
    vm = config.vm('web')
    services = json.loads(operations.remote(vm, web.CAPTURE_SERVICES))
    if not services['apache2']['active']:
        raise RuntimeError('Start with a healthy running web service')
    tables = ('users', 'completed_challenges', 'challenge_flags')
    protected = operations.protected_hashes(tables)
    with socket.create_connection((vm.host, 443), timeout=5):
        pass
    old_boot = vm.ssh.run(['cat', '/proc/sys/kernel/random/boot_id']).stdout.strip()

    def check_gate():
        vm.ssh.run(['true'], timeout=15)
        operations.remote(vm, web.LOCAL_HEALTH, {'certificate': config.web_certificate})
        try:
            connection = socket.create_connection((vm.host, 443), timeout=5)
        except OSError:
            return
        connection.close()
        raise AssertionError('Public web port remained reachable during maintenance')

    try:
        operations.remote(vm, web.INSTALL_GUARD, {'program': web.FIREWALL})
        check_gate()
        operations.command(['qm', 'reboot', vm.vmid, '--timeout', '180'], timeout=210)

        def restarted():
            current = vm.ssh.run(['cat', '/proc/sys/kernel/random/boot_id'], timeout=15).stdout.strip()
            if current == old_boot:
                raise RuntimeError('Web VM has not rebooted yet')

        operations.wait(restarted, 'new web VM boot')
        operations.wait(check_gate, 'maintenance gate and loopback health after reboot')
        print('Web maintenance gate, loopback health and SSH survived a real VM reboot')
    finally:
        operations.remote(vm, web.FINISH, {'services': services, 'open': True})
    with socket.create_connection((vm.host, 443), timeout=5):
        pass
    if operations.protected_hashes(tables) != protected:
        raise AssertionError('Protected student/grade data changed during web reboot')
    operations._health(legacy=True, local_web=True)
    print('Public web access restored; protected student data unchanged')


if __name__ == '__main__':
    raise SystemExit(main())
