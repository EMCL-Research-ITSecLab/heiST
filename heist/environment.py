"""Explicit component configuration with read-only compatibility for old installs.

New configuration belongs in config/*.env (or an explicit HEIST_*_ENV path).
Older deployments keep working without moving private files during Git checkout.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def environment_file(component):
    explicit = os.environ.get('HEIST_' + component.upper() + '_ENV')
    if explicit:
        return Path(explicit)
    legacy = 'setup' if component == 'installer' else component
    package = 'installer' if component == 'installer' else component
    candidates = [ROOT/'config'/(component+'.env'), ROOT/'heist'/package/'.env', ROOT/legacy/'.env']
    return next((path for path in candidates if path.is_file()), candidates[0])


def _load(component, dotenv_path=None, **options):
    from dotenv import load_dotenv
    path = Path(dotenv_path) if dotenv_path and Path(dotenv_path).is_file() else environment_file(component)
    result = load_dotenv(path, **options)
    # Only translate packaged resource paths. Private keys/certificates stay put.
    resource_keys = ('BACKEND_FILES_DIR', 'MONITORING_FILES_DIR', 'GRAFANA_FILES_SETUP_DIR',
                     'WAZUH_FILE_DIR', 'CLICKHOUSE_SQL_DIR', 'VECTOR_FILES_DIR', 'SSL_TLS_CERTS_DIR')
    for key in resource_keys:
        value = os.environ.get(key)
        if not value:
            continue
        for old, new in (('backend', 'heist/backend'), ('setup', 'heist/installer'), ('monitoring', 'heist/monitoring')):
            source = ROOT/old
            try:
                relative = Path(value).relative_to(source)
            except ValueError:
                continue
            target = ROOT/new/relative
            if target.exists():
                os.environ[key] = str(target)
            break
    return result


def load_backend_env(dotenv_path=None, **options):
    return _load('backend', dotenv_path, **options)


def load_installer_env(dotenv_path=None, **options):
    return _load('installer', dotenv_path, **options)
