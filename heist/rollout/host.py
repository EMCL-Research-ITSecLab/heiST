"""Guard and translate the one managed prediction cron job across source layouts."""
from pathlib import Path
import shlex


def prediction_cron(content, installation, marker):
    installation = Path(installation)
    old = str(installation/'backend/pool_size_prediction.py')
    new = installation/'heist/backend/pool_size_prediction.py'
    interpreter = shlex.quote(str(installation/'.venv/bin/python'))
    lines = []
    for line in content.splitlines():
        if line.strip() and not line.lstrip().startswith('#') and any(value in line for value in (old, str(new), '-m heist.backend.pool_size_prediction')):
            fields = line.split(None, 6)
            if len(fields) != 7:
                raise RuntimeError('Unknown prediction cron format')
            command = fields[6]
            if new.is_file() and old in command:
                for python in ('/usr/bin/python3', str(installation/'.venv/bin/python')):
                    command = command.replace(python+' '+old, 'cd '+shlex.quote(str(installation))+' && '+interpreter+' -m heist.backend.pool_size_prediction')
                if old in command:
                    raise RuntimeError('Unknown prediction interpreter; review the managed cron job')
            elif not new.is_file() and Path(old).is_file():
                command = command.replace(interpreter+' -m heist.backend.pool_size_prediction', interpreter+' '+shlex.quote(old))
            if 'HEIST_MAINTENANCE_GUARD' not in command:
                command = 'test ! -e '+shlex.quote(str(marker))+' && '+command+' # HEIST_MAINTENANCE_GUARD'
            line = ' '.join(fields[:6])+' '+command
        lines.append(line)
    return '\n'.join(lines)+'\n'
