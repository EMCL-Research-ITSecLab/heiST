"""Guard the managed prediction job across legacy, packaged and domain layouts."""
from pathlib import Path
import shlex

LAYOUTS = (
    ('heist/platform/pools/prediction.py', 'heist.platform.pools.prediction'),
    ('heist/backend/pool_size_prediction.py', 'heist.backend.pool_size_prediction'),
    ('backend/pool_size_prediction.py', 'backend.pool_size_prediction'),
)


def prediction_cron(content, installation, marker):
    installation = Path(installation)
    chosen = next(((path, module) for path, module in LAYOUTS if (installation/path).is_file()), None)
    if chosen is None:
        if any(str(installation/path) in content or '-m '+module in content for path, module in LAYOUTS):
            raise RuntimeError('Prediction job refers to missing source; review the managed cron job')
        return content
    module = chosen[1]
    interpreter = shlex.quote(str(installation/'.venv/bin/python'))
    lines = []
    for line in content.splitlines():
        known = any(str(installation/path) in line or '-m '+name in line for path, name in LAYOUTS)
        if line.strip() and not line.lstrip().startswith('#') and known:
            fields = line.split(None, 6)
            if len(fields) != 7:
                raise RuntimeError('Unknown prediction cron format')
            command = fields[6]
            for path, name in LAYOUTS:
                script = str(installation/path)
                for python in ('/usr/bin/python3', str(installation/'.venv/bin/python')):
                    command = command.replace(python+' '+script, 'cd '+shlex.quote(str(installation))+' && '+interpreter+' -m '+module)
                if script in command:
                    raise RuntimeError('Unknown prediction interpreter; review the managed cron job')
                command = command.replace('-m '+name, '-m '+module)
            if 'HEIST_MAINTENANCE_GUARD' not in command:
                command = 'test ! -e '+shlex.quote(str(marker))+' && '+command+' # HEIST_MAINTENANCE_GUARD'
            line = ' '.join(fields[:6])+' '+command
        lines.append(line)
    return '\n'.join(lines)+'\n'
