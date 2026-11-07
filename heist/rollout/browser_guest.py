"""Root-only web VM deployment agent, shared by updates and fresh provisioning.

The controller binds artifacts/configuration to trusted Git before invoking this
agent over verified SSH. Private settings arrive on stdin, never in argv. Every
mutation requires the persistent maintenance gate. No package index is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import subprocess
import sys

from heist.web_runtime import install, activate, verify, assert_directory
from heist.ui_assets import install_bundle, verify_installation
from heist.rollout.browser_configuration import serialize
from heist.rollout.web_proxy import render

MAINTENANCE=Path('/var/lib/heist/maintenance')
STATE=Path('/var/lib/heist-web')
CONFIG=Path('/etc/heist')
RUNTIME=Path('/opt/heist-web')
STATIC=Path('/var/www/heist-releases')
RECEIPT=Path('/var/lib/heist/browser-deployment.json')


def read_bundle(path,limit):
    path=Path(path)
    if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or
            not path.is_file() or path.stat().st_size>limit):
        raise RuntimeError('Browser artifact must be a bounded regular file without symlinks')
    with path.open('rb') as stream:
        data=stream.read(limit+1)
    if len(data)>limit:raise RuntimeError('Browser artifact exceeds its size limit')
    return data


def write(path,data,mode=0o600):
    import tempfile
    descriptor,temporary=tempfile.mkstemp(prefix='.heist-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data.encode() if isinstance(data,str) else data)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    finally:Path(temporary).unlink(missing_ok=True)


def account():
    try:value=pwd.getpwnam('heist-web')
    except KeyError:
        subprocess.run(['useradd','--system','--user-group','--home-dir',str(STATE),'--no-create-home',
                        '--shell','/usr/sbin/nologin','heist-web'],check=True,capture_output=True,timeout=30)
        value=pwd.getpwnam('heist-web')
    group=grp.getgrgid(value.pw_gid)
    primary_members=[entry.pw_name for entry in pwd.getpwall() if entry.pw_gid==value.pw_gid]
    if (value.pw_uid==0 or value.pw_uid>=1000 or value.pw_dir!=str(STATE) or
            value.pw_shell not in ('/usr/sbin/nologin','/bin/false') or group.gr_name!='heist-web' or
            any(member!='heist-web' for member in group.gr_mem) or
            primary_members!=['heist-web']):
        raise RuntimeError('An unexpected heist-web account already exists')
    return value


def migrate_media(legacy_root,data_root,user):
    from heist.rollout.image_checkpoint import copy_file
    from heist.files import sha256
    result={}
    for kind in ('avatars','challenge_images'):
        source=Path(legacy_root)/'uploads'/kind
        destination=data_root/'media'/kind
        if any(path.is_symlink() for path in (source,*source.parents,destination,*destination.parents)):
            raise RuntimeError('Media migration paths must not contain symlinks')
        destination.mkdir(mode=0o700,parents=True,exist_ok=True)
        for directory in (data_root/'media',destination):os.chown(directory,user.pw_uid,user.pw_gid)
        if not source.exists():continue
        if source.is_symlink():raise RuntimeError('Legacy media directory must not be a symlink')
        for path in source.iterdir():
            if path.is_symlink() or not path.is_file() or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:png|jpe?g|gif)',path.name,re.I) is None:
                raise RuntimeError('Reconcile unsupported legacy media before migration')
            item={'bytes':path.stat().st_size,'sha256':sha256(path)}
            target=destination/path.name
            if target.exists():
                if target.is_symlink() or sha256(target)!=item['sha256']:
                    raise RuntimeError('Legacy media conflicts with existing browser data')
            else:copy_file(path,target,item)
            os.chown(target,user.pw_uid,user.pw_gid);target.chmod(0o600)
            result[kind+'/'+path.name]=item
    return result


def install_guest(config):
    if os.geteuid()!=0 or MAINTENANCE.is_symlink() or not MAINTENANCE.is_file():
        raise RuntimeError('Web deployment requires root and persistent maintenance')
    commit=config['commit']
    if not isinstance(commit,str) or re.fullmatch('[a-f0-9]{40}',commit) is None:
        raise ValueError('Declare the exact reviewed source revision')
    environment=serialize(config['environment'])
    # Both archive verifiers run before changing accounts/configuration/services.
    from heist.runtime_bundle import inspect_bundle,digest,MAX_BYTES as runtime_limit
    from heist.ui_assets import inspect_bundle as inspect_ui,MAX_BYTES as ui_limit
    runtime=read_bundle(config['runtime_bundle'],runtime_limit)
    frontend=read_bundle(config['ui_bundle'],ui_limit)
    if digest(runtime)!=config['runtime_sha256'] or digest(frontend)!=config['ui_sha256']:
        raise RuntimeError('Transferred browser artifacts differ from the reviewed plan')
    inspect_bundle(runtime,commit)
    metadata,_=inspect_ui(frontend,commit)
    if metadata['schema']!=2:raise ValueError('A standalone browser bundle is required')
    settings=config['environment']
    if settings['HEIST_WEB_DATA_ROOT']!=str(STATE) or settings['HEIST_BACKEND_CA_FILE']!=str(CONFIG/'backend-ca.crt'):
        raise ValueError('Web role paths differ from the service confinement')
    expected={'heist-web.service','heist-artifacts.service'}
    if set(config['units'])!=expected:raise ValueError('Declare exactly the supported browser services')
    for unit in ('apache2','heist-web','heist-artifacts'):
        if subprocess.run(['systemctl','is-active','--quiet',unit],capture_output=True).returncode==0:
            raise RuntimeError('Quiesce browser services before deploying their runtime')
    sites=Path('/etc/apache2/sites-enabled')
    enabled=list(sites.iterdir())
    if any(not path.is_symlink() or path.name not in ('000-default.conf','default-ssl.conf','heist.conf') for path in enabled):
        raise RuntimeError('Reconcile unmanaged Apache sites before browser deployment')
    user=account()
    assert_directory(CONFIG);CONFIG.chmod(0o755)
    if STATE.is_symlink():raise RuntimeError('Browser data root must not be a symlink')
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chown(STATE,user.pw_uid,user.pw_gid);STATE.chmod(0o700)
    media=migrate_media(config['legacy_root'],STATE,user)
    install(runtime,RUNTIME,commit,config['runtime_sha256'])
    static=assert_directory(STATIC)/commit
    if static.exists():verify_installation(static,commit)
    else:install_bundle(frontend,static,commit)
    apache=render(config['apache_template'],web_root=str(static),certificate=config['certificate'],
                  certificate_key=config['certificate_key'],hostname=config['hostname'])
    write(CONFIG/'web.env',environment)
    write(CONFIG/'backend-ca.crt',config['backend_ca'],0o644)
    # No old worker may run against migrated SQL; the Python expiry timer replaces it.
    Path('/etc/cron.d/challenge_worker').unlink(missing_ok=True)
    for unit,body in config['units'].items():write(Path('/etc/systemd/system')/unit,body,0o644)
    write(Path('/etc/apache2/sites-available/heist.conf'),apache,0o644)
    modules=Path('/etc/apache2/mods-enabled')
    disabled=[path.stem for path in modules.glob('php*.load')]
    if (modules/'mpm_prefork.load').exists():disabled.append('mpm_prefork')
    if disabled:subprocess.run(['a2dismod','-f',*disabled],check=True,capture_output=True,timeout=30)
    subprocess.run(['a2enmod','mpm_event','ssl','headers','rewrite','proxy','proxy_http'],check=True,capture_output=True,timeout=30)
    for path in enabled:
        path.unlink()
    subprocess.run(['a2ensite','heist'],check=True,capture_output=True,timeout=30)
    subprocess.run(['apache2ctl','configtest'],check=True,capture_output=True,timeout=30)
    activate(RUNTIME,commit,config['runtime_sha256'])
    receipt={'schema':1,'commit':commit,'runtime_sha256':config['runtime_sha256'],
             'ui_sha256':config['ui_sha256'],'static_root':str(static),'media':media,
             'web_environment_sha256':hashlib.sha256(environment.encode()).hexdigest(),
             'apache_sha256':hashlib.sha256(apache.encode()).hexdigest()}
    write(RECEIPT,json.dumps(receipt,sort_keys=True)+'\n')
    subprocess.run(['systemctl','daemon-reload'],check=True,capture_output=True,timeout=30)
    # API health is checked behind maintenance. Artifact writers start only after
    # the controller's durable COMMITTED boundary and removal of the marker.
    subprocess.run(['systemctl','enable','heist-web','heist-artifacts'],check=True,capture_output=True,timeout=30)
    subprocess.run(['systemctl','start','heist-web','apache2'],check=True,capture_output=True,timeout=60)
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args(argv)
    result=install_guest(json.load(sys.stdin))
    print(json.dumps(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
