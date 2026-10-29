"""Immutable agent payloads loaded before any checkout switch can replace source."""
from pathlib import Path

_DIRECTORY = Path(__file__).resolve().parent
_AGENT = (_DIRECTORY / 'guest_agent.py').read_text()
FIREWALL = (_DIRECTORY / 'guest_firewall.py').read_text()


def _action(name):
    return _AGENT + '\nmain(' + repr(name) + ')\n'


INSTALL_GUARD = _action('guard')
CAPTURE_SERVICES = _action('capture')
QUIESCE = _action('quiesce')
DEPLOY = _action('deploy')
LOCAL_HEALTH = _action('health')
FINISH = _action('finish')
