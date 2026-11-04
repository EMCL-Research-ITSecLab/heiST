"""Fail-closed certificate revocation before removing any account VPN material."""
from .vpn_files import (Settings, ca_lock, certificate_states, disconnect, easy_rsa,
                        identifier, publish_crl, require_revocation_configuration, valid_certificate)


def delete_user_config(user_id, *, settings=None):
    settings = settings or Settings()
    name = identifier(user_id)
    with ca_lock(settings):
        files = [settings.root/'client-configs'/(name+'.ovpn'), settings.ca/'pki/issued'/(name+'.crt'),
                 settings.ca/'pki/private'/(name+'.key'), settings.ca/'pki/reqs'/(name+'.req'), settings.root/'ccd'/name]
        # Account IDs are reused by the legacy database. A live certificate must
        # be revoked even when a previous partial cleanup removed its files.
        states = certificate_states(settings, name)
        active = 'V' in states
        if not states and not any(path.exists() or path.is_symlink() for path in files):
            return
        require_revocation_configuration(settings)
        if active:
            easy_rsa(settings, 'revoke', name)
            if valid_certificate(settings, name):
                raise RuntimeError('VPN certificate revocation was not recorded')
        publish_crl(settings)
        disconnect(settings, name)
        # Preserve the CA index/revocation history. Only remove this user's leaf
        # files after the published CRL and disconnection have both succeeded.
        for path in files:
            if path.is_symlink():
                raise RuntimeError('Unexpected symbolic link in private VPN files')
            path.unlink(missing_ok=True)
