"""
CTF Layer 1 Monitoring Setup Script
Sets up network monitoring with Suricata + ClickHouse + Grafana for CTF infrastructure
"""

import os
import subprocess
import sys
import argparse
import hashlib
from dotenv import load_dotenv
import textwrap
import base64
import shlex
sys.stdout.reconfigure(line_buffering=True)

# Load environment variables
load_dotenv()
from monitoring.utils.script_helper import (
    log_info, log_debug, log_error, log_warning, log_success, log_section,
    execute_remote_command, execute_remote_command_with_key, scp_file, Timer, time_function, DEBUG_MODE
)

# Load environment variables
load_dotenv()

# ==== CONFIGURATION CONSTANTS ====
SSH_USER = os.getenv("MONITORING_VM_USER", "ubuntu")
NEW_SSH_PASSWORD = os.getenv("MONITORING_VM_PASSWORD", "meow1234")
MONITORING_IP = os.getenv("MONITORING_HOST", "10.0.0.103")
PROXMOX_IP = os.getenv("PROXMOX_HOST", "10.0.0.1")
DATABASE_IP = os.getenv("DATABASE_HOST", "10.0.0.102")
MONITORING_CTF_INTERFACE = os.getenv("MONITORING_VPN_INTERFACE", "ctf_monitoring")
SSL_TLS_CERTS_DIR = os.getenv("SSL_TLS_CERTS_DIR", "/root/heiST/setup/certs")
FULLCHAIN_FILE = f"{SSL_TLS_CERTS_DIR}/fullchain.pem"
PRIVKEY_FILE = f"{SSL_TLS_CERTS_DIR}/privkey.pem"
CLICKHOUSE_HTTPS_PORT = os.getenv("CLICKHOUSE_HTTPS_PORT", "8443")
CLICKHOUSE_NATIVE_PORT = os.getenv("CLICKHOUSE_NATIVE_PORT", "9440")
CLICKHOUSE_SQL_DIR = os.getenv("CLICKHOUSE_SQL_DIR", "/root/heiST/monitoring/clickhouse/sql")
PROXMOX_SSH_KEYFILE = os.getenv("PROXMOX_SSH_KEYFILE", "/root/.ssh/id_rsa.pub")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "changeme")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_VERSION = "25.8.32.4"


@time_function
def configure_ssl():
    """
    Configure SSL certificates for ClickHouse - PROPERLY FIXED VERSION
    """
    log_section("Configuring SSL for ClickHouse")

    # Create certificate directory
    execute_remote_command_with_key(MONITORING_IP, "sudo mkdir -p /etc/clickhouse-server/certs", ssh_key_path=PROXMOX_SSH_KEYFILE)

    # Copy certificate files
    scp_file(FULLCHAIN_FILE, "/tmp/fullchain.pem", MONITORING_IP, SSH_USER, NEW_SSH_PASSWORD)
    scp_file(PRIVKEY_FILE, "/tmp/privkey.pem", MONITORING_IP, SSH_USER, NEW_SSH_PASSWORD)

    # Move and secure certificates
    ssl_commands = [
        "sudo mv /tmp/fullchain.pem /etc/clickhouse-server/certs/fullchain.pem",
        "sudo mv /tmp/privkey.pem /etc/clickhouse-server/certs/privkey.pem",
        "sudo chown -R clickhouse:clickhouse /etc/clickhouse-server/certs",
        "sudo chmod 640 /etc/clickhouse-server/certs/fullchain.pem",
        "sudo chmod 640 /etc/clickhouse-server/certs/privkey.pem"
    ]

    for cmd in ssl_commands:
        execute_remote_command_with_key(MONITORING_IP, cmd, ssh_key_path=PROXMOX_SSH_KEYFILE)

    # Create SSL config using individual commands WITHOUT shell=True
    # This ensures heredoc works properly
    ssl_config_commands = [
        "sudo mkdir -p /etc/clickhouse-server/config.d",
        """sudo tee /etc/clickhouse-server/config.d/ssl.yaml > /dev/null << 'EOF'
listen_host: 0.0.0.0

https_port: 8443
tcp_port_secure: 9440

openSSL:
  server:
    certificateFile: /etc/clickhouse-server/certs/fullchain.pem
    privateKeyFile: /etc/clickhouse-server/certs/privkey.pem
    disableProtocols: 'sslv2,sslv3,tlsv1,tlsv1_1'
EOF""",
        "sudo chown clickhouse:clickhouse /etc/clickhouse-server/config.d/ssl.yaml",
        "sudo chmod 640 /etc/clickhouse-server/config.d/ssl.yaml"
    ]

    # Execute WITHOUT shell=True to preserve heredoc syntax
    for cmd in ssl_config_commands:
        execute_remote_command_with_key(
            MONITORING_IP,
            cmd,
            ssh_key_path=PROXMOX_SSH_KEYFILE,
            shell=False  # This is crucial!
        )

    log_success("SSL configuration file created")

    # Restart ClickHouse
    execute_remote_command_with_key(
        MONITORING_IP,
        "sudo systemctl restart clickhouse-server",
        ssh_key_path=PROXMOX_SSH_KEYFILE
    )

    # Verify the file was created correctly
    execute_remote_command_with_key(
        MONITORING_IP,
        "sudo cat /etc/clickhouse-server/config.d/ssl.yaml",
        ssh_key_path=PROXMOX_SSH_KEYFILE
    )

    log_success("SSL configuration completed")


