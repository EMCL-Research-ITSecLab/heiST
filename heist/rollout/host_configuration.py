"""Validate the complete host configuration checkpoint before recovery effects."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import tarfile

from heist.files import sha256, write_file

MAX_BYTES = 32*1024**2
MAX_FILE_BYTES = 8*1024**2


def inspect_checkpoint(path, expected, allowed, *, archive_sha256=None):
    path = Path(path)
    allowed = {str(Path(name)) for name in allowed}
    if not set(expected).issubset(allowed):
        raise RuntimeError('Host checkpoint contains an undeclared configuration path')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise RuntimeError('Invalid host configuration archive')
    if archive_sha256 is not None and sha256(path) != archive_sha256:
        raise RuntimeError('Host configuration archive checksum differs')
    values = {}
    # Bounded decompression also limits extended headers consumed by tarfile.
    import gzip
    with gzip.open(path, 'rb') as stream:
        expanded = stream.read(MAX_BYTES+1)
    if len(expanded) > MAX_BYTES:
        raise RuntimeError('Expanded host configuration exceeds its limit')
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for item in archive:
            relative = PurePosixPath(item.name)
            name = '/'+item.name
            if (not item.isfile() or relative.is_absolute() or '..' in relative.parts or
                    str(relative) != item.name or name not in expected or name in values or
                    not 0 <= item.size <= MAX_FILE_BYTES):
                raise RuntimeError('Unexpected host configuration member')
            with archive.extractfile(item) as stream:
                data = stream.read()
            if hashlib.sha256(data).hexdigest() != expected[name]:
                raise RuntimeError('Host configuration file checksum differs')
            values[name] = data
    if set(values) != set(expected):
        raise RuntimeError('Host configuration archive is incomplete')
    return values


def restore_files(values):
    # Inspect every destination before replacing the first file. PVE-managed
    # certificates are read-only platform state, never restored by this tool.
    pending = {}
    for name, data in values.items():
        path = Path(name)
        if path.is_file() and sha256(path) == hashlib.sha256(data).hexdigest():
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise RuntimeError('Symlink in host configuration recovery path')
        if path == Path('/etc/pve') or Path('/etc/pve') in path.parents:
            raise RuntimeError('Proxmox manages its own certificates and cluster configuration')
        if not path.parent.is_dir():
            raise RuntimeError('Host configuration recovery directory is missing')
        pending[path] = data
    for path, data in pending.items():
        write_file(path, data, mode=0o600)
