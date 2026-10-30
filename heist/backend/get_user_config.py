import subprocess
import os
from heist.environment import load_backend_env as load_dotenv
import fcntl
import time

from heist.backend.delete_user_config import delete_user_config

load_dotenv()

LOCK_FILE = "/var/lock/easy_rsa.lock"


def get_user_config(user_id, db_conn):
    """
    Create a user configuration for a challenge.
    """

    client_config_dir = "/etc/openvpn/client-configs"
    client_config_path = os.path.join(client_config_dir, f"{user_id}.ovpn")
    if os.path.exists(client_config_path):
        return client_config_path

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT vpn_static_ip FROM users WHERE id = %s", (user_id,))
        result = cursor.fetchone()
        if result is None:
            raise ValueError(f"User with ID {user_id} not found.")

    static_ip = result[0]

    try:
        easy_rsa_dir = "/etc/openvpn/easy-rsa"
        easy_rsa_binary = os.path.join(easy_rsa_dir, "easyrsa")

        ccd_dir = "/etc/openvpn/ccd"
        ccd_file = os.path.join(ccd_dir, str(user_id))

        vpn_server_ip = os.getenv("VPN_SERVER_IP")

        # Ensure necessary directories exist
        os.makedirs(ccd_dir, exist_ok=True)
        os.makedirs(client_config_dir, exist_ok=True)

        # Generate client certificate and key
        env = os.environ.copy()
        env["EASYRSA"] = "/etc/openvpn/easy-rsa"
        env["EASYRSA_PKI"] = "/etc/openvpn/easy-rsa/pki"
        env['EASYRSA_BATCH'] = '1'

        timeout = 30
        start = time.time()
        with open(LOCK_FILE, 'w') as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break  # acquired
                except BlockingIOError:
                    if time.time() - start > timeout:
                        raise TimeoutError(f"Could not acquire lock within {timeout}s")
                    time.sleep(0.1)  # back off a bit

            try:
                subprocess.run(
                    [easy_rsa_binary, "--batch", "build-client-full", str(user_id), "nopass"],
                    cwd=easy_rsa_dir, check=True, env=env, capture_output=True
                )
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

        # Assign static IP to the client
        with open(ccd_file, 'w') as f:
            f.write(f"ifconfig-push {static_ip} 255.255.255.0\n")

        ca_crt_path = os.path.join(easy_rsa_dir, "pki", "ca.crt")
        if not os.path.exists(ca_crt_path):
            raise FileNotFoundError(f"CA certificate not found at {ca_crt_path}")

        cert_path = os.path.join(easy_rsa_dir, "pki", "issued", f"{user_id}.crt")
        if not os.path.exists(cert_path):
            raise FileNotFoundError(f"Client certificate not found at {cert_path}")

        key_path = os.path.join(easy_rsa_dir, "pki", "private", f"{user_id}.key")
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Client key not found at {key_path}")

        ta_key_path = os.path.join(easy_rsa_dir, "ta.key")
        if not os.path.exists(ta_key_path):
            raise FileNotFoundError(f"TLS auth key not found at {ta_key_path}")

        # Read the contents of the keys
        ca_crt = open(ca_crt_path).read()
        cert = open(cert_path).read()
        key = open(key_path).read()
        ta_key = open(ta_key_path).read()

        client_config = f"""client
dev tun
proto udp
remote {vpn_server_ip} 1194
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
{ca_crt}
</ca>
<cert>
{cert}
</cert>
<key>
{key}
</key>
<tls-auth>
{ta_key}
</tls-auth>
"""

        with open(client_config_path, 'w') as config:
            config.write(client_config)

        return client_config_path

    except Exception as e:
        # Clean up if an error occurs
        delete_user_config(user_id)
        raise e