@time_function
def install_clickhouse():
    """
    Install and configure ClickHouse database
    """
    log_section("Installing ClickHouse")

    execute_remote_command_with_key(
        MONITORING_IP,
        "sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gnupg",
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    execute_remote_command_with_key(
        MONITORING_IP,
        "curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | sudo gpg --batch --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg",
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    repo_line = "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main"
    repo_line_b64 = base64.b64encode(repo_line.encode()).decode()

    execute_remote_command_with_key(
        MONITORING_IP,
        f"echo {repo_line_b64} | base64 -d | sudo tee /etc/apt/sources.list.d/clickhouse.list > /dev/null",
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    execute_remote_command_with_key(
        MONITORING_IP,
        f"""sudo tee /etc/apt/preferences.d/clickhouse >/dev/null <<'EOF'
        Package: clickhouse-server clickhouse-client clickhouse-common-static
        Pin: version {CLICKHOUSE_VERSION}
        Pin-Priority: 1001
        EOF""",
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    execute_remote_command_with_key(
        MONITORING_IP,
        f"""sudo apt-get update && \
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
        clickhouse-common-static={CLICKHOUSE_VERSION} \
        clickhouse-client={CLICKHOUSE_VERSION} \
        clickhouse-server={CLICKHOUSE_VERSION}""",
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    execute_remote_command_with_key(
        MONITORING_IP,
        "sudo systemctl enable --now clickhouse-server",
        ssh_key_path=PROXMOX_SSH_KEYFILE
    )

    log_success("ClickHouse installation completed")


@time_function
def set_clickhouse_default_password():
    """
    Set default ClickHouse user password using SHA256 hash
    """
    log_section("Configuring ClickHouse default user password")

    # Compute SHA256 hash
    sha256_hash = hashlib.sha256(CLICKHOUSE_PASSWORD.encode()).hexdigest()
    log_debug(f"SHA256 hash for ClickHouse default user: {sha256_hash}")

    # Prepare users.d file content - INCLUDE profile and other necessary settings
    users_d_content = f"""<clickhouse>
  <users>
    <{CLICKHOUSE_USER}>
      <password remove="true"/>
      <password_sha256_hex>{sha256_hash}</password_sha256_hex>
      <profile>default</profile>
      <networks>
        <ip>127.0.0.1</ip>
        <ip>10.0.0.0/24</ip>
      </networks>
      <access_management>1</access_management>
      <named_collection_control>1</named_collection_control>
    </{CLICKHOUSE_USER}>
  </users>
</clickhouse>"""

    users_d_path = "/etc/clickhouse-server/users.d/01_default_password.xml"

    # Encode payload to base64 so we can safely transport it as one token
    encoded = base64.b64encode(users_d_content.encode("utf-8")).decode("ascii")
    encoded_quoted = shlex.quote(encoded)

    cmd = textwrap.dedent(f"""\
        sudo mkdir -p /etc/clickhouse-server/users.d/
        echo {encoded_quoted} | base64 -d | sudo tee {shlex.quote(users_d_path)} > /dev/null
        sudo chown clickhouse:clickhouse {shlex.quote(users_d_path)}
        sudo chmod 640 {shlex.quote(users_d_path)}
        sudo systemctl restart clickhouse-server
    """)

    execute_remote_command_with_key(
        MONITORING_IP,
        cmd,
        ssh_key_path=PROXMOX_SSH_KEYFILE,
        shell=True
    )

    log_success("ClickHouse default user password configured successfully")


@time_function
def setup_database_schemas():
    """
    Set up ClickHouse database schemas and tables
    """
    log_section("Setting up database schemas")

    # Copy SQL schema files
    schema_files = [
        f"{CLICKHOUSE_SQL_DIR}/clickhouse_suri_vpn.sql",
        f"{CLICKHOUSE_SQL_DIR}/clickhouse_suri_dmz.sql",
        f"{CLICKHOUSE_SQL_DIR}/clickhouse_suri_backend.sql",
        f"{CLICKHOUSE_SQL_DIR}/clickhouse_zeek_vpn.sql"
    ]

    for schema_file in schema_files:
        if os.path.exists(schema_file):
            scp_file(schema_file, f"/tmp/{os.path.basename(schema_file)}", MONITORING_IP, SSH_USER, NEW_SSH_PASSWORD)
        else:
            log_warning(f"Schema file not found: {schema_file}")

    # Execute SQL schemas
    db_commands = [
        f"clickhouse-client --multiquery -u {CLICKHOUSE_USER} --password {CLICKHOUSE_PASSWORD} < /tmp/clickhouse_suri_vpn.sql",
        f"clickhouse-client --multiquery -u {CLICKHOUSE_USER} --password {CLICKHOUSE_PASSWORD} < /tmp/clickhouse_suri_dmz.sql",
        f"clickhouse-client --multiquery -u {CLICKHOUSE_USER} --password {CLICKHOUSE_PASSWORD} < /tmp/clickhouse_suri_backend.sql",
        f"clickhouse-client --multiquery -u {CLICKHOUSE_USER} --password {CLICKHOUSE_PASSWORD} < /tmp/clickhouse_zeek_vpn.sql"
    ]

    for cmd in db_commands:
        execute_remote_command_with_key(MONITORING_IP, cmd, ssh_key_path=PROXMOX_SSH_KEYFILE, shell=True)

    log_success("Database schemas setup completed")

@time_function
def setup_firewall():
    """
    Add firewall rules
    """

    log_section("Setting up firewall rules")

    execute_remote_command_with_key(MONITORING_IP, f"sudo ufw allow {CLICKHOUSE_HTTPS_PORT}/tcp")

    log_success("Firewall rules setup completed")


@time_function
def install_remote_monitoring():
    """
    Main function to install and configure monitoring infrastructure
    """
    log_section("Starting monitoring infrastructure setup")

    # Install ClickHouse
    install_clickhouse()

    # Configure SSL
    configure_ssl()

    # Change Clickhouse default password
    set_clickhouse_default_password()

    # Set up database schemas
    setup_database_schemas()

    setup_firewall()

def main():
    """
    Main execution function
    """
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description="CTF Monitoring Infrastructure Setup Script")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    DEBUG_MODE = args.debug

    try:
        with Timer():
            log_info("Setting up monitoring VM with ClickHouse and monitoring pipeline")
            install_remote_monitoring()
            log_success("Monitoring pipeline setup complete")
    except Exception as e:
        log_error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()