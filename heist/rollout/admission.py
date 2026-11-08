"""Bind production admission to private source/configuration-specific evidence."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

CHECKS=frozenset(('baseline_restore','precommit_recovery','committed_upgrade',
    'newer_data_rollback','reboot','exercise_lifecycle','vpn_and_monitoring',
    'legacy_credentials','strict_tests','backup_transport'))


def configuration_fingerprint(config):
    values=asdict(config)
    # Avoid a circular checksum between the report and the file referring to it.
    for name in ('acceptance_receipt','acceptance_sha256'):values.pop(name,None)
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read_evidence(path,digest):
    path=Path(path)
    if (not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or re.fullmatch('[a-f0-9]{64}',digest or '') is None):
        raise RuntimeError('Require a private regular acceptance file and exact SHA256')
    parent=path.parent.stat()
    if parent.st_uid!=os.geteuid() or parent.st_mode & 0o077:
        raise RuntimeError('Acceptance evidence requires a private administrator-owned directory')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
                or info.st_mode & 0o077 or info.st_size>2*1024**2):
            raise RuntimeError('Acceptance evidence must be a bounded private regular file')
        body=stream.read(2*1024**2+1)
    if hashlib.sha256(body).hexdigest()!=digest:
        raise RuntimeError('Acceptance evidence checksum differs')
    result=json.loads(body)
    if not isinstance(result,dict):raise RuntimeError('Acceptance evidence must be an object')
    return result


def require(config,plan):
    if not config.acceptance_receipt or not config.acceptance_sha256:
        raise RuntimeError('Browser runtime requires source-bound production-clone acceptance; no maintenance was entered')
    report=read_evidence(config.acceptance_receipt,config.acceptance_sha256)
    target=plan.source if plan.rollback else plan.target
    baseline=plan.target if plan.rollback else plan.source
    if (report.get('schema')!=1 or report.get('kind')!='production-clone-upgrade'
            or report.get('source_commit')!=target or report.get('baseline_source')!=baseline
            or report.get('configuration_sha256')!=configuration_fingerprint(config)):
        raise RuntimeError('Acceptance does not bind this source, target and deployment configuration')
    evidence=report.get('evidence')
    if not isinstance(evidence,dict) or set(evidence)!=CHECKS:
        raise RuntimeError('Complete production-clone acceptance evidence is required')
    parent=Path(config.acceptance_receipt).parent
    for name,entry in evidence.items():
        if (not isinstance(entry,dict) or set(entry)!={'file','sha256'}
                or not isinstance(entry['file'],str)
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.json',entry['file']) is None):
            raise RuntimeError('Acceptance evidence must use explicit sibling JSON receipts')
        item=read_evidence(parent/entry['file'],entry['sha256'])
        if name=='strict_tests':
            counts=item.get('counts',{})
            if (item.get('commit')!=target or item.get('dirty') is not False
                    or item.get('returncode')!=0 or item.get('strict_skips') is not True
                    or type(counts.get('tests')) is not int or counts['tests']<=0
                    or any(type(counts.get(k)) is not int or counts[k]!=0
                           for k in ('failures','errors','skipped','expected_failures'))):
                raise RuntimeError('Require passing exact-source strict tests with zero skips')
        elif (item.get('passed') is not True or item.get('source_commit')!=target
                or item.get('baseline_source')!=baseline or item.get('check')!=name):
            raise RuntimeError('A required production-clone acceptance check has not passed: '+name)
    vms=report.get('vm_uuids')
    if not isinstance(vms,dict) or set(vms)!={'web','database','monitoring'}:
        raise RuntimeError('Acceptance must bind the three restored infrastructure VM identities')
    try:
        if any(not isinstance(value,str) or str(uuid.UUID(value))!=value for value in vms.values()):
            raise ValueError('UUID is not canonical')
    except (ValueError,AttributeError):
        raise RuntimeError('Acceptance VM identities are invalid') from None
    return report
