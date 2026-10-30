"""Build a verified static UI artifact on a workstation, not the production host."""
import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from heist.ui_assets import digest, inspect_bundle, install_bundle

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development', action='store_true', help='Allow uncommitted preview source; this bundle cannot be used for a production rollout')
    parser.add_argument('--install-web-root', type=Path, help='Optionally install the built assets in a local web root')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Use a new output artifact path')
    dirty = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'])
    if dirty and not args.development:
        parser.error('Commit reviewed source before building a source-bound release')
    revision = 'development' if args.development else subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    if not shutil.which('npm'):
        parser.error('Build on a workstation with Node.js 24+ and npm; production does not need Node')
    subprocess.run(['npm', 'ci', '--ignore-scripts'], cwd=ROOT/'frontend', check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT/'frontend', check=True)
    dist = ROOT/'frontend/dist'
    entry = json.loads((dist/'.vite/manifest.json').read_text())['index.html']
    files = {str(path.relative_to(dist)): path.read_bytes() for path in (dist/'assets/ui').rglob('*') if path.is_file()}
    manifest = {'file': entry['file'], 'css': entry.get('css', []), 'source_commit': revision,
                'assets': {name: digest(body) for name, body in files.items()}}
    files['ui-manifest.json'] = json.dumps(manifest, sort_keys=True).encode()
    metadata = {'schema': 1, 'source_commit': revision, 'files': {name: digest(body) for name, body in files.items()}}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, body in {'metadata.json': json.dumps(metadata, sort_keys=True).encode(), **files}.items():
            member = tarfile.TarInfo(name);member.size = len(body);member.mode = 0o644
            archive.addfile(member, io.BytesIO(body))
    bundle = output.getvalue()
    inspect_bundle(bundle, revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bundle)
    if args.install_web_root:
        install_bundle(bundle, args.install_web_root, revision)
    print('Verified frontend artifact:', args.output)
    print('SHA256:', digest(bundle))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
