#!/usr/bin/env python3
"""Round-trip a synthetic read-only LVM-thin template in the isolated pilot.

Never starts a guest. Creates and removes only UUID-bound fixture VMs, an owned
loop-backed VG and a temporary storage registration. Keeps private receipts/logs.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
from rehearse_recovery import require_fixture
from heist.files import private_directory, write_json
from heist.maintenance.template_archive import create, inspect


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            value.update(block)
    return value.hexdigest()


def main():
    require_fixture()
    root = private_directory(Path('/root')/('heist-template-archive-'+uuid.uuid4().hex[:12]))
    identifiers = (900000510, 900000511)
    if any(Path(f'/etc/pve/qemu-server/{n}.conf').exists() for n in identifiers):
        raise RuntimeError('Fixture VM IDs already exist; reconcile the prior rehearsal')
    identity = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    vg, storage = 'heist_ro_'+suffix, 'heist-ro-'+suffix
    receipt = {'schema': 1, 'passed': False, 'pilot_only': True, 'vmids': identifiers,
               'uuid': identity, 'vg': vg, 'storage': storage, 'guest_started': False,
               'production_template_restore_accepted': False,
               'source_commit': subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()}
    loop = None
    registered = False
    log = (root/'commands.log').open('xb')
    def run(args):
        result = subprocess.run(args, capture_output=True, timeout=180)
        log.write(('$ '+' '.join(args)+'\n').encode()+result.stdout+result.stderr)
        log.flush()
        if result.returncode:raise RuntimeError('Fixture command failed; inspect '+str(root/'commands.log'))
        return result.stdout.decode().strip()
    try:
        backing = root/'loop.raw'
        with backing.open('xb') as stream:stream.truncate(1024**3)
        loop = run(['losetup','--find','--show',str(backing)])
        receipt['loop'] = loop
        write_json(root/'receipt.json',receipt)
        run(['pvcreate','--yes',loop])
        run(['vgcreate',vg,loop])
        run(['lvcreate','--type','thin-pool','-L','512M','-n','data',vg])
        run(['pvesm','add','lvmthin',storage,'--vgname',vg,'--thinpool','data','--content','images'])
        registered = True
        run(['qm','create',str(identifiers[0]),'--name','heist-readonly-roundtrip',
             '--memory','512','--cores','1','--smbios1','uuid='+identity,'--sata0',storage+':0.03125'])
        configuration = run(['qm','config',str(identifiers[0])])
        volume = next(line.split(': ',1)[1].split(',')[0] for line in configuration.splitlines() if line.startswith('sata0:'))
        device = run(['pvesm','path',volume])
        with open(device,'r+b',buffering=0) as stream:stream.write(bytes(range(256))*16384)
        expected = digest(device)
        run(['qm','template',str(identifiers[0])])
        configuration = run(['qm','config',str(identifiers[0])])
        base = next(line.split(': ',1)[1].split(',')[0] for line in configuration.splitlines() if line.startswith('sata0:'))
        device = Path(run(['pvesm','path',base]))
        assert device.parent.name == vg
        run(['lvchange','-a','y','-K',vg+'/'+device.name])
        template = inspect(identifiers[0],identity)
        stamp = datetime.now(timezone.utc).strftime('%Y_%m_%d-%H_%M_%S')
        archive = root/f'vzdump-qemu-{identifiers[0]}-{stamp}.vma.zst'
        receipt['archive'] = create(identifiers[0],identity,archive)
        assert inspect(identifiers[0],identity) == template
        run(['zstd','--quiet','--test',str(archive)])
        # qmrestore itself reads/extracts and checks the real compressed VMA.
        run(['qmrestore',str(archive),str(identifiers[1]),'--storage',storage])
        configuration = run(['qm','config',str(identifiers[1])])
        base = next(line.split(': ',1)[1].split(',')[0] for line in configuration.splitlines() if line.startswith('sata0:'))
        device = Path(run(['pvesm','path',base]))
        assert device.parent.name == vg
        run(['lvchange','-a','y','-K',vg+'/'+device.name])
        restored = inspect(identifiers[1],identity)
        assert len(restored.disks) == 1 and digest(restored.disks[0][1]) == expected
        assert digest(template.disks[0][1]) == expected
        receipt.update(passed=True, source_still_read_only=True, source_hash=expected,
                       restored_disk_hash_matches=True, restored_uuid_matches=True)
    finally:
        # Never force-stop or overwrite a different VM while cleaning a fixture.
        for identifier in reversed(identifiers):
            if Path(f'/etc/pve/qemu-server/{identifier}.conf').exists():
                configuration = run(['qm','config',str(identifier)])
                if 'uuid='+identity not in configuration:
                    raise RuntimeError('Fixture cleanup refused an unconfirmed VM identity')
                assert run(['qm','status',str(identifier)]) == 'status: stopped'
                run(['qm','destroy',str(identifier)])
        if registered:run(['pvesm','remove',storage])
        if loop:
            # The VG name is generated for this run and its only PV is our loop.
            records = run(['pvs','--noheadings','-o','pv_name','--select','vg_name='+vg]).split()
            if records:
                assert records == [loop]
                run(['vgremove','--yes',vg]);run(['pvremove','--yes',loop])
            run(['losetup','--detach',loop])
        receipt['fixture_resources_removed'] = True
        write_json(root/'receipt.json',receipt)
        log.close()
    print(json.dumps({'receipt':str(root/'receipt.json'),**receipt}))


if __name__ == '__main__':
    main()
