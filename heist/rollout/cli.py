"""Plan, apply and recover pinned heiST releases during scheduled maintenance."""
import argparse
import json
import logging
from pathlib import Path
import sys

from heist.files import maintenance_lock, sha256, write_json
from .config import Deployment
from .controller import Controller, Transaction
from .manifest import Plan, build_plan


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','apply','status','resume','rollback','adopt-task','retry-task'))
    parser.add_argument('--config',type=Path,required=True,help='Reviewed deployment JSON; no credentials in this file')
    parser.add_argument('--target',help='Already fetched immutable commit, tag or branch')
    parser.add_argument('--manifest',default='releases/0.2.0.json')
    parser.add_argument('--plan',type=Path,help='Reviewed plan file to apply')
    parser.add_argument('--output',type=Path,help='Save a plan for later review/application')
    parser.add_argument('--transaction',help='Completed transaction to roll back')
    parser.add_argument('--confirm-version',help='Authorize reverting data written since this release')
    parser.add_argument('--task', help='Journalled task key to reconcile')
    parser.add_argument('--upid', help='Verified Proxmox task identity to adopt')
    parser.add_argument('--confirm-request', help='Exact request SHA256 from the transaction journal')
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    configuration=Deployment.load(args.config)
    fingerprint=sha256(args.config)
    state=Path(configuration.state_directory)
    if args.action=='plan':
        if not args.target:parser.error('plan requires --target')
        plan=build_plan(configuration.installation,args.target,args.manifest,fingerprint)
        if args.output:
            if args.output.exists():parser.error('Use a new plan output path')
            write_json(args.output,plan.to_dict())
        print(json.dumps(plan.to_dict(),indent=2));return 0
    if args.action=='status':
        data={name:json.loads((state/(name+'.json')).read_text()) if (state/(name+'.json')).exists() else None
            for name in ('installed','active')}
        data['transactions']=[]
        for path in sorted((state/'transactions').glob('*/transaction.json')):
            transaction=json.loads(path.read_text())
            data['transactions'].append({'id':path.parent.name,'phase':transaction['phase'],
                'version':transaction['plan']['version'],'committed':transaction['committed']})
        print(json.dumps(data,indent=2));return 0
    from .pve import PVE
    operations=PVE(configuration,fingerprint)
    controller=Controller(state,operations)
    if args.action in ('adopt-task', 'retry-task'):
        if not args.task or not args.confirm_request:
            parser.error('Task reconciliation requires --task and --confirm-request')
        if args.action == 'adopt-task' and not args.upid:
            parser.error('adopt-task requires --upid')
        with maintenance_lock(state):
            pointer = json.loads((state/'active.json').read_text())['transaction']
            if pointer in ('.', '..') or Path(pointer).name != pointer:
                parser.error('Invalid transaction pointer')
            active = Transaction.load(state/'transactions'/pointer)
            if active.plan.config_sha256 != fingerprint:
                parser.error('Restore the transaction deployment configuration')
            operations.tasks.reconcile(active, args.task, args.confirm_request,
                upid=args.upid, retry=args.action == 'retry-task')
        print('Task reconciliation recorded; inspect status, then resume.')
        return 0
    if args.action=='apply':
        if not args.plan:parser.error('apply requires a previously reviewed --plan')
        plan=Plan.from_dict(json.loads(args.plan.read_text()))
        if plan.config_sha256!=fingerprint:parser.error('Deployment configuration changed after planning')
        transaction=controller.apply(plan)
    elif args.action=='resume':
        pointer=json.loads((state/'active.json').read_text())['transaction']
        if Path(pointer).name!=pointer:parser.error('Invalid transaction pointer')
        active=Transaction.load(state/'transactions'/pointer)
        if active.plan.config_sha256!=fingerprint:parser.error('Restore the deployment configuration used by this transaction')
        transaction=controller.resume()
    else:
        if not args.transaction or not args.confirm_version:parser.error('rollback requires --transaction and --confirm-version')
        transaction=controller.rollback(args.transaction,confirm_version=args.confirm_version)
    recovered = transaction.data['phase'] == 'ROLLED_BACK'
    print(json.dumps({'transaction': transaction.path.name, 'phase': transaction.data['phase'],
        'commit': transaction.plan.source if recovered else transaction.plan.target,
        'version': transaction.plan.source_version if recovered else transaction.plan.version}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
