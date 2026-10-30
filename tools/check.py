#!/usr/bin/env python3
"""Local checks. No infrastructure is provisioned and no dependencies are installed."""
import argparse
import json
from datetime import datetime, timezone
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend', action='store_true', help='PHP syntax plus existing PHPUnit suite (requires installed vendor/)')
    parser.add_argument('--frontend-database', action='store_true', help='Include container-backed PHP tests; requires isolated Docker and cached postgres:15')
    parser.add_argument('--function-trace', type=Path, help='Record function entry counts during Python tests; execution is not verification')
    parser.add_argument('--report', type=Path, help='Write a new private JSON result with source provenance')
    parser.add_argument('--fail-on-skip', action='store_true', help='Release gate: missing prerequisites fail coverage')
    args = parser.parse_args(argv)
    if args.function_trace and (args.function_trace.exists() or args.frontend):
        parser.error('Use a new function trace output path with the Python suite')
    if args.report and args.report.exists():
        parser.error('Use a new report path')
    started = time.monotonic()
    counts = {}
    failures = []
    skipped = []
    returncode = 0
    if args.frontend_database and not args.frontend:
        parser.error('--frontend-database requires --frontend')
    sys.path[:0] = [str(ROOT), str(ROOT / 'tools/local')]
    if args.frontend:
        php = shutil.which('php')
        runner = ROOT / 'webserver/html/vendor/bin/phpunit'
        if not php or not runner.is_file():
            parser.error('Frontend checks require PHP and existing Composer dependencies; see docs/TESTING.md')
        web = ROOT / 'webserver/html'
        for path in sorted(web.rglob('*.php')):
            if 'vendor' not in path.relative_to(web).parts:
                subprocess.run([php, '-l', str(path)], check=True, stdout=subprocess.DEVNULL)
        command = [php, str(runner), '--fail-on-warning', '--fail-on-deprecation', '--configuration', str(web / 'phpunit.xml')]
        if not args.frontend_database:
            command += ['--exclude-group', 'database']
        with tempfile.TemporaryDirectory(prefix='heist-php-results-') as temporary:
            junit = Path(temporary)/'results.xml'
            result = subprocess.run(command + ['--log-junit', str(junit)], cwd=web)
            returncode = result.returncode
            if junit.exists():
                root = ET.parse(junit).getroot()
                summary = root if root.get('tests') is not None else root.find('testsuite')
                counts = {name: int(summary.get(name, 0)) for name in ('tests', 'failures', 'errors', 'skipped')}
                skipped = [case.get('name', 'unknown') for case in root.iter('testcase') if case.find('skipped') is not None]
            else:
                returncode = returncode or 1
    else:
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py', top_level_dir=str(ROOT))
        identifiers = set()
        pending = [suite]
        while pending:
            item = pending.pop()
            if isinstance(item, unittest.TestSuite):
                pending.extend(item)
            else:
                identifiers.add(item.id())
        from tools.function_inventory import FunctionTrace, evaluate
        from contextlib import nullcontext
        with FunctionTrace() if args.function_trace else nullcontext() as trace:
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        if args.function_trace:
            from heist.files import write_json
            args.function_trace.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            mapping = ROOT/'verification/functions.json'
            verification = json.loads(mapping.read_text()) if mapping.exists() else {}
            excluded = [test.id() for test, _ in result.failures + result.errors + result.skipped + result.expectedFailures]
            passed = {name for name in identifiers if not any(item == name or item.startswith(name+' ') for item in excluded)}
            write_json(args.function_trace, {'schema': 1, 'calls': trace.calls, 'functions': evaluate(trace.calls, verification, passed_tests=passed)})
        counts = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures)}
        failures = [test.id() for test, _ in result.failures + result.errors]
        skipped = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
        returncode = 0 if result.wasSuccessful() else 1
    if args.fail_on_skip and (counts.get('skipped', 0) or counts.get('expected_failures', 0)):
        returncode = 1
    if args.report:
        from heist.files import write_json
        args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']))
        write_json(args.report, {'schema': 1, 'suite': 'php' if args.frontend else 'python', 'commit': commit, 'dirty': dirty,
            'completed_at': datetime.now(timezone.utc).isoformat(), 'duration_seconds': round(time.monotonic()-started, 3),
            'counts': counts, 'failures': failures, 'skipped': skipped, 'returncode': returncode,
            'strict_skips': args.fail_on_skip})
    if returncode:
        raise SystemExit(returncode)


if __name__ == '__main__':
    main()
