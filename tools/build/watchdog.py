"""Package the off-host observer using only reviewed standard-library source."""
import argparse
from pathlib import Path
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[2]


def build(output):
    output = Path(output)
    if output.exists():
        raise ValueError('Use a new watchdog artifact path')
    with tempfile.TemporaryDirectory(prefix='heist-watchdog-') as directory:
        root = Path(directory)
        for name in ('heist/__init__.py', 'heist/monitoring/__init__.py', 'heist/remote.py',
                     'heist/monitoring/health.py', 'heist/monitoring/watchdog.py'):
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            # Empty package initializers prevent future app startup side effects.
            target.write_bytes(b'' if name.endswith('__init__.py') else (ROOT/name).read_bytes())
        (root/'__main__.py').write_text('from heist.monitoring.watchdog import main\nraise SystemExit(main())\n')
        zipapp.create_archive(root, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.output)


if __name__ == '__main__':
    main()
