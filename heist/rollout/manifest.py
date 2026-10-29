"""Validate a release against immutable Git objects before touching an installation."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


@dataclass(frozen=True)
class Migration:
    identifier: str
    path: str
    sha256: str


@dataclass(frozen=True)
class Plan:
    schema: int
    installation: str
    source: str
    target: str
    version: str
    manifest_path: str
    manifest_sha256: str
    config_sha256: str
    migrations: tuple[Migration, ...]
    web_before: tuple[str, ...]
    web_after: tuple[str, ...]
    protected_tables: tuple[str, ...] = ('users', 'completed_challenges', 'challenge_flags')
    source_version: str = 'unknown'
    rollback: bool = False

    def to_dict(self):
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['migrations'] = tuple(Migration(**item) for item in data['migrations'])
        for name in ('web_before', 'web_after', 'protected_tables'):
            data[name] = tuple(data[name])
        return cls(**data)


def git(repository, *arguments):
    return subprocess.check_output(['git', '-C', str(repository), *arguments])


def revision(repository, reference):
    return git(repository, 'rev-parse', '--verify', '--end-of-options', reference + '^{commit}').decode().strip()


def blob(repository, commit, name):
    return git(repository, 'show', commit + ':' + name)


def safe_relative(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('Unsafe release path: ' + name)
    return name


def web_files(repository, commit, *, production):
    result = []
    entries = git(repository, 'ls-tree', '-r', '-z', commit, '--', 'webserver/html/').split(b'\0')
    for entry in entries:
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        name = raw_name.decode().removeprefix('webserver/html/')
        safe_relative(name)
        if metadata.split()[0] not in (b'100644', b'100755'):
            raise ValueError('Web release contains a link or unsupported member: ' + name)
        if name.split('/')[0] in ('vendor', 'uploads') or '.env' in PurePosixPath(name).parts:
            raise ValueError('Runtime data must not be tracked as web release source: ' + name)
        if production and (name.split('/')[0] in ('tests', 'mocks') or name == 'phpunit.xml'):
            continue
        result.append(name)
    return tuple(sorted(result))


def build_plan(repository, target, manifest_path, config_sha256):
    repository = Path(repository).resolve()
    source = revision(repository, 'HEAD')
    target = revision(repository, target)
    manifest_path = safe_relative(manifest_path)
    body = blob(repository, target, manifest_path)
    release = json.loads(body)
    required = {'schema', 'version', 'supported_from', 'migrations', 'protected_tables'}
    if set(release) != required or release['schema'] != 1:
        raise ValueError('Unsupported or incomplete release manifest')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', release['version']):
        raise ValueError('Release version must be a semantic version')
    if source not in release['supported_from']:
        raise ValueError('Installed commit has no declared/tested upgrade path in this release')
    if source == target:
        raise ValueError('Target is already installed')
    # Protocol v1 installs source, not new system/Python/Composer dependencies.
    for name in ('setup/requirements.txt', 'webserver/html/composer.lock'):
        old = git(repository, 'ls-tree', source, '--', name)
        new = git(repository, 'ls-tree', target, '--', name)
        if old != new:
            raise ValueError('Release needs a dependency migration not supported by protocol v1: ' + name)
    old_composer = json.loads(blob(repository, source, 'webserver/html/composer.json'))
    new_composer = json.loads(blob(repository, target, 'webserver/html/composer.json'))
    for key in ('require', 'require-dev', 'repositories', 'scripts', 'config'):
        if old_composer.get(key) != new_composer.get(key):
            raise ValueError('Release changes Composer dependencies/plugins/scripts; an explicit adapter is required')
    if not release['protected_tables'] or any(not re.fullmatch(r'[a-z_][a-z0-9_]*', name) for name in release['protected_tables']):
        raise ValueError('Declare protected student/grade tables')
    migrations = []
    identifiers = set()
    for item in release['migrations']:
        if set(item) != {'id', 'path', 'sha256'} or not re.fullmatch(r'[A-Za-z0-9_-]+', item['id']):
            raise ValueError('Invalid migration declaration')
        if item['id'] in identifiers:
            raise ValueError('Duplicate migration identifier')
        identifiers.add(item['id'])
        path = safe_relative(item['path'])
        payload = blob(repository, target, path)
        if hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise ValueError('Migration checksum differs: ' + item['id'])
        migrations.append(Migration(item['id'], path, item['sha256']))
    # Syntax validation uses compile only, never imports trusted deployment code.
    for name in git(repository, 'ls-tree', '-r', '--name-only', target).decode().splitlines():
        if name.endswith('.py'):
            compile(blob(repository, target, name), name, 'exec')
    import tomllib
    source_version=tomllib.loads(blob(repository,source,'pyproject.toml').decode())['project']['version']
    if tomllib.loads(blob(repository,target,'pyproject.toml').decode())['project']['version']!=release['version']:
        raise ValueError('Release manifest and package versions differ')
    return Plan(1, str(repository), source, target, release['version'], manifest_path,
        hashlib.sha256(body).hexdigest(), config_sha256, tuple(migrations),
        web_files(repository, source, production=False), web_files(repository, target, production=True), tuple(release['protected_tables']),source_version)
