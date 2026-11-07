#!/usr/bin/env python3
"""Stage a gated platform candidate on the isolated pilot and recover its baseline.

Never commits the candidate or opens its public service. Reuses only an explicit,
complete, verified disposable baseline checkpoint. The production admission guard
remains closed. Full recovery can take an hour: keep the frozen runner available.
"""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))

from rehearse_recovery import require_fixture
from heist.files import private_directory,sha256,write_file,write_json
from heist.rollout.config import Deployment
from heist.rollout.controller import Controller,Transaction
from heist.rollout.manifest import build_plan,revision
from heist.rollout.pve import PVE


class PlannedVerificationFailure(RuntimeError):
    pass


class PilotPlatform(PVE):
    def __init__(self,config,fingerprint,checkpoint):
        super().__init__(config,fingerprint)
        self.baseline=checkpoint

    def preflight(self,plan):
        require_fixture()
        if revision(self.installation,'HEAD')!='1bf6c026a9c6ce9ff6e00de9453496779c0e8043':
            raise RuntimeError('This rehearsal requires the known disposable legacy baseline')
        if plan.schema!=3 or plan.rollback:
            raise RuntimeError('This rehearsal requires a new immutable browser-runtime candidate')
        baseline=self.baseline
        if (baseline.data['phase']!='COMPLETE' or not baseline.data.get('checkpoint_ready') or
                baseline.data.get('failures') or baseline.plan.source!=plan.source):
            raise RuntimeError('Require the complete successfully recovered baseline checkpoint')
        # Exercise the common baseline checks without enabling production schema-3
        # admission. Immutable target validation still runs in full below.
        old=replace(plan,schema=1,target=plan.source,rollback=True,
                    ui_bundle=None,runtime_bundle=None,web_after=plan.web_before)
        super().preflight(old)
        if build_plan(self.installation,plan.target,plan.manifest_path,self.config_sha256,
                      plan.ui_bundle['path'],plan.runtime_bundle['path'])!=plan:
            raise RuntimeError('Candidate/configuration changed after planning')
        if self.protected_hashes(plan.protected_tables)!=baseline.data['protected_hashes']:
            raise RuntimeError('Protected fixture data changed since the baseline')
        for path,digest in baseline.data['preserved_files'].items():
            if sha256(path)!=digest:raise RuntimeError('Host configuration differs from the baseline')
        current=self.template_catalogue()
        if set(current)!=set(baseline.data['template_catalogue']):
            raise RuntimeError('Template catalogue differs from the baseline')
        # qmrestore legitimately changes generation metadata. Bind immutable VM
        # identities rather than requiring the pre-restore configuration digest.
        from heist.rollout.template_checkpoint import require_same_vm
        from types import SimpleNamespace
        for identifier,saved in baseline.data['template_catalogue'].items():
            if saved.get('absent'):
                if current[identifier]!=saved:raise RuntimeError('Previously absent template now exists')
            else:
                require_same_vm(self.template_configuration(SimpleNamespace(vmid=int(identifier))),saved)
        for item in baseline.data['snapshots'].values():
            path=Path(item['path'])
            if path.is_symlink() or path.stat().st_size!=item['bytes'] or sha256(path)!=item['sha256']:
                raise RuntimeError('A full baseline archive changed')

    def checkpoint(self,transaction):
        saved=self.baseline.data
        if self.protected_hashes(transaction.plan.protected_tables)!=saved['protected_hashes']:
            raise RuntimeError('Protected fixture data changed during quiescence')
        if transaction.data.get('generated',{})!=saved.get('generated',{}):
            raise RuntimeError('Generated host metadata differs from the baseline')
        directory=private_directory(Path(self.config.backup_directory)/transaction.path.name)
        transaction.save(backup_directory=str(directory),reused_checkpoint=self.baseline.path.name)
        # Keep the verified baseline immutable, including its private source and
        # configuration archives. New credentials/artifacts use this transaction.
        for name in ('source.bundle','host-configuration.tar.gz'):
            shutil.copyfile(Path(saved['backup_directory'])/name,directory/name)
            (directory/name).chmod(0o600)
        fields=('snapshots','template_catalogue','image_checkpoint','database_backup',
                'internal_runtime','absent_host_files','preserved_files','host_configuration_sha256')
        transaction.save(**{key:saved[key] for key in fields if key in saved})
        from heist.rollout.identifiers import preserve
        transaction.save(id_watermarks=preserve(self.database,self.state/'id-watermarks.json'))
        from heist import ui_assets,runtime_bundle
        for key,filename,verifier in (('ui_bundle','frontend.tar.gz',ui_assets.inspect_bundle),
                                       ('runtime_bundle','web-runtime.tar.gz',runtime_bundle.inspect_bundle)):
            artifact=getattr(transaction.plan,key)
            data=Path(artifact['path']).read_bytes()
            if ui_assets.digest(data)!=artifact['sha256']:raise RuntimeError('Reviewed artifact changed')
            verifier(data,transaction.plan.target)
            write_file(directory/filename,data)
            transaction.save(**{key+'_checkpoint':str(directory/filename)})
        write_json(directory/'checkpoint.json',transaction.data)

    def verify(self,transaction,*,target):
        super().verify(transaction,target=target)
        if target:
            transaction.save(target_verified=True)
            raise PlannedVerificationFailure('Expected pilot fault after target verification, before commit')


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--checkpoint',required=True,type=Path)
    parser.add_argument('--target',required=True)
    parser.add_argument('--manifest',default='releases/0.4.0-rc.1.json')
    parser.add_argument('--ui-bundle',required=True,type=Path)
    parser.add_argument('--runtime-bundle',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    require_fixture()
    if args.output.exists():raise ValueError('Use a new receipt path')
    config=Deployment.load(args.config)
    plan=build_plan(config.installation,args.target,args.manifest,sha256(args.config),args.ui_bundle,args.runtime_bundle)
    adapter=PilotPlatform(config,sha256(args.config),Transaction.load(args.checkpoint))
    controller=Controller(config.state_directory,adapter)
    prior={p.name for p in (adapter.state/'transactions').iterdir()}
    try:
        controller.apply(plan)
    except PlannedVerificationFailure:
        pass
    except BaseException:
        # The controller owns recovery and durable maintenance. Do not reopen
        # public access or try an additional restore outside its journal.
        raise
    else:raise AssertionError('The candidate must not reach its public commit boundary')
    created={p.name for p in (adapter.state/'transactions').iterdir()}-prior
    if len(created)!=1:raise RuntimeError('Cannot identify the rehearsal transaction')
    transaction=Transaction.load(adapter.state/'transactions'/created.pop())
    if (transaction.data['phase']!='ROLLED_BACK' or not transaction.data.get('target_verified') or
            not transaction.data.get('recovery_committed') or adapter.marker.exists()):
        raise AssertionError('Target verification or complete baseline recovery did not finish')
    failures=transaction.data.get('failures',[])
    if len(failures)!=1 or failures[0]['type']!='PlannedVerificationFailure':
        raise AssertionError('Unexpected failure in the native target rehearsal')
    receipt={'source_commit':plan.target,'baseline_source':plan.source,'transaction':transaction.path.name,
             'target_verified':True,'expected_precommit_failure':True,'baseline_recovered':True,
             'candidate_committed':False,'whole_platform_upgrade_approved':False}
    write_json(args.output,receipt)
    print(json.dumps(receipt))


if __name__=='__main__':
    main()
