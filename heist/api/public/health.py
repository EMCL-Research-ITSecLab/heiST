"""Small proxy health endpoints; never create sessions or expose diagnostics."""
from pathlib import Path
import ipaddress

from flask import Blueprint, current_app, request
from .context import internal, repository

blueprint=Blueprint('health',__name__)


@blueprint.get('/health/live')
def live():
    return {'success':True,'status':'alive'}


@blueprint.get('/health/ready')
def ready():
    if Path(current_app.config['MAINTENANCE_FILE']).exists() and not ipaddress.ip_address(request.remote_addr).is_loopback:
        return {'success':False,'status':'maintenance'},503
    try:
        repository().call('web_disk_files',-1)
        result=internal().request('health')
        if result.get('status')!='ready':
            raise RuntimeError('Platform is not ready')
    except Exception:
        return {'success':False,'status':'not ready'},503
    return {'success':True,'status':'ready'}
