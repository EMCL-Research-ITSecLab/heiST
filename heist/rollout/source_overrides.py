"""Capture explicitly reviewed legacy source differences for exact recovery."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess


def validate(values):
    if not isinstance(values, dict):
        raise ValueError('Reviewed source files must map tracked paths to SHA256')
    for name, digest in values.items():
        path=PurePosixPath(name) if isinstance(name,str) else None
        if (path is None or not path.parts or path.is_absolute() or '..' in path.parts or str(path)!=name
                or not (name=='bin/install' or (path.parts[0] in ('backend','monitoring','setup','heist')
                         and path.suffix in ('.py','.ps1','.sh')))
                or not isinstance(digest,str) or re.fullmatch('[a-f0-9]{64}',digest) is None):
            raise ValueError('Declare reviewed tracked source paths and exact SHA256 values')


def capture(root, values):
    """Return private bytes/modes after verifying the complete declared file set."""
    validate(values)
    root=Path(root)
    tracked=set(subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0'))
    result,modes={},{}
    for name,expected in values.items():
        path=root/name
        if (name not in tracked or path.is_symlink() or not path.is_file()
                or any(parent.is_symlink() for parent in path.parents)):
            raise RuntimeError('Reviewed source is not a regular tracked file: '+name)
        info=path.stat();mode=stat.S_IMODE(info.st_mode)
        if info.st_uid!=os.geteuid() or mode & 0o7022:
            raise RuntimeError('Reviewed source ownership/permissions are unsafe: '+name)
        if info.st_size>2*1024**2:
            raise RuntimeError('Reviewed source exceeds its limit: '+name)
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise RuntimeError('Reviewed source changed or exceeds its limit: '+name)
        result[name]=data.hex();modes[name]=mode
    return result,modes


def for_source(values, reviewed_commit, current_commit):
    """Legacy paths disappear after migration; keep their review for rollback."""
    validate(values)
    if values and (not isinstance(reviewed_commit,str) or re.fullmatch('[a-f0-9]{40}',reviewed_commit) is None):
        raise ValueError('Bind reviewed source files to their original commit')
    return values if current_commit==reviewed_commit else {}


def validate_web(values):
    if not isinstance(values,dict):raise ValueError('Reviewed web files must map paths to SHA256')
    for name,digest in values.items():
        path=PurePosixPath(name) if isinstance(name,str) else None
        if (path is None or not path.parts or path.is_absolute() or '..' in path.parts or str(path)!=name
                or '.env' in path.parts or path.parts[0] in ('vendor','uploads')
                or not isinstance(digest,str) or re.fullmatch('[a-f0-9]{64}',digest) is None):
            raise ValueError('Declare reviewed managed web source paths and SHA256 values')


def web_before(before,values):
    validate_web(values)
    if not set(values).issubset(before):
        raise RuntimeError('Reviewed web source is not tracked in the legacy release')
    return {**before,**values}
