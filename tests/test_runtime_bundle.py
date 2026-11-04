"""Offline artifacts bind both executable source and every dependency to a release."""
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from heist.runtime_bundle import BoundedReader, digest, hashed_requirements, inspect_bundle, wheel_identity
from heist.web_runtime import activate, public_interpreter, verify

COMMIT = 'a'*40
SOURCES = {'heist/api/public/__init__.py': b'def create_app(): pass\n', 'heist/api/serve.py': b'pass\n'}
REQUIREMENTS = b'gunicorn==26.2.0\npip==24.0\n'


def wheel(name='gunicorn', version='26.2.0'):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr(ZipInfo(name+'-'+version+'.dist-info/METADATA', (1980,1,1,0,0,0)), 'Name: '+name+'\nVersion: '+version+'\n')
    return stream.getvalue()


def bundle(change=None, extras=()):
    files = {'source/'+name: body for name, body in SOURCES.items()} | {'requirements.txt': REQUIREMENTS,
            'wheels/gunicorn-26.2.0-py3-none-any.whl': wheel(),
            'wheels/pip-24.0-py3-none-any.whl': wheel('pip', '24.0')}
    if change:
        change(files)
    metadata = {'schema': 1, 'source_commit': COMMIT, 'python': 'cp312', 'platform': 'linux_x86_64',
                'files': {name: digest(data) for name, data in files.items()}}
    files['metadata.json'] = json.dumps(metadata).encode()
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in [*files.items(), *extras]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return result.getvalue()


class RuntimeBundleTests(unittest.TestCase):
    def test_exact_source_and_wheels_produce_hash_locked_offline_requirements(self):
        _, files = inspect_bundle(bundle(), COMMIT, source_files=SOURCES, pinned_requirements=REQUIREMENTS)
        self.assertEqual(hashed_requirements(files), 'gunicorn==26.2.0 --hash=sha256:'+digest(wheel())+'\npip==24.0 --hash=sha256:'+digest(wheel('pip', '24.0'))+'\n')
        with self.assertRaises(ValueError):
            inspect_bundle(bundle(), 'b'*40)
        with self.assertRaises(ValueError):
            inspect_bundle(bundle(), COMMIT, pinned_requirements=b'gunicorn==99\n')

    def test_correct_internal_hashes_cannot_disguise_altered_git_source(self):
        def alter(files):
            files['source/heist/api/serve.py'] = b'print("tampered")\n'
        with self.assertRaisesRegex(ValueError, 'trusted Git'):
            inspect_bundle(bundle(alter), COMMIT, source_files=SOURCES)
        with self.assertRaises(ValueError):
            inspect_bundle(bundle(extras=[('source/heist/api/serve.py', b'pass')]), COMMIT)
        with self.assertRaises(ValueError):
            inspect_bundle(bundle(extras=[('../escape.py', b'pass')]), COMMIT)

    def test_missing_unpinned_duplicate_and_wrong_platform_wheels_fail(self):
        for change in (
            lambda files: files.pop('wheels/gunicorn-26.2.0-py3-none-any.whl'),
            lambda files: files.update({'wheels/gunicorn-99-py3-none-any.whl': wheel(version='99')}),
            lambda files: files.update({'wheels/gunicorn-26.2.0-1-py3-none-any.whl': wheel()}),
            lambda files: files.update({'requirements.txt': b'gunicorn>=26\n'}),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect_bundle(bundle(change), COMMIT)
        for name in ('gunicorn-26-cp312-cp312-macosx_10_9_x86_64.whl', 'gunicorn-26-cp311-cp311-manylinux2014_x86_64.whl'):
            with self.assertRaises(ValueError):
                wheel_identity(name, wheel())

    def test_pax_size_expansion_is_bounded_before_tar_parser_allocates_payload(self):
        reader = BoundedReader(io.BytesIO(b'1234'), 4)
        self.assertEqual(reader.read(3), b'123')
        with self.assertRaises(ValueError):
            reader.read(2)
        header = tarfile.TarInfo('pax')
        header.type, header.size = tarfile.XHDTYPE, 2**32
        malicious = gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT))
        with self.assertRaises((ValueError, tarfile.ReadError)):
            inspect_bundle(malicious, COMMIT)
        header.size = 5*1024**2
        expanded = gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT)+bytes(header.size))
        with patch('heist.runtime_bundle.MAX_BYTES', 65536), self.assertRaises(ValueError):
            inspect_bundle(expanded, COMMIT)

    def test_activation_rejects_modified_installation_and_never_switches_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root/'versions'/COMMIT
            version.mkdir(parents=True)
            (version/'source.py').write_text('pass\n')
            receipt = {'source_commit': COMMIT, 'artifact_sha256': 'b'*64,
                       'inventory': {'files': {'source.py': digest(b'pass\n')}, 'links': {}}}
            (version/'installation.json').write_text(json.dumps(receipt))
            self.assertEqual(activate(root, COMMIT, 'b'*64)['source_commit'], COMMIT)
            self.assertEqual((root/'current').resolve(), version)
            (version/'source.py').write_text('changed\n')
            with self.assertRaises(ValueError):
                activate(root, COMMIT, 'b'*64)
            self.assertEqual((root/'current').resolve(), version)
            with self.assertRaises(ValueError):
                verify(version, '../../outside')

    def test_private_interpreter_is_refused_before_an_unusable_runtime_can_be_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)/'python3.12'
            private.write_bytes(b'placeholder')
            private.chmod(0o755)
            with patch('sys._base_executable', str(private)), self.assertRaises(ValueError):
                public_interpreter()
