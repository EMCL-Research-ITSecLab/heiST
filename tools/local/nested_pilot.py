#!/usr/bin/env python3
"""Prepare and operate a disposable nested Proxmox pilot (never modifies host networking).

Base image and its matching official SHA512SUMS must be supplied separately.
Private keys, cloud-init, guest logs and disks stay in an external work directory.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PORTS = {'ssh': 22220, 'web': 18443, 'proxmox': 18006, 'vpn': 11194}


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def check_image(image, sums):
    entries = [line.split() for line in sums.read_text().splitlines()]
    hashes = [parts[0] for parts in entries if len(parts) == 2 and parts[1].lstrip('*') == image.name]
    if len(hashes) != 1:
        raise ValueError('Expected exactly one matching filename in official SHA512SUMS')
    value = hashlib.sha512()
    with image.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    if value.hexdigest() != hashes[0]:
        raise ValueError('Debian base SHA512 mismatch')
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(image)]))
    if info.get('backing-filename') or info['format'] != 'qcow2':
        raise ValueError('Base must be a standalone QCOW2')
    return value.hexdigest()


def management_ports(config):
    """Use one validated loopback port mapping for boot, SSH and isolation proof."""
    ports = config.get('ports', PORTS)
    if (not isinstance(ports, dict) or set(ports) != set(PORTS)
            or any(type(port) is not int or not 1024 <= port <= 65535 for port in ports.values())
            or len(set(ports.values())) != len(PORTS)):
        raise ValueError('Declare four distinct unprivileged management ports')
    return dict(ports)


def pilot_configuration(work):
    path = work / 'pilot.json'
    return json.loads(path.read_text()) if path.exists() else {}


def management_network(config, *, online=False):
    ports = management_ports(config)
    network = 'user,id=mgmt,restrict=' + ('off' if online else 'on')
    for protocol, name, remote in [('tcp', 'ssh', 22), ('tcp', 'web', 443),
                                   ('tcp', 'proxmox', 8006), ('udp', 'vpn', 1194)]:
        network += f',hostfwd={protocol}:127.0.0.1:{ports[name]}-:{remote}'
    return network


def prepare(work, image, sums, *, port_offset=0, memory_mib=36864, cpus=12):
    ports = management_ports({'ports': {name: port + port_offset for name, port in PORTS.items()}})
    if type(memory_mib) is not int or not 2048 <= memory_mib <= 1048576 or type(cpus) is not int or not 1 <= cpus <= 256:
        raise ValueError('Declare 2048–1048576 MiB memory and 1–256 CPUs')
    if work.exists():
        raise ValueError('Use a new work directory; existing pilots are never overwritten')
    if shutil.disk_usage(work.parent).free < 70 * 1024**3:
        raise ValueError('Need at least 70 GiB free for the initial pilot; monitor usage during imports')
    image_hash = check_image(image, sums)
    work.mkdir(mode=0o700)
    run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', work / 'id_ed25519')
    public = (work / 'id_ed25519.pub').read_text().strip()
    # The upstream installer needs a root PAM password too. Generate inside the
    # private workspace, never in argv or shared source.
    import secrets
    password = secrets.token_urlsafe(30)
    (work / 'root-password').write_text(password + '\n')
    seed = work / 'seed'
    seed.mkdir()
    (seed / 'meta-data').write_text('instance-id: heist-nested-pilot\nlocal-hostname: heist-pilot\n')
    (seed / 'user-data').write_text(
        '#cloud-config\nhostname: heist-pilot\nfqdn: heist-pilot.test\n'
        'manage_etc_hosts: false\ndisable_root: false\nssh_pwauth: false\n'
        'users:\n  - name: root\n    ssh_authorized_keys:\n      - ' + public + '\n'
        'chpasswd:\n  expire: false\n  users:\n    - name: root\n      password: ' + password + '\n      type: text\n'
        'write_files:\n  - path: /etc/hosts\n    content: |\n'
        '      127.0.0.1 localhost\n      10.0.2.15 heist-pilot.test heist-pilot\n'
        'runcmd:\n  - [touch, /root/pilot-cloud-init-ready]\n')
    (seed / 'network-config').write_text(
        'version: 2\nethernets:\n  ens3:\n    match:\n      macaddress: "52:54:00:48:53:01"\n'
        '    set-name: ens3\n    dhcp4: true\n')
    run('xorriso', '-as', 'mkisofs', '-quiet', '-volid', 'cidata', '-joliet', '-rock',
        '-output', work / 'seed.iso', seed)
    # Flatten the base so this appliance survives movement to another workstation.
    run('qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', image, work / 'disk.qcow2')
    run('qemu-img', 'resize', work / 'disk.qcow2', '96G')
    shutil.copy2(ROOT / 'tools/local/prepare-proxmox.sh', work / 'prepare-proxmox.sh')
    (work / 'pilot.json').write_text(json.dumps({
        'schema': 1, 'base': image.name, 'base_sha512': image_hash,
        'memory_mib': memory_mib, 'cpus': cpus, 'ports': ports,
        'production_accepted': False,
    }, indent=2) + '\n')
    for path in work.rglob('*'):
        if path.is_file():
            path.chmod(0o600)
    print('Prepared private pilot:', work)
    print('Start with --online for OS provisioning only; use offline mode for vulnerable guests.')


def qmp(work, command):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(work / 'qmp.sock'))
        stream = client.makefile('rwb', buffering=0)
        json.loads(stream.readline())
        for request in ('qmp_capabilities', command):
            stream.write(json.dumps({'execute': request}).encode() + b'\n')
            while True:
                reply = json.loads(stream.readline())
                if 'error' in reply:
                    raise ValueError(str(reply['error']))
                if 'return' in reply:
                    break
        return reply['return']


def supplemental_storage(work, config):
    """Keep hot VM data on scratch storage and bulk backups on a separate disk."""
    arguments = []
    root = work/'disk.qcow2'
    seen = {(root.stat().st_dev, root.stat().st_ino)} if root.is_file() else set()
    for name, serial in (('backup','HEIST-ROLLOUT-BACKUP'), ('data','HEIST-PLATFORM-DATA')):
        enabled = config.get('attach_'+name+'_disk',False)
        if type(enabled) is not bool:
            raise ValueError('Disk attachment flags must be booleans')
        if not enabled:
            continue
        value = config.get('backup_disk_path',str(work/'backup.qcow2')) if name=='backup' else str(work/'data.qcow2')
        if not isinstance(value,str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+',value):
            raise ValueError('Use a plain absolute QCOW2 path')
        disk = Path(value)
        if str(disk)!=value or '..' in disk.parts or disk.is_symlink() or not disk.is_file():
            raise ValueError('Supply a private standalone '+name+'.qcow2')
        if any(parent.is_symlink() for parent in disk.parents) or disk.parent.stat().st_mode & 0o077:
            raise ValueError('Supplemental disks require a private parent directory without symlinks')
        identity=(disk.stat().st_dev,disk.stat().st_ino)
        if identity in seen:
            raise ValueError('Each attached disk must be a distinct file')
        seen.add(identity)
        info=json.loads(subprocess.check_output(['qemu-img','info','--output=json',str(disk)]))
        if info.get('backing-filename') or info.get('format')!='qcow2':
            raise ValueError('Supplemental disks must be standalone QCOW2')
        arguments += ['-drive',f'file={disk},format=qcow2,if=none,id=heist{name},cache=none,discard=unmap',
                      '-device',f'virtio-blk-pci,drive=heist{name},serial={serial}']
    return arguments


def check_storage_capacity(work, config, *, reserve=32*1024**3):
    """Sparse disks must fit when fully allocated, including a filesystem reserve."""
    disks=[work/'disk.qcow2']
    for name in ('backup','data'):
        if config.get('attach_'+name+'_disk',False):
            disks.append(Path(config.get('backup_disk_path',str(work/'backup.qcow2')))
                         if name=='backup' else work/'data.qcow2')
    filesystems={}
    for path in disks:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Capacity checks require regular pilot disks')
        info=json.loads(subprocess.check_output(['qemu-img','info','--output=json',str(path)]))
        virtual=info.get('virtual-size')
        if type(virtual) is not int or virtual<=0:
            raise ValueError('Cannot confirm pilot disk virtual capacity')
        stat=path.stat()
        entry=filesystems.setdefault(stat.st_dev,{'path':str(path.parent),'remaining':0,'disks':[]})
        # Include QCOW2 metadata growth. Backing images already occupy host
        # space; an overlay may still allocate its entire virtual size again.
        entry['remaining']+=max(0,virtual-stat.st_blocks*512)+max(64*1024**2,virtual//128)
        entry['disks'].append(str(path))
    for entry in filesystems.values():
        free=shutil.disk_usage(entry['path']).free
        required=entry['remaining']+reserve
        if free<required:
            raise ValueError('Insufficient backing storage at '+entry['path']+
                             ': sparse pilot disks need '+str((required+1024**3-1)//1024**3)+
                             ' GiB available including reserve; move them to a larger persistent filesystem')


def start(work, online=False):
    if (work / 'qmp.sock').exists():
        raise ValueError('QMP socket exists; inspect the existing process before restarting')
    if not os.access('/dev/kvm', os.R_OK | os.W_OK):
        raise ValueError('Need read/write access to /dev/kvm')
    nested = Path('/sys/module/kvm_intel/parameters/nested')
    if nested.exists() and nested.read_text().strip() not in ('Y', '1'):
        raise ValueError('Nested Intel KVM is disabled')
    config = json.loads((work / 'pilot.json').read_text())
    network = management_network(config, online=online)
    nic_model = config.get('nic_model', 'virtio-net-pci')
    disk_bus = config.get('disk_bus', 'virtio')
    if nic_model not in ('virtio-net-pci', 'e1000') or disk_bus not in ('virtio', 'sata'):
        raise ValueError('Unsupported pilot appliance disk/NIC profile')
    storage = ['-drive', f'file={work}/disk.qcow2,format=qcow2,if=virtio,cache=none,discard=unmap,detect-zeroes=unmap']
    if disk_bus == 'sata':
        storage = ['-device', 'ich9-ahci,id=pilotahci',
                   '-drive', f'file={work}/disk.qcow2,format=qcow2,if=none,id=pilotdisk,cache=none,discard=unmap,detect-zeroes=unmap',
                   '-device', 'ide-hd,drive=pilotdisk,bus=pilotahci.0,bootindex=1']
    storage += supplemental_storage(work,config)
    check_storage_capacity(work,config)
    if config.get('attach_seed', True):
        storage += ['-drive', f'file={work}/seed.iso,format=raw,media=cdrom,readonly=on']
    run('qemu-system-x86_64', '-name', 'heist-nested-pilot', '-enable-kvm', '-cpu', 'host',
        '-machine', 'q35', '-smp', config['cpus'], '-m', config['memory_mib'],
        *storage,
        '-device', f'{nic_model},netdev=mgmt,mac=52:54:00:48:53:01', '-netdev', network,
        '-display', 'none',
        '-chardev', f'socket,id=console,path={work}/console.sock,server=on,wait=off,logfile={work}/serial.log,logappend=on',
        '-serial', 'chardev:console',
        '-qmp', f'unix:{work}/qmp.sock,server=on,wait=off', '-pidfile', work / 'qemu.pid', '-daemonize')
    mode_path = work / 'network-mode'
    mode_path.write_text('online-provisioning\n' if online else 'offline-pilot\n')
    # sudo boot must leave this non-secret mode indicator readable by the
    # workspace owner. The surrounding private directory stays mode 0700.
    mode_path.chmod(0o644)
    print('Started; management ports bind only to 127.0.0.1.', 'ONLINE PROVISIONING' if online else 'OFFLINE PILOT')


def ssh_args(work):
    config = pilot_configuration(work)
    ports = management_ports(config)
    trust = 'yes' if config.get('attach_seed') is False else 'accept-new'
    return ['ssh', '-p', str(ports['ssh']), '-i', str(work / 'id_ed25519'),
            '-o', 'IdentitiesOnly=yes', '-o', 'ForwardAgent=no', '-o', 'StrictHostKeyChecking='+trust,
            '-o', f'UserKnownHostsFile={work}/known_hosts', '-o', 'ConnectTimeout=10',
            'root@127.0.0.1']



def checkpoint(work, output):
    """Clone a stopped standalone appliance for installation/migration rollback."""
    if not output.is_absolute() or output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError('Use a new absolute checkpoint directory outside source')
    if (work / 'qmp.sock').exists():
        raise ValueError('Wait for clean shutdown and QEMU exit before checkpointing')
    configuration = work / 'pilot.json'
    if configuration.is_file() and any(json.loads(configuration.read_text()).get(name) for name in ('attach_backup_disk','attach_data_disk')):
        raise ValueError('Single-disk checkpoints cannot include attached backup or data disks')
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(work / 'disk.qcow2')]))
    if info.get('backing-filename') or info['format'] != 'qcow2':
        raise ValueError('Checkpoint requires a standalone QCOW2')
    if shutil.disk_usage(output.parent).free < info['virtual-size'] + 8 * 1024**3:
        raise ValueError('Reserve full virtual capacity plus 8 GiB for a checkpoint')
    owner = work.stat()
    output.mkdir(mode=0o700)
    run('qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', work / 'disk.qcow2', output / 'disk.qcow2')
    run('qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', work / 'disk.qcow2', output / 'disk.qcow2')
    for name in ('pilot.json', 'id_ed25519', 'id_ed25519.pub', 'known_hosts', 'seed.iso',
                 'root-password', 'heist.env', 'pilot-shutdown-proof.json'):
        source = work / name
        if source.is_file():
            shutil.copy2(source, output / name)
    # A failed convert/compare leaves a diagnostic directory, never a valid receipt.
    (output / 'checkpoint.json').write_text(json.dumps({
        'schema': 1, 'source': str(work), 'disk_content_comparison': 'PASSED',
        'virtual_disk_bytes': info['virtual-size'], 'production_accepted': False,
    }, indent=2) + '\n')
    for path in output.iterdir():
        if path.is_file():
            path.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(path, owner.st_uid, owner.st_gid)
    if os.geteuid() == 0:
        os.chown(output, owner.st_uid, owner.st_gid)
    print('Checkpoint verified. Clone it to a fresh workspace to restore; keep the failed workspace for diagnosis.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--image', type=Path, required=True)
    prep.add_argument('--sums', type=Path, required=True)
    prep.add_argument('--port-offset', type=int, default=0, help='Offset all loopback ports for concurrent isolated pilots')
    prep.add_argument('--memory-mib', type=int, default=36864)
    prep.add_argument('--cpus', type=int, default=12)
    boot = sub.add_parser('start')
    boot.add_argument('--online', action='store_true', help='Allow outbound NAT for provisioning; never run vulnerable guests in this mode')
    snapshot = sub.add_parser('checkpoint', help='Verified stopped-disk copy for installation/migration rollback')
    snapshot.add_argument('--output', type=Path, required=True)
    sub.add_parser('status')
    sub.add_parser('shutdown')
    sub.add_parser('provision-proxmox', help='Run the guest-only installer over SSH; reboot and repeat after the kernel stage')
    remote = sub.add_parser('ssh')
    remote.add_argument('remote_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if not args.work.is_absolute():
            raise ValueError('Use an absolute external private workspace')
        args.work = args.work.resolve()
        if args.work == ROOT or ROOT in args.work.parents:
            raise ValueError('Use an absolute external private workspace')
        if args.command == 'prepare':
            prepare(args.work, args.image.resolve(), args.sums.resolve(),
                    port_offset=args.port_offset, memory_mib=args.memory_mib, cpus=args.cpus)
        elif args.command == 'start':
            start(args.work, args.online)
        elif args.command == 'provision-proxmox':
            if (args.work / 'network-mode').read_text().strip() != 'online-provisioning':
                raise ValueError('OS provisioning requires an online boot; do not launch vulnerable scenarios')
            with (ROOT / 'tools/local/prepare-proxmox.sh').open('rb') as script:
                run(*ssh_args(args.work), 'bash -s', stdin=script)
        elif args.command == 'checkpoint':
            checkpoint(args.work, args.output)
        elif args.command == 'status':
            print(json.dumps(qmp(args.work, 'query-status')))
        elif args.command == 'shutdown':
            qmp(args.work, 'system_powerdown')
            print('Requested graceful shutdown; wait for QEMU to exit before copying disks.')
        else:
            raise SystemExit(subprocess.call(ssh_args(args.work) + args.remote_args))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
