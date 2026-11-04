"""Run the privileged API with one Gunicorn process and a verified offline wheel.

Existing host dependencies remain in their original venv. The additional approved
Gunicorn wheel is installed separately, tied to the complete application source,
and ignored by older source after rollback. No production package download runs.
"""
import json
import os
from pathlib import Path
import re
import sys


def load_runtime(directory=None,source=None):
    from heist.runtime_bundle import digest
    root=Path(directory or os.environ.get('HEIST_INTERNAL_RUNTIME','/var/lib/heist/internal-runtime/current')).resolve(strict=True)
    source=Path(source) if source else Path(__file__).resolve().parents[2]
    value=json.loads((root/'metadata.json').read_text())
    if value.get('schema')!=1 or not re.fullmatch('[a-f0-9]{40}',value.get('source_commit','')):
        raise ValueError('Unknown internal runtime receipt')
    for name,expected in value['source_files'].items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or not name.startswith('heist/') or not name.endswith('.py'):
            raise ValueError('Unsafe runtime source path')
        target=source/path
        if target.is_symlink() or digest(target.read_bytes())!=expected:
            raise ValueError('Internal runtime belongs to different source')
    if 'heist/api/internal_serve.py' not in value['source_files']:
        raise ValueError('Internal entry point is not covered by its receipt')
    wheel=root/'gunicorn.whl'
    if wheel.is_symlink() or digest(wheel.read_bytes())!=value['wheel_sha256']:
        raise ValueError('Internal Gunicorn wheel checksum differs')
    sys.path.insert(0,str(wheel))


def options(values=None):
    values=os.environ if values is None else values
    host=values.get('BACKEND_HOST','10.0.0.1')
    from heist.security.tls import server_name
    server_name(host)
    port=values.get('BACKEND_PORT','8000')
    if not isinstance(port,str) or not port.isascii() or not port.isdigit() or not 1024<=int(port)<=65535:
        raise ValueError('Configure an unprivileged backend TCP port')
    host='['+host+']' if ':' in host else host
    return {'bind':host+':'+str(int(port)),'workers':1,'worker_class':'gthread','threads':4,
            'timeout':1900,'graceful_timeout':40,'keepalive':5,'accesslog':None,'errorlog':'-',
            'loglevel':'warning','umask':0o077,'preload_app':False,'forwarded_allow_ips':'',
            'certfile':values.get('HEIST_INTERNAL_CERTIFICATE','/etc/pve/local/pve-ssl.pem'),
            'keyfile':values.get('HEIST_INTERNAL_KEY','/etc/pve/local/pve-ssl.key')}


def main(argv=None):
    import argparse
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    from heist.environment import load_backend_env
    load_backend_env()
    load_runtime()
    from gunicorn.app.base import BaseApplication
    class Application(BaseApplication):
        def load_config(self):
            for key,value in options().items():
                self.cfg.set(key,value)

        def load(self):
            from heist.api.internal import create_app
            return create_app()
    Application().run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
