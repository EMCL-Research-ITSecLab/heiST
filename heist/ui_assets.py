"""Verify and install a source-bound, static frontend release; no Node runtime required."""
import argparse
import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile

MAX_BYTES = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def asset_path(name):
    if not isinstance(name, str):
        raise ValueError('Unsafe frontend asset path')
    path = PurePosixPath(name)
    if (not isinstance(name, str) or str(path) != name or '..' in path.parts or
            not (name=='index.html' or re.fullmatch(r'assets/logo/(?:logo_dark|logo_light|icon_dark)\.svg',name) or re.fullmatch(r'assets/ui/[a-zA-Z0-9_./-]+',name) or re.fullmatch(r'assets/(?:avatars|images)/[a-zA-Z0-9_.-]+\.(?:png|jpe?g|gif)',name))):
        raise ValueError('Unsafe frontend asset path')
    return name


class BoundedStream:
    def __init__(self,stream):
        self.stream=stream
        self.remaining=MAX_BYTES+4*1024**2

    def read(self,size):
        if size<0 or size>self.remaining:
            raise ValueError('Expanded frontend stream exceeds size limit')
        data=self.stream.read(size)
        self.remaining-=len(data)
        return data


def inspect_bundle(data, expected_commit=None):
    if len(data) > MAX_BYTES:
        raise ValueError('Frontend bundle exceeds the size limit')
    files = {}
    total = 0
    with tarfile.open(fileobj=BoundedStream(gzip.GzipFile(fileobj=io.BytesIO(data))), mode='r|') as archive:
        for member in archive:
            if member.name in ('metadata.json','ui-manifest.json') and member.size>512*1024:
                raise ValueError('Frontend metadata exceeds size limit')
            if not member.isfile() or member.name in files or member.size > MAX_BYTES or len(files) >= 1024:
                raise ValueError('Unsupported or duplicate frontend bundle member')
            if member.name not in ('metadata.json', 'ui-manifest.json'):
                asset_path(member.name)
            total += member.size
            if total > MAX_BYTES:
                raise ValueError('Expanded frontend bundle exceeds the size limit')
            with archive.extractfile(member) as source:
                files[member.name] = source.read()
    metadata = json.loads(files.pop('metadata.json'))
    if set(metadata) != {'schema', 'source_commit', 'files'} or metadata['schema'] not in (1,2):
        raise ValueError('Unsupported frontend bundle schema')
    if (metadata['schema']==2) != ('index.html' in files):
        raise ValueError('Standalone frontend requires its versioned index document')
    revision = metadata['source_commit']
    if expected_commit and revision != expected_commit:
        raise ValueError('Frontend bundle was built from another source commit')
    if revision != 'development' and not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Invalid frontend source commit')
    if set(files) != set(metadata['files']):
        raise ValueError('Frontend bundle manifest does not cover every file')
    for name, body in files.items():
        if digest(body) != metadata['files'][name]:
            raise ValueError('Frontend asset checksum differs')
    manifest = json.loads(files['ui-manifest.json'])
    if manifest['source_commit'] != revision:
        raise ValueError('Frontend entry manifest revision differs')
    assets = manifest['assets']
    if set(assets) != set(files) - {'ui-manifest.json'}:
        raise ValueError('Frontend entry manifest asset coverage differs')
    for name, value in assets.items():
        asset_path(name)
        if name not in files or digest(files[name]) != value:
            raise ValueError('Frontend entry asset checksum differs')
    for name in [manifest['file'], *manifest['css']]:
        if name not in assets:
            raise ValueError('Frontend entry references an unlisted asset')
    return metadata, files


def verify_installation(root, expected_commit):
    """Fail before provisioning when the workstation build is missing or stale."""
    root = Path(root).absolute()
    manifest = json.loads((root/'ui-manifest.json').read_text())
    if manifest.get('source_commit') != expected_commit:
        raise ValueError('Build and install the frontend bundle from this exact source commit first')
    assets = manifest['assets']
    if not assets or any(name not in assets for name in [manifest['file'], *manifest['css']]):
        raise ValueError('Incomplete frontend entry manifest')
    for name, expected in assets.items():
        asset_path(name)
        path = root/name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('Symlink in frontend installation path')
        if digest(path.read_bytes()) != expected:
            raise ValueError('Installed frontend checksum differs')
    return manifest


def atomic_write(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.ui-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_bundle(data, root, expected_commit=None):
    metadata, files = inspect_bundle(data, expected_commit)
    root = Path(root).absolute()
    previous = {}
    old_manifest = root/'ui-manifest.json'
    if old_manifest.is_file():
        previous = json.loads(old_manifest.read_text()).get('assets', {})
    for name in set(files) | set(previous):
        if name != 'ui-manifest.json':
            asset_path(name)
        path = root/name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('Symlink in frontend installation path')
        if name != 'ui-manifest.json' and path.exists():
            expected = previous.get(name) or metadata['files'].get(name)
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise ValueError('Installed frontend asset changed locally')
    for name in sorted(files, key=lambda name: name == 'ui-manifest.json'):
        path = root/name
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        atomic_write(path, files[name])
    for name in previous.keys() - files.keys():
        (root/name).unlink(missing_ok=True)
    return {'source_commit': metadata['source_commit'], 'files': len(files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'install'))
    parser.add_argument('--bundle', required=True, help='Bundle path or - for standard input')
    parser.add_argument('--commit')
    parser.add_argument('--web-root', type=Path)
    args = parser.parse_args(argv)
    data = sys.stdin.buffer.read(MAX_BYTES + 1) if args.bundle == '-' else Path(args.bundle).read_bytes()
    if args.action == 'install':
        if not args.web_root:
            parser.error('install requires --web-root')
        result = install_bundle(data, args.web_root, args.commit)
    else:
        result = inspect_bundle(data, args.commit)[0]
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
