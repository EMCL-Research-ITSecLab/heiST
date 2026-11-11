"""Source-bound administrator worker unit; checkpointed with host configuration."""
import json
from pathlib import Path

from .manifest import blob

UNIT='heist-administrator-worker.service'
PATH=Path('/etc/systemd/system')/UNIT


def enabled(plan):
    return any(m.identifier=='0013_administrator_requests' for m in getattr(plan,'migrations',()))


def files(adapter,target):
    body=blob(adapter.installation,target,'deploy/platform/systemd/'+UNIT).decode()
    body=body.replace('/root/heiST',str(adapter.installation))
    environment='Environment='+json.dumps('HEIST_BACKEND_ENV='+str(adapter.config.backend_env))+'\n'
    environment+='Environment='+json.dumps('HEIST_INTERNAL_RUNTIME='+str(adapter.state/'internal-runtime/current'))+'\n'
    if body.count('[Service]\n')!=1:raise ValueError('Worker service template is invalid')
    body=body.replace('[Service]\n','[Service]\n'+environment)
    return {PATH:(body.encode(),0o644)}
