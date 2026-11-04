"""Install an immutable offline browser runtime; activation is a separate action.

This module imports only the standard library and bundle verifier so a clean web
VM needs Python 3.12/venv, not an existing Flask or pip installation. The caller
must first bind the artifact hash and its code to trusted release Git objects.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

from heist.runtime_bundle import MAX_BYTES, digest, hashed_requirements, inspect_bundle


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C.UTF-8',
            'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'PIP_CONFIG_FILE': '/dev/null', 'PIP_NO_CACHE_DIR': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1'}


def file_hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory(root):
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        relative = str(path.relative_to(root))
        if '__pycache__' in path.parts or relative == 'installation.json':
            continue
        if path.is_symlink():
            links[relative] = os.readlink(path)
        elif path.is_file():
            files[relative] = file_hash(path)
    return {'files': files, 'links': links}


def verify(root, commit, artifact_sha256=None):
    if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Runtime commit must be a complete Git hash')
    root = Path(root)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError('Installed runtime path must not contain symlinks')
    value = json.loads((root/'installation.json').read_text())
    if value['source_commit'] != commit or (artifact_sha256 and value['artifact_sha256'] != artifact_sha256):
        raise ValueError('Installed runtime revision or artifact differs')
    if inventory(root) != value['inventory']:
        raise ValueError('Installed runtime files changed')
    return value


def assert_directory(path):
    path = Path(path).absolute()
    if '..' in path.parts or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Runtime root must not contain symlinks')
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o022:
        raise ValueError('Runtime root must be owned by its installer without group/other write access')
    return path


def install(data, root, commit, artifact_sha256):
    if not isinstance(artifact_sha256, str) or digest(data) != artifact_sha256:
        raise ValueError('Runtime artifact checksum differs from the deployment plan')
    _, files = inspect_bundle(data, commit)
    if sys.version_info[:2] != (3, 12) or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Browser runtime requires CPython 3.12 on Linux x86_64')
    root = assert_directory(root)
    versions = assert_directory(root/'versions')
    destination = versions/commit
    if destination.exists():
        return verify(destination, commit, artifact_sha256)
    with tempfile.TemporaryDirectory(prefix='.runtime-', dir=versions) as temporary:
        stage = Path(temporary)
        stage.chmod(0o755)
        for name, body in files.items():
            path = stage/name
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            path.write_bytes(body)
            path.chmod(0o644)
        locked = stage/'requirements-hashed.txt'
        locked.write_text(hashed_requirements(files))
        locked.chmod(0o644)
        subprocess.run([sys.executable, '-I', '-m', 'venv', str(stage/'venv')], env=environment(), check=True, timeout=120, capture_output=True, umask=0o022)
        python = stage/'venv/bin/python'
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-index', '--only-binary=:all:', '--no-deps',
                        '--require-hashes', '--find-links', str(stage/'wheels'), '-r', str(locked)],
                       env=environment(), check=True, timeout=180, capture_output=True, umask=0o022)
        subprocess.run([str(python), '-I', '-m', 'pip', 'check'], env=environment(), check=True, timeout=30, capture_output=True, umask=0o022)
        smoke = "import sys;sys.path.insert(0,sys.argv[1]);from heist.api.public import create_app;import gunicorn;create_app({'WEB_SESSION_SECRET':'a'*64},repository_factory=lambda:None,internal_client_factory=lambda:None)"
        subprocess.run([str(python), '-I', '-c', smoke, str(stage/'source')], env=environment(), check=True, timeout=30, capture_output=True, umask=0o022)
        # Relocate generated console scripts and activation helpers before hashing
        # the final runtime. The systemd entry point invokes bin/python directly.
        for path in (stage/'venv/bin').iterdir():
            if path.is_file() and not path.is_symlink():
                content = path.read_bytes()
                if b'\x00' not in content:
                    path.write_bytes(content.replace(str(stage).encode(), str(destination).encode()))
        config = stage/'venv/pyvenv.cfg'
        config.write_text(config.read_text().replace(str(stage), str(destination)))
        for directory in stage.rglob('*'):
            if directory.is_dir() and not directory.is_symlink():
                directory.chmod(0o755)
        receipt = {'schema': 1, 'source_commit': commit, 'artifact_sha256': artifact_sha256,
                   'inventory': inventory(stage)}
        path = stage/'installation.json'
        path.write_text(json.dumps(receipt, sort_keys=True)+'\n')
        path.chmod(0o644)
        for path in stage.rglob('*'):
            if path.is_symlink():
                continue
            if path.is_file():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        os.rename(stage, destination)
        descriptor = os.open(versions, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return verify(destination, commit, artifact_sha256)


def activate(root, commit, artifact_sha256):
    root = assert_directory(root)
    version = root/'versions'/commit
    receipt = verify(version, commit, artifact_sha256)
    current = root/'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('Current runtime must be an installer-managed symlink')
    temporary = root/'.current-new'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(Path('versions')/commit, target_is_directory=True)
    os.replace(temporary, current)
    descriptor = os.open(root, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'source_commit': receipt['source_commit'], 'artifact_sha256': receipt['artifact_sha256']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'activate', 'verify'))
    parser.add_argument('--root', type=Path, default=Path('/opt/heist-web'))
    parser.add_argument('--commit', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'install':
        data = args.bundle.read_bytes() if args.bundle else sys.stdin.buffer.read(MAX_BYTES+1)
        result = install(data, args.root, args.commit, args.sha256)
    elif args.action == 'activate':
        result = activate(args.root, args.commit, args.sha256)
    else:
        result = verify(args.root/'versions'/args.commit, args.commit, args.sha256)
    print(json.dumps({name: result[name] for name in ('source_commit', 'artifact_sha256')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
