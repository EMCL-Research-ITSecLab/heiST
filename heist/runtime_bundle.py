"""Inspect source-bound offline Python runtimes before deployment mutation."""
from email.parser import BytesParser
import hashlib
import gzip
import io
import json
from pathlib import PurePosixPath
import re
import tarfile
from zipfile import BadZipFile, ZipFile

MAX_BYTES = 128*1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def requirements(body):
    result = {}
    for line in body.decode('ascii').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+-]*)', line)
        if not match:
            raise ValueError('Runtime requirements must contain exact pins only')
        name = re.sub('[-_.]+', '-', match[1]).lower()
        if name in result:
            raise ValueError('Duplicate runtime dependency')
        result[name] = match[2]
    if not result or not {'gunicorn', 'pip'}.issubset(result):
        raise ValueError('Declare the approved Gunicorn runtime and pinned pip bootstrap')
    return result


def wheel_identity(name, data):
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', name):
        raise ValueError('Invalid wheel filename')
    if not (name.endswith('-py3-none-any.whl') or re.search(r'-cp312-cp312-(?:manylinux[A-Za-z0-9_.]*x86_64|linux_x86_64)\.whl\Z', name)):
        raise ValueError('Runtime wheel must target CPython 3.12 Linux x86_64 or pure Python')
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = [item for item in archive.infolist() if item.filename.endswith('.dist-info/METADATA')]
            if len(entries) != 1 or entries[0].file_size > 65536:
                raise ValueError('Wheel metadata is missing, duplicated or too large')
            metadata = BytesParser().parsebytes(archive.read(entries[0]))
    except BadZipFile:
        raise ValueError('Invalid wheel archive') from None
    name, version = metadata.get('Name'), metadata.get('Version')
    if not name or not version or len(metadata.get_all('Name')) != 1 or len(metadata.get_all('Version')) != 1:
        raise ValueError('Wheel identity is missing or duplicated')
    return re.sub('[-_.]+', '-', name).lower(), version


def safe_path(name):
    path = PurePosixPath(name)
    if not isinstance(name, str) or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('Unsafe runtime bundle path')
    if name in ('metadata.json', 'requirements.txt'):
        return name
    if name.startswith('source/heist/') and name.endswith('.py') and re.fullmatch('[A-Za-z0-9_./-]+', name):
        return name
    if name.startswith('wheels/') and len(path.parts) == 2 and re.fullmatch('[A-Za-z0-9_.+-]+', path.name):
        return name
    raise ValueError('Unexpected runtime bundle member')


class BoundedReader:
    def __init__(self, stream, maximum):
        self.stream, self.remaining = stream, maximum

    def read(self, size=-1):
        if size < 0 or size > self.remaining:
            raise ValueError('Expanded runtime stream exceeds size limit')
        data = self.stream.read(size)
        self.remaining -= len(data)
        return data


def inspect_bundle(data, expected_commit, *, source_files=None, pinned_requirements=None):
    if len(data) > MAX_BYTES:
        raise ValueError('Runtime bundle exceeds size limit')
    files, total = {}, 0
    compressed = gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb')
    with tarfile.open(fileobj=BoundedReader(compressed, MAX_BYTES+4*1024**2), mode='r|') as archive:
        for item in archive:
            safe_path(item.name)
            if not item.isfile() or item.name in files or len(files) >= 2048 or not 0 <= item.size <= MAX_BYTES:
                raise ValueError('Invalid or duplicate runtime member')
            total += item.size
            if total > MAX_BYTES:
                raise ValueError('Expanded runtime exceeds size limit')
            with archive.extractfile(item) as stream:
                files[item.name] = stream.read()
    if 'metadata.json' not in files or 'requirements.txt' not in files:
        raise ValueError('Runtime metadata or requirements missing')
    metadata = json.loads(files.pop('metadata.json'))
    if set(metadata) != {'schema', 'source_commit', 'python', 'platform', 'files'} or metadata['schema'] != 1:
        raise ValueError('Unsupported runtime metadata')
    if not re.fullmatch('[0-9a-f]{40}', metadata['source_commit']) or metadata['source_commit'] != expected_commit:
        raise ValueError('Runtime source commit differs')
    if metadata['python'] != 'cp312' or metadata['platform'] != 'linux_x86_64':
        raise ValueError('Unsupported runtime target')
    if set(files) != set(metadata['files']) or any(digest(body) != metadata['files'][name] for name, body in files.items()):
        raise ValueError('Runtime checksums do not cover the complete bundle')
    if pinned_requirements is not None and files['requirements.txt'] != pinned_requirements:
        raise ValueError('Runtime requirements differ from trusted source')
    source = {name.removeprefix('source/'): body for name, body in files.items() if name.startswith('source/')}
    if not source or 'heist/api/public/__init__.py' not in source or 'heist/api/serve.py' not in source:
        raise ValueError('Browser API source is missing')
    if source_files is not None and source != source_files:
        raise ValueError('Runtime code differs from trusted Git objects')
    for name, body in source.items():
        compile(body, name, 'exec')
    pins, seen = requirements(files['requirements.txt']), {}
    for name, body in files.items():
        if name.startswith('wheels/'):
            dependency, version = wheel_identity(PurePosixPath(name).name, body)
            if dependency in seen or pins.get(dependency) != version:
                raise ValueError('Unexpected, duplicate or unpinned runtime wheel')
            seen[dependency] = name
    if set(seen) != set(pins):
        raise ValueError('Runtime wheel set does not match pinned requirements')
    return metadata, files


def hashed_requirements(files):
    """Every pinned package has one verified wheel; pip must not access an index."""
    lines = []
    for name, version in sorted(requirements(files['requirements.txt']).items()):
        wheel = next(body for path, body in files.items() if path.startswith('wheels/') and wheel_identity(PurePosixPath(path).name, body)[0] == name)
        lines.append(f'{name}=={version} --hash=sha256:{digest(wheel)}')
    return '\n'.join(lines)+'\n'
