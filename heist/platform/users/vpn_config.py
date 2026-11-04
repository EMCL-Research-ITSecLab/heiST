"""Publish a private, complete VPN profile while holding the certificate CA lock."""
import ipaddress
import os

from .vpn_files import Settings, atomic_file, ca_lock, easy_rsa, endpoint, identifier, read_private, valid_certificate


def get_user_config(user_id, db_conn, *, settings=None):
    settings = settings or Settings()
    name = identifier(user_id)
    with ca_lock(settings):
        with db_conn.cursor() as cursor:
            cursor.execute('SELECT vpn_static_ip FROM users WHERE id = %s', (user_id,))
            row = cursor.fetchone()
        if row is None or row[0] is None:
            raise ValueError('VPN account or address is unavailable')
        address = ipaddress.IPv4Address(row[0])
        host = endpoint(os.environ.get('VPN_SERVER_IP'))
        target = settings.root/'client-configs'/(name+'.ovpn')
        certificate = settings.ca/'pki/issued'/(name+'.crt')
        private_key = settings.ca/'pki/private'/(name+'.key')
        if certificate.exists() or private_key.exists():
            if not certificate.is_file() or not private_key.is_file() or not valid_certificate(settings, name):
                raise RuntimeError('VPN certificate requires administrator reconciliation')
        else:
            easy_rsa(settings, 'build-client-full', name, 'nopass')
            if not valid_certificate(settings, name):
                raise RuntimeError('Generated VPN certificate has an unexpected account identity')
        # A previous interrupted generation may already have a valid certificate.
        # Reuse it; never revoke another successful request as error cleanup.
        ca = read_private(settings.ca/'pki/ca.crt').decode('ascii')
        cert = read_private(certificate).decode('ascii')
        key = read_private(private_key).decode('ascii')
        tls = read_private(settings.ca/'ta.key').decode('ascii')
        configuration = f'''client
dev tun
proto udp
remote {host} 1194
remote-cert-tls server
resolv-retry infinite
nobind
persist-key
persist-tun
verb 3
explicit-exit-notify 2
key-direction 1
tun-mtu 1338
mssfix 1290
<ca>
{ca}
</ca>
<cert>
{cert}
</cert>
<key>
{key}
</key>
<tls-auth>
{tls}
</tls-auth>
'''
        atomic_file(settings.root/'ccd'/name, f'ifconfig-push {address} 255.255.255.0\n'.encode('ascii'))
        atomic_file(target, configuration.encode('ascii'))
        return str(target)
