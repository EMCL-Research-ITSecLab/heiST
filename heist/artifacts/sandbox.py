"""Private mount/network/PID namespace for inspecting and normalizing VMDKs.

Invoked only by the privileged intake service with administrator-owned paths.
QEMU runs without root, capabilities, network or access to host configuration.
"""
import ctypes
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

MAX_REPORT = 1024**2


def mount(source, target, *, readonly=True, device=False):
    subprocess.run(['/usr/bin/mount', '--bind', str(source), str(target)], check=True, timeout=10, capture_output=True)
    flags = 'remount,bind,nosuid'+('' if device else ',nodev')+(',ro' if readonly else ',rw,noexec')
    subprocess.run(['/usr/bin/mount', '-o', flags, str(target)], check=True, timeout=10, capture_output=True)


def qemu(arguments, label):
    # Bound diagnostic output independently of converted disk size.
    previous = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_REPORT, previous[1]))
    try:
        with open('/output/'+label+'.json', 'wb') as output, open('/output/'+label+'.stderr', 'wb') as error:
            subprocess.run(['/usr/bin/qemu-img', *arguments], stdout=output, stderr=error,
                           check=True, timeout=900, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        path = Path('/output/'+label+'.json')
        if path.stat().st_size > MAX_REPORT:
            raise ValueError('Disk inspection response exceeds limit')
        return json.loads(path.read_bytes())
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, previous)


def inspect_disk(name, expected, allowed):
    value = qemu(['info', '--output=json', '--image-opts',
                  'driver=vmdk,file.driver=file,file.filename=/input/'+name], 'info')
    if not isinstance(value, dict) or value.get('format') != 'vmdk' or value.get('virtual-size') != expected:
        raise ValueError('VMDK content does not match its declared disk size')
    if value.get('backing-filename') or value.get('full-backing-filename') or value.get('encrypted'):
        raise ValueError('Backing files and encrypted disks are unsupported')
    data = value.get('format-specific', {}).get('data', {})
    if data.get('cid') is None or data.get('parent-cid') not in (None, 4294967295):
        raise ValueError('Invalid or dependent VMDK descriptor')
    extents = data.get('extents')
    if not isinstance(extents, list) or not 1 <= len(extents) <= 32:
        raise ValueError('Unsupported VMDK extent inventory')
    for item in extents:
        filename = item.get('filename')
        if filename not in {'/input/'+entry for entry in allowed}:
            raise ValueError('VMDK references a file outside its embedded disk set')
    return value


def run(root, inputs, outputs, specification):
    if os.geteuid() != 0:
        raise ValueError('Sandbox setup requires the isolated privileged intake service')
    root, inputs, outputs = Path(root), Path(inputs), Path(outputs)
    if any(not path.is_absolute() or path.is_symlink() for path in (root, inputs, outputs)):
        raise ValueError('Sandbox paths must be absolute private directories')
    subprocess.run(['/usr/bin/mount', '--make-rprivate', '/'], check=True, timeout=10, capture_output=True)
    root.chmod(0o755)
    for name in ('usr', 'input', 'output', 'dev'):
        (root/name).mkdir(mode=0o755)
    mount('/usr', root/'usr')
    for name in ('lib', 'lib64', 'bin', 'sbin'):
        source = Path('/')/name
        if source.is_symlink():
            (root/name).symlink_to(os.readlink(source))
        elif source.is_dir():
            (root/name).mkdir(mode=0o755)
            mount(source, root/name)
    for name in ('null', 'zero', 'urandom'):
        (root/'dev'/name).touch()
        mount('/dev/'+name, root/'dev'/name, readonly=False, device=True)
    mount(inputs, root/'input')
    mount(outputs, root/'output', readonly=False)
    # Modules are loaded before chroot. No /etc, /root, /home, /proc or host
    # writable directory is visible to the disk parser.
    os.chroot(root)
    os.chdir('/')
    resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (900, 900))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    limit = specification['maximum_output']
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'Cannot restrict disk worker privileges')
    os.setgroups([])
    os.setgid(specification['gid'])
    os.setuid(specification['uid'])
    allowed = [item['name'] for item in specification['disks']]
    result = []
    for index, item in enumerate(specification['disks']):
        inspect_disk(item['name'], item['capacity'], allowed)
        output = f'disk{index}.qcow2'
        with open('/output/convert.stderr', 'wb') as error:
            subprocess.run(['/usr/bin/qemu-img', 'convert', '-f', 'vmdk', '-O', 'qcow2',
                            '/input/'+item['name'], '/output/'+output], check=True, timeout=900,
                           stdout=subprocess.DEVNULL, stderr=error,
                           env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        result.append({'name': output, 'capacity': item['capacity']})
    print(json.dumps({'schema': 1, 'disks': result}))


if __name__ == '__main__':
    value = json.loads(Path(sys.argv[4]).read_text())
    run(sys.argv[1], sys.argv[2], sys.argv[3], value)
