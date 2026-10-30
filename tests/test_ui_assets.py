"""Static releases fail closed before changing an existing web installation."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from heist.ui_assets import digest, inspect_bundle, install_bundle, verify_installation

COMMIT = 'a' * 40


def bundle(revision=COMMIT, asset='assets/ui/index-one.js', body=b'console.log("heiST")', extra=None):
    files = {asset: body}
    manifest = {'source_commit': revision, 'file': asset, 'css': [], 'assets': {asset: digest(body)}}
    files['ui-manifest.json'] = json.dumps(manifest).encode()
    metadata = {'schema': 1, 'source_commit': revision, 'files': {name: digest(data) for name, data in files.items()}}
    files['metadata.json'] = json.dumps(metadata).encode()
    files.update(extra or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


class UiAssetTests(unittest.TestCase):
    def test_exact_source_installs_and_owned_old_assets_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_bundle(bundle(), root, COMMIT)
            self.assertEqual(verify_installation(root, COMMIT)['source_commit'], COMMIT)
            (root/'uploads').mkdir()
            (root/'uploads/student.txt').write_text('preserve')
            install_bundle(bundle(asset='assets/ui/index-two.js'), root, COMMIT)
            self.assertFalse((root/'assets/ui/index-one.js').exists())
            self.assertEqual((root/'uploads/student.txt').read_text(), 'preserve')

    def test_wrong_source_and_development_bundles_are_rejected(self):
        for payload in (bundle('b'*40), bundle('development')):
            with self.assertRaisesRegex(ValueError, 'another source'):
                inspect_bundle(payload, COMMIT)

    def test_traversal_and_unlisted_members_are_rejected(self):
        for extra in ({'../escape': b'x'}, {'assets/ui/unlisted.js': b'x'}):
            with self.assertRaises(ValueError):
                inspect_bundle(bundle(extra=extra), COMMIT)

    def test_tampered_bundle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            inspect_bundle(bundle(extra={'assets/ui/index-one.js': b'changed'}), COMMIT)

    def test_local_changes_prevent_all_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_bundle(bundle(), root, COMMIT)
            manifest = (root/'ui-manifest.json').read_bytes()
            (root/'assets/ui/index-one.js').write_text('local changes')
            with self.assertRaisesRegex(ValueError, 'changed locally'):
                install_bundle(bundle(asset='assets/ui/index-two.js'), root, COMMIT)
            self.assertEqual((root/'ui-manifest.json').read_bytes(), manifest)
            self.assertFalse((root/'assets/ui/index-two.js').exists())

    def test_symlinks_cannot_escape_installation(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            (root/'assets').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                install_bundle(bundle(), root, COMMIT)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_fresh_installer_rejects_stale_or_modified_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_bundle(bundle(), root, COMMIT)
            with self.assertRaises(ValueError):
                verify_installation(root, 'b'*40)
            (root/'assets/ui/index-one.js').write_text('changed')
            with self.assertRaises(ValueError):
                verify_installation(root, COMMIT)


if __name__ == '__main__':
    unittest.main()
