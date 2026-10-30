import os
import subprocess
import fcntl

LOCK_FILE = "/var/lock/easy_rsa.lock"


def delete_user_config(user_id):
    """
    Removes an OpenVPN client configuration, keys, and related files.
    """

    easy_rsa_dir = "/etc/openvpn/easy-rsa"
    ccd_dir = "/etc/openvpn/ccd"
    client_config_dir = "/etc/openvpn/client-configs"

    files_to_remove = [
        (os.path.join(client_config_dir, f"{user_id}.ovpn")),
        (os.path.join(easy_rsa_dir, "pki", "issued", f"{user_id}.crt")),
        (os.path.join(easy_rsa_dir, "pki", "private", f"{user_id}.key")),
        (os.path.join(easy_rsa_dir, "pki", "reqs", f"{user_id}.req")),
        (os.path.join(ccd_dir, str(user_id)))
    ]

    for path in files_to_remove:
        if os.path.isfile(path):
            os.remove(path)

    # Generate client certificate and key
    env = os.environ.copy()
    env["EASYRSA"] = "/etc/openvpn/easy-rsa"
    env["EASYRSA_PKI"] = "/etc/openvpn/easy-rsa/pki"
    env['EASYRSA_BATCH'] = '1'

    with open(LOCK_FILE, 'w') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            subprocess.run(["./easyrsa", "--batch", "revoke", str(user_id)],
                           cwd=easy_rsa_dir, check=True, capture_output=True, env=env)
        except Exception:
            pass

        try:
            subprocess.run(["./easyrsa", "gen-crl"], cwd=easy_rsa_dir, check=True, capture_output=True, env=env)
        except Exception:
            pass

        try:
            subprocess.run(["cp", os.path.join(easy_rsa_dir, "pki", "crl.pem"), "/etc/openvpn/"],
                           check=True, capture_output=True)
        except Exception:
            pass
        fcntl.flock(lock_file, fcntl.LOCK_UN)
