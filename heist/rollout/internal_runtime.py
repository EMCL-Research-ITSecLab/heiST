"""Checkpoint and restore the selected immutable privileged WSGI runtime."""
import json
import os
from pathlib import Path
import re

from heist.files import fsync_directory,sha256


def paths(root,snapshot):
    if snapshot is None:return []
    target=snapshot.get('target')
    if not isinstance(target,str) or re.fullmatch(r'versions/[a-f0-9]{40}',target) is None:
        raise RuntimeError('Unknown internal runtime checkpoint target')
    version=Path(root)/target
    files=[version/'metadata.json',version/'gunicorn.whl']
    if any(path.is_symlink() or any(parent.is_symlink() for parent in path.parents) for path in files):
        raise RuntimeError('Symlink in internal runtime checkpoint path')
    return files


def validate_current(root):
    """Check existing selection without creating directories or changing files."""
    root=Path(root)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise RuntimeError('Symlink in internal runtime root')
    current=root/'current'
    if current.exists() and not current.is_symlink():
        raise RuntimeError('Internal runtime selection is not a managed symlink')
    if current.is_symlink():paths(root,{'target':os.readlink(current)})


def capture(root):
    root=Path(root);current=root/'current'
    validate_current(root)
    if not current.exists() and not current.is_symlink():return None
    if not current.is_symlink():raise RuntimeError('Internal runtime selection is not a managed symlink')
    value={'target':os.readlink(current)}
    files=paths(root,value)
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise RuntimeError('Internal runtime checkpoint is incomplete')
    value['files']={str(path):sha256(path) for path in files}
    return value


def select(root,snapshot):
    root=Path(root)
    validate_current(root)
    if not root.exists() and snapshot is None:return
    from heist.web_runtime import assert_directory
    assert_directory(root)
    current=root/'current'
    if current.exists() and not current.is_symlink():raise RuntimeError('Unknown internal runtime selection')
    if current.is_symlink():paths(root,{'target':os.readlink(current)})
    if snapshot is None:
        current.unlink(missing_ok=True);fsync_directory(root);return
    expected=paths(root,snapshot)
    if set(snapshot.get('files',{}))!={str(path) for path in expected}:
        raise RuntimeError('Incomplete internal runtime checkpoint inventory')
    if any(path.is_symlink() or sha256(path)!=snapshot['files'][str(path)] for path in expected):
        raise RuntimeError('Internal runtime recovery bytes differ from the checkpoint')
    metadata=json.loads(expected[0].read_text())
    if metadata.get('source_commit')!=snapshot['target'].split('/')[1]:
        raise RuntimeError('Internal runtime receipt revision differs')
    temporary=root/'.current-restore'
    temporary.unlink(missing_ok=True);temporary.symlink_to(snapshot['target'],target_is_directory=True)
    os.replace(temporary,current);fsync_directory(root)
