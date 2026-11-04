#!/usr/bin/env python3
"""Build a clean-commit offline CPython 3.12 Linux browser runtime from cached wheels."""
import argparse
import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from heist.runtime_bundle import MAX_BYTES, digest, inspect_bundle, wheel_identity


def build(repository, wheelhouse, output):
    repository, wheelhouse, output = Path(repository), Path(wheelhouse), Path(output)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repository), *args])
    if git('status', '--porcelain').strip():
        raise ValueError('Commit the complete source before building a release runtime')
    commit = git('rev-parse', 'HEAD').decode().strip()
    sources = {}
    for entry in git('ls-tree', '-r', '-z', commit, '--', 'heist/').split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        name = name.decode()
        if not name.endswith('.py'):
            continue
        if metadata.split()[0] not in (b'100644', b'100755'):
            raise ValueError('Runtime code must be regular tracked files')
        sources[name] = git('show', commit+':'+name)
    requirements = git('show', commit+':deploy/web/requirements.txt')
    files = {'source/'+name: body for name, body in sources.items()} | {'requirements.txt': requirements}
    for path in sorted(wheelhouse.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != '.whl':
            raise ValueError('Wheelhouse must contain only regular wheel files')
        if path.stat().st_size > MAX_BYTES or sum(map(len, files.values()))+path.stat().st_size > MAX_BYTES:
            raise ValueError('Runtime wheelhouse exceeds size limit')
        data = path.read_bytes()
        wheel_identity(path.name, data)
        files['wheels/'+path.name] = data
    metadata = {'schema': 1, 'source_commit': commit, 'python': 'cp312', 'platform': 'linux_x86_64',
                'files': {name: digest(body) for name, body in files.items()}}
    files['metadata.json'] = json.dumps(metadata, sort_keys=True).encode()
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name, data in sorted(files.items()):
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.mtime = len(data), 0o644, 0
                archive.addfile(item, io.BytesIO(data))
    result = buffer.getvalue()
    inspect_bundle(result, commit, source_files=sources, pinned_requirements=requirements)
    if git('status', '--porcelain').strip() or git('rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('Source changed during runtime build')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(result)
    return {'source_commit': commit, 'sha256': digest(result), 'bytes': len(result)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(ROOT, args.wheelhouse, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
