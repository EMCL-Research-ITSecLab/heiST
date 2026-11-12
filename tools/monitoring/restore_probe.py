"""Restore one verified backup into two network-isolated disposable databases."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from tools.testing.postgres import IMAGE


def verify(directory):
    directory=Path(directory)
    path=directory/'database.backup'
    metadata=json.loads((directory/'source-metadata.json').read_text())
    created=datetime.fromisoformat(metadata['created_at'])
    if created.tzinfo is None or not -30 <= (datetime.now(timezone.utc)-created).total_seconds() <= 1800:
        raise ValueError('Source backup is stale or has an invalid clock')
    body=path.read_bytes()
    if len(body)!=metadata['bytes'] or hashlib.sha256(body).hexdigest()!=metadata['sha256']:
        raise ValueError('Source backup checksum differs')
    if os.geteuid()!=0:raise ValueError('Require local container privileges')
    name='heist-delivery-'+uuid.uuid4().hex[:12]
    steps=dict.fromkeys(('source_checksum','restore','application_query','corruption_rejected','recovery','cleanup'),False)
    steps['source_checksum']=True
    log=directory/'restore.log'
    with log.open('xb') as output:
        os.fchmod(output.fileno(),0o600)
        def run(args,*,input=None,check=True):
            return subprocess.run(args,input=input,stdout=output,stderr=output,check=check,timeout=120)
        def exec(*args,**kwargs):return run(['docker','exec','-i',name,*args],**kwargs)
        def counts(database):
            sql="SELECT (SELECT count(*) FROM public.users),(SELECT count(*) FROM public.challenge_templates),(SELECT count(*) FROM public.training_preferences),(SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='api'),(SELECT count(*) FROM public.users u LEFT JOIN public.training_preferences p ON p.user_id=u.id WHERE p.user_id IS NULL)"
            result=subprocess.check_output(['docker','exec',name,'psql','-U','postgres','-d',database,'-At','-c',sql],stderr=output,timeout=30)
            values=[int(v) for v in result.decode().strip().split('|')]
            if not (values[0]>0 and values[1]>0 and values[2]==values[0] and values[3]>20 and values[4]==0):
                raise RuntimeError('Restored application integrity query failed')
            return values
        try:
            run(['docker','run','--pull','never','--rm','--detach','--name',name,'--network','none',
                 '--memory','1536m','--cpus','2','--tmpfs','/var/lib/postgresql/data:rw,nosuid,size=1g',
                 '-e','POSTGRES_HOST_AUTH_METHOD=trust',IMAGE,'-c','listen_addresses='])
            for _ in range(60):
                if exec('pg_isready','-U','postgres',check=False).returncode==0:break
                time.sleep(1)
            else:raise RuntimeError('Disposable database did not start')
            def restore(database,data,check=True):
                return exec('pg_restore','--single-transaction','--exit-on-error','--no-owner','--no-acl','-U','postgres','-d',database,input=data,check=check)
            exec('createdb','-U','postgres','before')
            restore('before',body);steps['restore']=True
            before=counts('before');steps['application_query']=True
            bad=restore('before',body[:48],check=False)
            steps['corruption_rejected']=bad.returncode!=0 and counts('before')==before
            exec('createdb','-U','postgres','recovered')
            restore('recovered',body);steps['recovery']=counts('recovered')==before
        finally:
            run(['docker','rm','--force',name],check=False)
            steps['cleanup']=subprocess.run(['docker','inspect',name],capture_output=True).returncode!=0
    result={'steps':steps,'source_sha256':metadata['sha256'],'scope':'production archive restored locally; production database unchanged'}
    (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    if not all(steps.values()):raise RuntimeError('Restore verification failed; inspect private report')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    print(json.dumps(verify(parser.parse_args().directory)))
