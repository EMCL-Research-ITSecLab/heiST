"""Refresh VPN revocation expiry without changing issued certificates or users."""
from .vpn_files import Settings, ca_lock, publish_crl, require_revocation_configuration


def renew(settings=None):
    settings = settings or Settings()
    with ca_lock(settings):
        require_revocation_configuration(settings)
        publish_crl(settings)


if __name__ == '__main__':
    renew()
    print('VPN certificate revocation list refreshed')
