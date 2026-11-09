"""Render the static React/loopback Flask Apache boundary without shell input."""
from pathlib import Path
import re

from heist.security.tls import server_name


def render(template, *, web_root, certificate, certificate_key, hostname, api_port=8001, bind='*:443'):
    values = {'WEB_ROOT': web_root, 'CERTIFICATE': certificate, 'CERTIFICATE_KEY': certificate_key}
    for name, value in values.items():
        path = Path(value)
        if (not path.is_absolute() or '..' in path.parts or str(path) != value or
                re.fullmatch(r'/[A-Za-z0-9_./+-]+', value) is None):
            raise ValueError('Use a normalized Apache filesystem path: '+name)
    if type(api_port) is not int or not 1024 <= api_port <= 65535:
        raise ValueError('Use an unprivileged loopback API port')
    if re.fullmatch(r'(?:\*|127\.0\.0\.1):[0-9]{1,5}', bind) is None or not 1 <= int(bind.rsplit(':', 1)[1]) <= 65535:
        raise ValueError('Use the public TLS listener or an isolated loopback listener')
    values.update(SERVER_NAME=server_name(hostname), API_PORT=str(api_port), BIND=bind)
    if set(re.findall(r'@([A-Z_]+)@', template)) != set(values):
        raise ValueError('Unexpected Apache template placeholders')
    for name, value in values.items():
        template = template.replace('@'+name+'@', value)
    return template
