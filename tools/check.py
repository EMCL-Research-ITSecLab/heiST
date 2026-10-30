#!/usr/bin/env python3
"""Local checks. No infrastructure is provisioned and no dependencies are installed."""
import argparse
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
    args = parser.parse_args(argv)
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
        subprocess.run(command, cwd=web, check=True)
    else:
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py', top_level_dir=str(ROOT))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise SystemExit(1)


if __name__ == '__main__':
    main()
