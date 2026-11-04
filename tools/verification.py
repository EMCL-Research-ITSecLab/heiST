"""Collect reproducible test evidence and audit the release test catalogue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def provenance(root=ROOT):
    return {'commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
            'dirty': bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']))}


def audit_catalogue(root=ROOT):
    value = json.loads((root/'verification/cases.json').read_text())
    if value.get('schema') != 1 or not isinstance(value.get('cases'), list):
        raise ValueError('Unsupported verification catalogue')
    identifiers, automated = set(), set()
    for case in value['cases']:
        if set(case) != {'id', 'area', 'mode', 'procedure', 'expected', 'evidence', 'sources'}:
            raise ValueError('Incomplete verification case')
        if case['id'] in identifiers or not case['expected'] or not case['procedure'] or not case['evidence']:
            raise ValueError('Duplicate or incomplete verification case')
        identifiers.add(case['id'])
        if case['mode'] not in ('automated', 'appliance', 'manual'):
            raise ValueError('Unknown case mode')
        for source in case['sources']:
            path = Path(source)
            if path.is_absolute() or '..' in path.parts or not (root/path).is_file():
                raise ValueError('Missing or unsafe verification source: '+source)
            if case['mode'] == 'automated':
                automated.add(source)
    missing = {str(path.relative_to(root)) for path in (root/'tests').glob('test_*.py')} - automated
    if missing:
        raise ValueError('Portable test modules missing from catalogue: '+', '.join(sorted(missing)))
    return value


def collect(suite, output, *, strict=False):
    output = Path(output).absolute()
    if output.exists():
        raise ValueError('Use a new evidence directory; previous evidence is immutable')
    output.mkdir(mode=0o700, parents=True)
    before = provenance()
    commands = {
        'python': [sys.executable, 'tools/check.py', '--report', str(output/'results.json')],
        'php': [sys.executable, 'tools/check.py', '--frontend', '--report', str(output/'results.json')],
        'ui': ['npm', '--prefix', 'frontend', 'run', 'check'],
        'browser': [sys.executable, 'tests/browser/ui_smoke.py'],
        'ui-build': ['npm', '--prefix', 'frontend', 'run', 'build'],
        'vpn': ['unshare', '--net', sys.executable, '-m', 'tests.integration.vpn.lifecycle'],
    }
    command = commands[suite]
    if strict and suite in ('python', 'php'):
        command.append('--fail-on-skip')
    started = time.monotonic()
    with (output/'output.log').open('wb') as log:
        os.fchmod(log.fileno(), 0o600)
        try:
            returncode = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=900).returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            log.write(('Verification command failed: '+type(error).__name__+'\n').encode())
            returncode = 1
    after = provenance()
    report = {'schema': 1, 'suite': suite, **before, 'source_unchanged': before == after,
              'command': command, 'returncode': returncode, 'strict': strict,
              'completed_at': datetime.now(timezone.utc).isoformat(),
              'duration_seconds': round(time.monotonic()-started, 3),
              'log_sha256': hashlib.sha256((output/'output.log').read_bytes()).hexdigest(),
              'artifacts': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file()}}
    from heist.files import write_json
    write_json(output/'evidence.json', report)
    print(json.dumps(report, indent=2))
    return returncode


def verify_evidence(directory, commit, *, require_strict=False):
    directory = Path(directory)
    result = json.loads((directory/'evidence.json').read_text())
    if result['commit'] != commit or result['dirty'] or not result['source_unchanged'] or result['returncode'] != 0:
        raise ValueError('Evidence is failing, dirty, changed during execution or from another revision')
    if hashlib.sha256((directory/'output.log').read_bytes()).hexdigest() != result['log_sha256']:
        raise ValueError('Evidence log checksum differs')
    required = {'output.log', 'results.json'} if result['suite'] in ('python', 'php') else {'output.log'}
    if set(result.get('artifacts', {})) != required:
        raise ValueError('Incomplete suite artifacts')
    for name, digest in result['artifacts'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Suite artifact checksum differs')
    if require_strict:
        if not result['strict']:
            raise ValueError('Strict prerequisite coverage was not requested')
        if result['suite'] in ('python', 'php'):
            counts = json.loads((directory/'results.json').read_text())['counts']
            if counts.get('skipped') or not counts.get('tests'):
                raise ValueError('Required tests were skipped or no tests ran')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('catalogue', help='Validate case completeness and automated module traceability')
    run = sub.add_parser('run', help='Execute an explicit local test suite and retain private evidence')
    run.add_argument('--suite', choices=('python', 'php', 'ui', 'ui-build', 'browser', 'vpn'), required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--strict', action='store_true')
    gate = sub.add_parser('verify-evidence', help='Verify one suite receipt; this is not whole-release approval')
    gate.add_argument('directory', type=Path)
    gate.add_argument('--commit', required=True)
    gate.add_argument('--strict', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'catalogue':
        value = audit_catalogue()
        print('Verified catalogue:', len(value['cases']), 'cases; every portable test module is mapped')
        return 0
    if args.action == 'verify-evidence':
        verify_evidence(args.directory, args.commit, require_strict=args.strict)
        print('Verified suite evidence; appliance/manual release gates remain separate')
        return 0
    return collect(args.suite, args.output, strict=args.strict)


if __name__ == '__main__':
    raise SystemExit(main())
