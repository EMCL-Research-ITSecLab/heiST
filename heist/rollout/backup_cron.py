"""Migrate the legacy root database-backup schedule with reversible receipts."""
from pathlib import Path
import shlex
import subprocess

from heist.files import write_json


def read():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and 'no crontab for' in result.stderr:
        return None
    raise RuntimeError('Cannot inspect the root backup schedule')


def install(content):
    if content is None:
        arguments, payload = ['crontab', '-r'], None
    else:
        arguments, payload = ['crontab', '-'], content
    subprocess.run(arguments, input=payload, text=True, capture_output=True, check=True, timeout=30)
    if read() != content:
        raise RuntimeError('Root backup schedule installation was not confirmed')


def rewrite(content, installation, marker, state):
    if content is None:
        return None
    root = Path(installation)
    script = str(root/'setup/backup_db.py')
    lines = []
    for line in content.splitlines(keepends=True):
        if script not in line or line.lstrip().startswith('#'):
            lines.append(line)
            continue
        fields = line.split(None, 5)
        if len(fields) != 6:
            raise RuntimeError('Unknown legacy database backup schedule')
        words = shlex.split(fields[5])
        prefix = ['/usr/bin/echo', '-e', '\\n', '|']
        if words[:4] == prefix:
            words = words[4:]
        if words not in ([str(root/'.venv/bin/python3'), script, '>', '/dev/null'],
                         [str(root/'.venv/bin/python'), script, '>', '/dev/null']):
            raise RuntimeError('Unknown legacy database backup command; preserve it for review')
        command = ['-m', 'heist.maintenance.database', 'backup', '--config', str(root/'setup/.env'),
                   '--directory', '/var/backups/heist/database', '--state-dir', str(state)]
        managed = ('test ! -e '+shlex.quote(str(marker))+' && cd '+shlex.quote(str(root))+' && '+
                   shlex.join([str(root/'.venv/bin/python'), *command])+' > /dev/null')
        lines.append(' '.join(fields[:5])+' '+managed+'\n')
    return ''.join(lines)


def migrate(adapter, transaction):
    if not transaction.data.get('checkpoint_ready'):
        raise RuntimeError('Backup schedule migration requires a verified checkpoint')
    before = read()
    after = rewrite(before, adapter.installation, adapter.marker, adapter.state)
    receipt = {'before': before, 'after': after}
    write_json(Path(transaction.data['backup_directory'])/'root-crontab.json', receipt)
    transaction.save(backup_cron=receipt)
    if before != after:
        install(after)


def restore(transaction, checkpoint):
    saved = checkpoint.data.get('backup_cron')
    if saved is None:
        return
    desired = saved['before']
    current = read()
    own = transaction.data.get('backup_cron', saved)
    if current not in (own['before'], own['after'], desired):
        raise RuntimeError('Root backup schedule changed; preserve the operator edit')
    if current != desired:
        install(desired)
    transaction.save(resume_backup_cron=desired)


def verify(transaction, *, target):
    if 'resume_backup_cron' in transaction.data:
        expected = transaction.data['resume_backup_cron']
    elif 'backup_cron' in transaction.data:
        expected = transaction.data['backup_cron']['after' if target else 'before']
    else:
        return
    if read() != expected:
        raise RuntimeError('Root backup schedule differs from the deployment receipt')
