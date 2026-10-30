"""Validated infrastructure VM sizing and non-destructive storage configuration."""
import json
import os
import subprocess


def vm_resources(environment=None):
    environment = os.environ if environment is None else environment
    result = {}
    for role, memory in (('WEBSERVER', 16384), ('DATABASE', 32768)):
        values = {}
        for option, default in (('MEMORY', memory), ('CORES', 4)):
            name = f'{role}_VM_{option}'
            try:
                value = int(environment.get(name, str(default)))
            except (ValueError, TypeError):
                raise ValueError(f'{name} must be a positive integer') from None
            if value <= 0:
                raise ValueError(f'{name} must be a positive integer')
            values[option.lower()] = value
        result[role.lower()] = values
    return result


def enable_ova_storage(image_storage):
    """Add import to local without replacing other storage definitions/options.

    Validate image storage before making changes. Directory-backed pilots can
    choose local for images as well; normal installations keep local-lvm.
    """
    def config(name):
        return json.loads(subprocess.check_output(
            ['pvesh', 'get', f'/storage/{name}', '--output-format', 'json']))

    target = config(image_storage)
    if image_storage != 'local' and 'images' not in target.get('content', '').split(','):
        raise ValueError(f'Image storage {image_storage} does not support images')
    local = target if image_storage == 'local' else config('local')
    contents = set(filter(None, local.get('content', '').split(',')))
    contents.add('import')
    if image_storage == 'local':
        contents.add('images')
    subprocess.run(['pvesm', 'set', 'local', '--content', ','.join(sorted(contents))], check=True)
