"""Unprivileged image-transfer worker; external VM operations do not run here.

Each transfer has a stable server identity. Host intake is deliberately
idempotent: immutable chunks, verified normalization, a fixed storage name and a
unique database row allow safe transfer recovery. VM lifecycle journals have a
separate manual-review policy and are never replayed by this worker.
"""
import argparse
import os
from pathlib import Path
import time

from heist.files import write_json
from heist.api.public.errors import ApiError
from heist.api.public.internal_client import ImageRejected, InternalClient
from .ova import InvalidOva, inspect_envelope
from .uploads import UploadStore


def process(store,client,owner,identifier):
    with store.session(owner,identifier) as (directory,value):
        if value['state'] not in ('SEALED','PROCESSING'):
            return False
        if value.get('next_attempt',0)>store.clock():
            return False
        # Preserve the stable identity before any host request. A restarted
        # worker resumes this identity rather than registering a second image.
        value.update(state='PROCESSING',attempts=value.get('attempts',0)+1)
        write_json(directory/'metadata.json',value)
        try:
            inspect_envelope(directory/'payload.ova')
            remote=client.artifact_request(owner,identifier,'init',payload={key:value[key] for key in ('name','size','guest_os')})
            if remote.get('state') not in ('READY','SEALED','PROCESSING'):
                with (directory/'payload.ova').open('rb') as source:
                    index=0
                    while data:=source.read(store.CHUNK_BYTES):
                        client.artifact_request(owner,identifier,'chunk',index=index,data=data)
                        index+=1
                client.artifact_request(owner,identifier,'seal')
            result=client.artifact_request(owner,identifier,'publish',payload={'sha256':value['sha256']})
            artifact_id=result.get('artifact_id')
            if type(artifact_id) is not int or artifact_id<=0:
                raise ApiError('Host publication is not yet confirmed',503)
            value.update(state='READY',artifact_id=artifact_id,message='Image validated and available')
            value.pop('next_attempt',None)
            write_json(directory/'metadata.json',value)
            store.discard_payload(directory)
            return True
        except (InvalidOva,ImageRejected):
            value.update(state='FAILED',message='Image validation or publication was rejected. Check the format and whether its name already exists.')
            write_json(directory/'metadata.json',value)
            store.discard_payload(directory)
            return False
        except (ApiError,OSError):
            state='NEEDS_REVIEW' if value['attempts']>=10 else 'PROCESSING'
            value.update(state=state,message='Transfer interrupted; retained for retry' if state=='PROCESSING' else 'Repeated transfer failure requires administrator review',
                         next_attempt=store.clock()+min(3600,30*2**min(value['attempts'],7)))
            write_json(directory/'metadata.json',value)
            return False


def sweep(store,client):
    done=0
    for path in store.root.iterdir():
        if not path.name.isascii() or not path.name.isdigit() or path.is_symlink() or not path.is_dir():
            continue
        owner=int(path.name)
        if not 0<owner<2**63:
            continue
        store.expire(owner)
        for value in store.list(owner):
            try:
                done+=process(store,client,owner,value['id'])
            except BlockingIOError:
                continue
    return done


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    store=UploadStore(Path(os.environ.get('HEIST_WEB_DATA_ROOT','/var/lib/heist-web'))/'artifact-uploads')
    client=InternalClient.from_environment()
    try:
        while True:
            if not Path(os.environ.get('HEIST_WEB_MAINTENANCE_FILE','/run/heist-web-maintenance')).exists():
                sweep(store,client)
            if args.once:
                return 0
            time.sleep(10)
    finally:
        client.close()


if __name__=='__main__':
    raise SystemExit(main())
